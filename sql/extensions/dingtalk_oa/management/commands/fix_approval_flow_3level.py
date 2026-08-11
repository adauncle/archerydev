"""一次性修复 3 个 flow 的 audit_auth_groups → 14,15,3 (3 级审批)。

设计背景: 2026-08-11 用户报"提交走审批没生效" 排查发现
ext_approval_flow 表 3 个 flow (default / normal / high_risk) 的 audit_auth_groups
都是 "3" (DBA 单级)——v0.1.4 (2026-07-22) 时 init_fallback_flow 占位是 "1,2"，
但 134 dev / 110 prod 实际配置被改成了 "3" 单级。

本命令:
    1. 列出 ext_approval_flow 当前所有 flow
    2. 把 code IN ('default', 'normal', 'high_risk') 的 flow 改成 audit_auth_groups='14,15,3'
    3. 跑完后 print 前后对比

关联 changelog: docs/changelogs/2026-08-11_approval-flow-3level-fix.md
关联设计: docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §11 决策 2

使用:
    python manage.py fix_approval_flow_3level
"""

from django.core.management.base import BaseCommand

from sql.extensions.dingtalk_oa.models import ApprovalFlow


# 3 个 flow 统一改成 3 级审批 (研发组长 14 → DBA组长 15 → DBA 3)
TARGET_FLOWS = ["default", "normal", "high_risk"]
TARGET_GROUPS = "14,15,3"


class Command(BaseCommand):
    help = "把 ext_approval_flow 3 个 flow 的 audit_auth_groups 改成 14,15,3 (3 级审批)"

    def handle(self, *args, **options):
        # 1) 改前
        self.stdout.write("=== 改前 (ext_approval_flow) ===")
        before = {f.code: f.audit_auth_groups for f in ApprovalFlow.objects.all()}
        for code in TARGET_FLOWS:
            v = before.get(code, "(缺失)")
            self.stdout.write(f"  {code}: audit_auth_groups = {v!r}")

        # 2) 改 (idempotent)
        updated = 0
        for code in TARGET_FLOWS:
            flow, _ = ApprovalFlow.objects.update_or_create(
                code=code,
                defaults={"audit_auth_groups": TARGET_GROUPS},
            )
            updated += 1
            self.stdout.write(self.style.SUCCESS(
                f"  ✅ {code}: audit_auth_groups = {TARGET_GROUPS!r}"
            ))

        # 3) 改后
        self.stdout.write()
        self.stdout.write("=== 改后 (ext_approval_flow) ===")
        after = {f.code: f.audit_auth_groups for f in ApprovalFlow.objects.all()}
        for code in TARGET_FLOWS:
            self.stdout.write(f"  {code}: audit_auth_groups = {after.get(code, '(缺失)')!r}")

        self.stdout.write()
        self.stdout.write(self.style.SUCCESS(
            f"✅ 完成: 更新 {updated} 个 flow 的 audit_auth_groups = '{TARGET_GROUPS}'"
        ))
        self.stdout.write(self.style.WARNING(
            f"⚠️  如果实际审批组不是 14/15/3, 请到 admin 改 (DBA / DBA 组长)"
        ))
