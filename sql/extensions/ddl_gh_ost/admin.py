"""gh-ost 任务 admin。"""

from django.contrib import admin, messages
from django.utils.html import format_html

from .models import DdlGhostTask
from .services.notify import notify_terminal
from .services.runner import stop_ghost_process


@admin.register(DdlGhostTask)
class DdlGhostTaskAdmin(admin.ModelAdmin):
    ## CUSTOM-MODIFIED: v0.4.5-alpha 加 task_type 列表 + 兼容 rebuild @ 2026-08-06 @ mavis
    list_display = (
        "id", "task_type_badge", "source_link",
        "status_badge", "current_stage",
        "progress_bar", "enabled", "cut_over_strategy",
        "precheck_passed", "started_at", "finished_at", "created_at",
    )
    list_filter = (
        "task_type", "status", "enabled", "cut_over_strategy", "precheck_passed",
    )
    search_fields = (
        "workflow__workflow_name", "workflow__id",
        "audit__audit_id", "table_name", "db_name",
        "target_table",
    )
    raw_id_fields = ("workflow", "audit")
    ## CUSTOM-MODIFIED: v0.4.5-alpha 加 task_type 字段 + rebuild 字段只读 @ 2026-08-06 @ mavis
    readonly_fields = (
        "task_type", "target_table", "related_task_id",
        "precheck_report", "precheck_at",
        "original_table_size_bytes", "disk_free_bytes",
        "ghost_pid", "systemd_scope_unit",
        "progress_pct", "progress_rows_copied", "progress_rows_total",
        "progress_speed_rows_per_sec", "progress_eta_seconds",
        "progress_threads_running", "progress_message", "last_heartbeat_at",
        "stderr_tail", "error_message",
        "created_at", "updated_at", "started_at", "finished_at",
    )
    date_hierarchy = "created_at"
    ordering = ("-id",)
    ## CUSTOM-MODIFIED: v0.4.5-alpha admin_retry 兼容 rebuild @ 2026-08-06 @ mavis
    actions = ["admin_cancel", "admin_retry", "admin_rollback", "admin_batch_rebuild"]

    # ===== 列展示 =====
    ## CUSTOM-MODIFIED: v0.4.5-alpha 加 task_type_badge 颜色徽章 @ 2026-08-06 @ mavis
    def task_type_badge(self, obj):
        color = {
            "ghost": "#409EFF",     # 蓝
            "rebuild": "#67C23A",   # 绿
        }.get(obj.task_type, "#909399")
        label = {
            "ghost": "gh-ost DDL",
            "rebuild": "碎片回收",
        }.get(obj.task_type, obj.task_type)
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:12px;">{}</span>',
            color, label,
        )
    task_type_badge.short_description = "任务类型"

    ## CUSTOM-MODIFIED: v0.4.5-alpha source_link 区分 ghost 工单 / rebuild 表 @ 2026-08-06 @ mavis
    def source_link(self, obj):
        if obj.task_type == "rebuild":
            # rebuild: 显示 db.table
            target = obj.target_table or f"{obj.db_name}.{obj.table_name}"
            return format_html(
                '<span style="color:#67C23A;">📊 {}</span>',
                target,
            )
        # ghost: 显示工单链接
        if obj.workflow_id:
            url = f"/admin/sql/sqlworkflow/{obj.workflow_id}/change/"
            return format_html('<a href="{}">工单 #{} {}</a>',
                               url, obj.workflow_id,
                               obj.workflow.workflow_name or "")
        return format_html('<span style="color:#909399;">—</span>')
    source_link.short_description = "来源"

    # 保留原 workflow_link 兼容旧代码引用（admin 行内调用）
    def workflow_link(self, obj):
        return self.source_link(obj)
    workflow_link.short_description = "SQL 工单"

    def status_badge(self, obj):
        color = {
            "pending": "#909399",
            "precheck_failed": "#F56C6C",
            "queued": "#E6A23C",
            "running": "#409EFF",
            "cut_over": "#67C23A",
            "success": "#67C23A",
            "failed": "#F56C6C",
            "cancelled": "#909399",
            "rolled_back": "#909399",
        }.get(obj.status, "#909399")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:12px;">{}</span>',
            color, obj.get_status_display(),
        )
    status_badge.short_description = "状态"

    def progress_bar(self, obj):
        pct = obj.progress_pct or 0
        color = "#67C23A" if obj.status == "success" else "#409EFF"
        return format_html(
            '<div style="background:#f0f0f0;border-radius:4px;width:140px;'
            'height:18px;position:relative;">'
            '<div style="background:{};height:18px;border-radius:4px;'
            'width:{}%;"></div>'
            '<div style="position:absolute;top:0;left:0;width:140px;'
            'text-align:center;font-size:12px;line-height:18px;">'
            '{}%</div></div>',
            color, pct, pct,
        )
    progress_bar.short_description = "进度"

    # ===== admin actions =====
    @admin.action(description="取消选中的 gh-ost 任务")
    def admin_cancel(self, request, queryset):
        n = 0
        for task in queryset:
            if task.is_terminal:
                continue
            if task.ghost_pid:
                stop_ghost_process(task.ghost_pid, timeout=5)
            task.status = "cancelled"
            from django.utils import timezone as tz
            task.finished_at = tz.now()
            task.error_message = (task.error_message or "") + "\n[admin] 手动取消"
            task.save()
            try:
                notify_terminal(task)
            except Exception:  # noqa: BLE001
                pass
            n += 1
        self.message_user(request, f"已取消 {n} 个任务")

    ## CUSTOM-MODIFIED: v0.4.5-alpha admin_retry 兼容 rebuild @ 2026-08-06 @ mavis
    @admin.action(description="重试选中的 gh-ost 任务（仅 failed/cancelled）")
    def admin_retry(self, request, queryset):
        from .services.poller import start_poller
        from .services.runner import start_ghost_process
        from .services.rebuild import start_rebuild_process
        from .services.db import _get_creds
        from django.utils import timezone as tz
        n = 0
        skipped_rebuild_no_instance = 0
        for task in queryset:
            if task.status not in ("failed", "cancelled"):
                continue
            if not task.precheck_passed:
                continue
            # 重置
            task.status = "queued"
            task.started_at = None
            task.finished_at = None
            task.ghost_pid = None
            task.current_stage = ""
            task.progress_pct = 0
            task.error_message = ""
            task.stderr_tail = ""
            task.save()
            try:
                # CUSTOM: rebuild 任务 workflow=NULL，从 related_task_id 推断 instance，
                # 简化方案：让 DBA 通过端点触发 retry（admin 暂不支持）
                if task.task_type == "rebuild":
                    # rebuild task 没有 instance 字段，admin retry 暂不支持
                    # DBA 应通过 POST /gh_ost/rebuild/start/ 重新触发
                    skipped_rebuild_no_instance += 1
                    task.status = "failed"
                    task.error_message = "[admin] rebuild task retry 不支持（请通过端点 /gh_ost/rebuild/start/ 重新触发）"
                    task.save()
                    continue
                instance = task.workflow.instance
                pid = start_ghost_process(task, instance=instance)
                task.ghost_pid = pid
                task.status = "running"
                task.started_at = tz.now()
                task.save()
                start_poller(task.id)
                n += 1
            except Exception as exc:  # noqa: BLE001
                task.status = "failed"
                task.error_message = f"retry 启动失败：{exc}"
                task.save()
        msg = f"已重试 {n} 个任务"
        if skipped_rebuild_no_instance:
            msg += f"（跳过 {skipped_rebuild_no_instance} 个 rebuild —— 请用端点 /gh_ost/rebuild/start/ 触发）"
        self.message_user(request, msg)

    @admin.action(description="回滚选中的 gh-ost 任务（drop 影子表）")
    def admin_rollback(self, request, queryset):
        # CUSTOM-MODIFIED: import 路径修 services.db @ 2026-08-27 @ mavis
        # 关联: docs/changelogs/2026-08-27_rollback-import-path-fix.md
        from .services.db import _get_creds
        import pymysql
        n = 0
        skipped = 0
        for task in queryset:
            if task.status not in ("success", "failed", "cancelled"):
                continue
            # CUSTOM: rebuild 任务无 instance 信息，admin rollback 暂不支持
            if task.task_type == "rebuild":
                task.status = "rolled_back"
                task.finished_at = __import__("django.utils.timezone", fromlist=["now"]).now()
                task.save()
                n += 1
                continue
            instance = task.workflow.instance
            try:
                user, password, (host, port) = _get_creds(instance)
                conn = pymysql.connect(
                    host=host, port=port, user=user, password=password,
                    database=task.db_name, connect_timeout=5, autocommit=True,
                )
                try:
                    with conn.cursor() as cur:
                        for tbl in [task.ghost_table_name, f"_{task.table_name}_del"]:
                            if tbl:
                                cur.execute(f"DROP TABLE IF EXISTS `{task.db_name}`.`{tbl}`")
                finally:
                    conn.close()
            except Exception as exc:  # noqa: BLE001
                self.message_user(request, f"task #{task.id} 回滚异常：{exc}", level=messages.WARNING)
                continue
            from django.utils import timezone as tz
            task.status = "rolled_back"
            task.finished_at = tz.now()
            task.save()
            n += 1
        if skipped:
            self.message_user(request, f"跳过 {skipped} 个 rebuild（直接标 rolled_back，无影子表可 drop）", level=messages.INFO)
        self.message_user(request, f"已回滚 {n} 个任务")

    ## CUSTOM-MODIFIED: v0.4.5-alpha 加 admin_batch_rebuild action @ 2026-08-06 @ mavis
    @admin.action(description="批量触发 rebuild（仅 task_type=rebuild 有效，需要 instance_id）")
    def admin_batch_rebuild(self, request, queryset):
        """DBA 在 admin 列表勾选 rebuild 任务 → 批量触发。

        注意：rebuild 任务 workflow=NULL 没有 instance 字段，这里只对
        ``task_type=rebuild`` 且 ``related_task_id`` 非空（关联归档任务）的 task 有效。
        实际触发走 view ``rebuild_start`` —— 走端点更稳。
        """
        rebuild_tasks = queryset.filter(task_type="rebuild")
        if not rebuild_tasks.exists():
            self.message_user(
                request,
                "没有 task_type=rebuild 的任务被选中",
                level=messages.WARNING,
            )
            return
        # alpha 阶段 admin 暂不直接触发，引导 DBA 走端点
        ids = list(rebuild_tasks.values_list("id", flat=True))
        self.message_user(
            request,
            f"rebuild batch trigger alpha 阶段请走端点：POST /gh_ost/rebuild/start/ "
            f"入参 {{instance_id, db, table}}（task ids: {ids[:10]}{'...' if len(ids) > 10 else ''}）",
            level=messages.INFO,
        )
