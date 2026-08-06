"""gh-ost 任务 admin。"""

from django.contrib import admin, messages
from django.utils.html import format_html

from .models import DdlGhostTask
from .services.notify import notify_terminal
from .services.runner import stop_ghost_process


@admin.register(DdlGhostTask)
class DdlGhostTaskAdmin(admin.ModelAdmin):
    list_display = (
        "id", "workflow_link", "status_badge", "current_stage",
        "progress_bar", "enabled", "cut_over_strategy",
        "precheck_passed", "started_at", "finished_at", "created_at",
    )
    list_filter = ("status", "enabled", "cut_over_strategy", "precheck_passed")
    search_fields = (
        "workflow__workflow_name", "workflow__id",
        "audit__audit_id", "table_name", "db_name",
    )
    raw_id_fields = ("workflow", "audit")
    readonly_fields = (
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
    actions = ["admin_cancel", "admin_retry", "admin_rollback"]

    def workflow_link(self, obj):
        url = f"/admin/sql/sqlworkflow/{obj.workflow_id}/change/"
        return format_html('<a href="{}">工单 #{} {}</a>',
                           url, obj.workflow_id,
                           obj.workflow.workflow_name or "")
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

    @admin.action(description="重试选中的 gh-ost 任务（仅 failed/cancelled）")
    def admin_retry(self, request, queryset):
        from .services.poller import start_poller
        from .services.runner import start_ghost_process
        from django.utils import timezone as tz
        n = 0
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
        self.message_user(request, f"已重试 {n} 个任务")

    @admin.action(description="回滚选中的 gh-ost 任务（drop 影子表）")
    def admin_rollback(self, request, queryset):
        from .db import _get_creds
        import pymysql
        n = 0
        for task in queryset:
            if task.status not in ("success", "failed", "cancelled"):
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
        self.message_user(request, f"已回滚 {n} 个任务")
