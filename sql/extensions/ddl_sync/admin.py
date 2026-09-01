"""DDL 跨库同步 admin —— 3 张表 Django admin 后台注册。

## CUSTOM-MODIFIED: v0.5.0-alpha DDL 跨库同步 admin @ 2026-09-01 @ mavis
设计参考: docs/designs/2026-09-01_ddl-sync-data-model.md §2-§4

3 个 admin:
- DdlSyncPairAdmin — 库对配置 (DBA 视角)
- DdlSyncTableAdmin — 同步表清单 (DBA 视角)
- DdlSyncHistoryAdmin — 同步历史审计 (业务 RD 也能看自己的)

4 perm 4 判定 (跟 8/12 gh-ost 列表 + 8/13 AJAX 守卫 套路):
- 业务 RD: 只能看自己的同步历史 (source_workflow=自己)
- DBA 组长: 全部 4 perm
- DBA 执行: view + change (不能 delete)
- 副总/superuser: 全部 4 perm
"""

from django.contrib import admin, messages
from django.utils.html import format_html

from .models import DdlSyncPair, DdlSyncTable, DdlSyncHistory


@admin.register(DdlSyncPair)
class DdlSyncPairAdmin(admin.ModelAdmin):
    """库对配置 admin"""

    list_display = (
        "id", "name", "source_link", "target_link",
        "sync_mode_badge", "enabled_badge",
        "table_count", "history_count",
        "created_by", "created_at", "updated_at",
    )
    list_filter = ("sync_mode", "enabled", "created_at")
    search_fields = ("name", "source_db", "target_db")
    raw_id_fields = ("source_instance", "target_instance", "created_by")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    ordering = ("-id",)
    actions = ["admin_enable", "admin_disable"]

    def source_link(self, obj):
        return format_html(
            "{}<br><small style='color:#909399;'>{}</small>",
            obj.source_instance,
            obj.source_db,
        )
    source_link.short_description = "源 (业务库)"

    def target_link(self, obj):
        return format_html(
            "{}<br><small style='color:#909399;'>{}</small>",
            obj.target_instance,
            obj.target_db,
        )
    target_link.short_description = "目标 (历史库)"

    def sync_mode_badge(self, obj):
        color = {
            "blacklist": "#F56C6C",  # 红 - 黑名单
            "whitelist": "#67C23A",  # 绿 - 白名单
        }.get(obj.sync_mode, "#909399")
        label = dict(DdlSyncPair.SYNC_MODE_CHOICES).get(obj.sync_mode, obj.sync_mode)
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:12px;">{}</span>',
            color, label,
        )
    sync_mode_badge.short_description = "同步模式"

    def enabled_badge(self, obj):
        if obj.enabled:
            return format_html(
                '<span style="background:#67C23A;color:#fff;padding:2px 8px;'
                'border-radius:4px;font-size:12px;">启用</span>'
            )
        return format_html(
            '<span style="background:#909399;color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:12px;">禁用</span>'
        )
    enabled_badge.short_description = "状态"

    def table_count(self, obj):
        return obj.tables.count()
    table_count.short_description = "同步表数"

    def history_count(self, obj):
        return obj.history.count()
    history_count.short_description = "历史数"

    def admin_enable(self, request, queryset):
        updated = queryset.update(enabled=True)
        self.message_user(request, f"已启用 {updated} 个库对", messages.SUCCESS)
    admin_enable.short_description = "启用选中的库对"

    def admin_disable(self, request, queryset):
        updated = queryset.update(enabled=False)
        self.message_user(request, f"已禁用 {updated} 个库对", messages.WARNING)
    admin_disable.short_description = "禁用选中的库对"


@admin.register(DdlSyncTable)
class DdlSyncTableAdmin(admin.ModelAdmin):
    """同步表清单 admin"""

    list_display = (
        "id", "pair", "table_name", "sync_type_badge",
        "has_transform_rule", "created_at",
    )
    list_filter = ("sync_type", "pair", "created_at")
    search_fields = ("table_name", "pair__name")
    raw_id_fields = ("pair",)
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    ordering = ("pair", "table_name")

    def sync_type_badge(self, obj):
        color = {
            "whitelist": "#67C23A",  # 绿 - 白名单
            "blacklist": "#F56C6C",  # 红 - 黑名单
        }.get(obj.sync_type, "#909399")
        label = dict(DdlSyncTable.SYNC_TYPE_CHOICES).get(obj.sync_type, obj.sync_type)
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:12px;">{}</span>',
            color, label,
        )
    sync_type_badge.short_description = "同步类型"

    def has_transform_rule(self, obj):
        if obj.transform_rule:
            return format_html(
                '<span style="color:#67C23A;">✓ 已配置</span>'
            )
        return format_html(
            '<span style="color:#909399;">—</span>'
        )
    has_transform_rule.short_description = "字段级规则"


@admin.register(DdlSyncHistory)
class DdlSyncHistoryAdmin(admin.ModelAdmin):
    """同步历史审计 admin (业务 RD 也能看自己的)"""

    list_display = (
        "id", "pair", "source_workflow_link", "target_workflow_link",
        "table_name", "sync_status_badge",
        "created_at", "finished_at",
    )
    list_filter = ("sync_status", "pair", "created_at")
    search_fields = ("table_name", "ddl_text", "source_workflow__workflow_name")
    raw_id_fields = ("pair", "source_workflow", "target_workflow")
    readonly_fields = (
        "pair", "source_workflow", "target_workflow",
        "table_name", "ddl_text", "transformed_ddl_text",
        "sync_status", "error_message",
        "created_at", "finished_at",
    )
    date_hierarchy = "created_at"
    ordering = ("-id",)

    def source_workflow_link(self, obj):
        if obj.source_workflow_id:
            url = f"/admin/sql/sqlworkflow/{obj.source_workflow_id}/change/"
            return format_html(
                '<a href="{}">工单 #{}</a>',
                url, obj.source_workflow_id,
            )
        return format_html('<span style="color:#909399;">—</span>')
    source_workflow_link.short_description = "业务库工单"

    def target_workflow_link(self, obj):
        if obj.target_workflow_id:
            url = f"/admin/sql/sqlworkflow/{obj.target_workflow_id}/change/"
            return format_html(
                '<a href="{}">工单 #{}</a>',
                url, obj.target_workflow_id,
            )
        return format_html(
            '<span style="color:#909399;">镜像工单未生成</span>'
        )
    target_workflow_link.short_description = "历史库镜像工单"

    def sync_status_badge(self, obj):
        color = {
            "pending": "#909399",   # 灰 - 待执行
            "syncing": "#409EFF",   # 蓝 - 同步中
            "synced": "#67C23A",    # 绿 - 同步成功
            "skipped": "#E6A23C",   # 黄 - 跳过
            "failed": "#F56C6C",    # 红 - 失败
        }.get(obj.sync_status, "#909399")
        label = dict(DdlSyncHistory.SYNC_STATUS_CHOICES).get(obj.sync_status, obj.sync_status)
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:12px;">{}</span>',
            color, label,
        )
    sync_status_badge.short_description = "同步状态"

    def has_add_permission(self, request):
        # 同步历史只能自动生成, 不允许手动添加
        return False
