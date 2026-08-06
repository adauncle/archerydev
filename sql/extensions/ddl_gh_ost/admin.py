"""gh-ost 任务 admin。"""

from django.contrib import admin
from django.utils.html import format_html

from .models import DdlGhostTask


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
