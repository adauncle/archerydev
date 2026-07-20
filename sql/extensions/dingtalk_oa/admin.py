"""Django admin 注册。"""

from django.contrib import admin

from .models import (
    ApprovalFlow,
    ApprovalPolicy,
    CoreBusinessTable,
    DingtalkOaEventLog,
    GroupDingtalkAuditor,
    SqlTypeRegistry,
    WorkflowAuditExternal,
)


@admin.register(SqlTypeRegistry)
class SqlTypeRegistryAdmin(admin.ModelAdmin):
    list_display = (
        "code", "category", "description", "default_severity",
        "is_critical", "is_active",
    )
    list_filter = ("category", "default_severity", "is_critical", "is_active")
    search_fields = ("code", "description", "pattern")
    ordering = ("category", "code")


@admin.register(CoreBusinessTable)
class CoreBusinessTableAdmin(admin.ModelAdmin):
    list_display = (
        "id", "instance", "db_name", "table_name",
        "level", "is_active", "created_by", "updated_at",
    )
    list_filter = ("instance", "level", "is_active")
    search_fields = ("db_name", "table_name", "remark")
    autocomplete_fields = ("instance",)


@admin.register(ApprovalFlow)
class ApprovalFlowAdmin(admin.ModelAdmin):
    list_display = (
        "code", "name", "audit_driver",
        "dingtalk_process_code", "is_active", "updated_at",
    )
    list_filter = ("audit_driver", "is_active")
    search_fields = ("code", "name", "description")


class ApprovalPolicyInline(admin.TabularInline):
    """在 ``ApprovalFlow`` 详情页内联展示引用此 flow 的策略。"""
    model = ApprovalPolicy
    extra = 0
    fields = ("name", "priority", "is_enabled", "severity")
    show_change_link = True


# 让 ApprovalFlow 详情页显示引用它的策略
ApprovalFlowAdmin.inlines = [ApprovalPolicyInline]


@admin.register(ApprovalPolicy)
class ApprovalPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "id", "name", "priority", "is_enabled",
        "severity", "flow", "updated_at",
    )
    list_filter = ("is_enabled", "severity", "flow", "sql_type_match_mode")
    search_fields = ("name", "description")
    autocomplete_fields = ("flow",)
    filter_horizontal = ("sql_types",)


@admin.register(GroupDingtalkAuditor)
class GroupDingtalkAuditorAdmin(admin.ModelAdmin):
    list_display = (
        "id", "group", "resource_group",
        "dingtalk_dept_id", "is_active", "updated_at",
    )
    list_filter = ("is_active", "group", "resource_group")
    search_fields = ("dingtalk_user_ids", "dingtalk_dept_id")
    autocomplete_fields = ("group", "resource_group")


@admin.register(WorkflowAuditExternal)
class WorkflowAuditExternalAdmin(admin.ModelAdmin):
    list_display = (
        "id", "audit", "source", "external_status",
        "external_process_instance_id", "last_synced_at",
    )
    list_filter = ("source", "external_status")
    search_fields = (
        "external_process_instance_id", "external_process_code",
    )
    readonly_fields = ("payload",)


@admin.register(DingtalkOaEventLog)
class DingtalkOaEventLogAdmin(admin.ModelAdmin):
    list_display = (
        "id", "event_type", "audit", "processed", "created_at",
    )
    list_filter = ("event_type", "processed")
    search_fields = ("event_id", "audit__audit_id")
    readonly_fields = ("payload", "raw_payload_encrypted", "error", "created_at")
    date_hierarchy = "created_at"
