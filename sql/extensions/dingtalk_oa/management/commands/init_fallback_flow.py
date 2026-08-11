"""创建默认兜底 flow。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §11 决策 2

使用：

    python manage.py init_fallback_flow

创建 code='default' 的 ApprovalFlow，所有 ApprovalPolicy 都不命中时走这个。

注意：``audit_auth_groups`` 默认填 ``'14,15,3'`` (研发组长→DBA组长→DBA)
多级审批组 ID 占位。**部署后如果实际审批组不是这个，需要到 admin 改**。
变更背景: v0.1.4 (2026-07-22) 时占位是 "1,2"，但 8/11 用户报"提交走审批没生效"
排查发现占位是 "3" (DBA 单级) 导致多级审批失效，本次统一改成 "14,15,3" 3 级。
"""

from django.core.management.base import BaseCommand

from sql.extensions.dingtalk_oa.models import ApprovalFlow


# 兜底 flow 的占位配置
FALLBACK_FLOW_CODE = "default"
FALLBACK_FLOW_NAME = "默认兜底（所有策略不命中时）"
FALLBACK_FLOW_DESCRIPTION = (
    "由 init_fallback_flow 命令创建。所有 ApprovalPolicy 都不命中时走这个 flow。"
    "audit_auth_groups 默认 '14,15,3' 表示研发组长→DBA组长→DBA 3 级审批。"
    "部署后如果实际审批组不是这个，需要到 admin 改。"
)
FALLBACK_PLACEHOLDER_GROUPS = "14,15,3"  # 部署后由 admin 修改


class Command(BaseCommand):
    help = "创建 code='default' 的兜底 ApprovalFlow（idempotent）"

    def handle(self, *args, **options):
        flow, created = ApprovalFlow.objects.update_or_create(
            code=FALLBACK_FLOW_CODE,
            defaults={
                "name": FALLBACK_FLOW_NAME,
                "description": FALLBACK_FLOW_DESCRIPTION,
                "audit_driver": "archery",  # 兜底走本地 Group 审批
                "audit_auth_groups": FALLBACK_PLACEHOLDER_GROUPS,
                "dingtalk_process_code": "",
                "is_active": True,
            },
        )
        action = "创建" if created else "更新"
        self.stdout.write(self.style.SUCCESS(
            f"{action} flow: {flow.code} ({flow.name})"
        ))
        if created:
            self.stdout.write(self.style.WARNING(
                f"⚠️  请到 admin 把 audit_auth_groups 从占位 "
                f"'{FALLBACK_PLACEHOLDER_GROUPS}' 改为实际审批组 ID"
            ))
