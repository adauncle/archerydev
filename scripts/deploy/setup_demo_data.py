"""
setup_demo_data.py
在 172.20.2.134 prod 上创建钉钉 OA 流程演示数据

依赖：
    - setup_test_group.py 必须先跑（建 group_id=25 测试组）
    - 需要 /etc/archery/dbops_password

步骤：
    1) 建测试 Instance（本机 MySQL 8.0）
    2) 改 default ApprovalFlow 的 audit_auth_groups (新驱动系统)
    3) 建 archery 内审 ApprovalFlow (normal)
    4) 建钉钉 OA ApprovalFlow (high_risk, 占位 process_code)
    5) 建 ApprovalPolicy 1: 高风险 → 钉钉 OA
    6) 建 ApprovalPolicy 2: 中风险 → archery 内审
    7) 建 CoreBusinessTable 示例
    8) 补 workflow_audit_setting 上游审流配置
       原因：/submitsql/ 页面通过 sql/utils/workflow_audit.py:691
       Audit.settings() 读的是上游 workflow_audit_setting 表，不补这条
       测试组的下拉会空，提交时弹 '请配置审批流程'。
    9) 打印最终状态
"""
import os
import sys
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()

from sql.models import Instance, WorkflowAuditSetting
from sql.extensions.dingtalk_oa.models import (
    SqlTypeRegistry, CoreBusinessTable, ApprovalFlow, ApprovalPolicy
)

DBOPS_PWD_FILE = "/etc/archery/dbops_password"
with open(DBOPS_PWD_FILE) as f:
    dbops_pwd = f.read().strip()


def get_sql_type(code):
    t, _ = SqlTypeRegistry.objects.get_or_create(
        code=code,
        defaults={"name": code, "category": "DDL" if code in ("ALTER", "DROP", "TRUNCATE", "RENAME", "CREATE") else "DML" if code in ("INSERT", "UPDATE", "DELETE", "REPLACE") else "DCL" if code in ("GRANT", "REVOKE", "SET") else "DQL", "default_severity": "low"},
    )
    return t


print("=" * 60)
print("1) 建测试 Instance（本机 MySQL 8.0）")
print("=" * 60)
inst, created = Instance.objects.get_or_create(
    instance_name="测试 MySQL 8.0",
    defaults={
        "type": "master",
        "db_type": "mysql",
        "host": "127.0.0.1",
        "port": 3306,
        "user": "dbops",
        "password": dbops_pwd,
        "db_name": "",
        "is_ssl": False,
    },
)
print(f"  Instance: {inst.instance_name} (id={inst.id}, created={created})")

print()
print("=" * 60)
print("2) 改 default ApprovalFlow 的 audit_auth_groups")
print("=" * 60)
default_flow = ApprovalFlow.objects.get(code="default")
default_flow.audit_auth_groups = "3"
default_flow.description = "由 init_fallback_flow 命令创建。所有 ApprovalPolicy 都不命中时走这个 flow。audit_auth_groups=3 表示 fallback 走 DBA 内审。"
default_flow.save()
print(f"  default flow.audit_auth_groups = {default_flow.audit_auth_groups!r}")

print()
print("=" * 60)
print("3) 建 archery 内审 ApprovalFlow（normal）")
print("=" * 60)
normal, created = ApprovalFlow.objects.get_or_create(
    code="normal",
    defaults={
        "name": "中低风险走 Archery 内审",
        "description": "中低风险 SQL 走 Archery 内审。audit_auth_groups=3 表示 DBA 组审批。",
        "audit_driver": "archery",
        "audit_auth_groups": "3",
        "dingtalk_process_code": "",
        "is_active": True,
    },
)
print(f"  Flow: code={normal.code!r} -> {normal.name!r} (created={created})")
print(f"    audit_driver={normal.audit_driver!r}, audit_auth_groups={normal.audit_auth_groups!r}")

print()
print("=" * 60)
print("4) 建钉钉 OA ApprovalFlow（high_risk）")
print("=" * 60)
high_risk, created = ApprovalFlow.objects.get_or_create(
    code="high_risk",
    defaults={
        "name": "高风险走钉钉 OA",
        "description": "高风险 SQL（DDL/DML 影响行 ≥100）走钉钉 OA 审批。dingtalk_process_code 是占位，需要在钉钉开放平台填实际模板 code。",
        "audit_driver": "dingtalk_oa",
        "audit_auth_groups": "3",
        "dingtalk_process_code": "PLACEHOLDER_REPLACE_WITH_REAL_CODE",
        "is_active": True,
    },
)
print(f"  Flow: code={high_risk.code!r} -> {high_risk.name!r} (created={created})")
print(f"    audit_driver={high_risk.audit_driver!r}, dingtalk_process_code={high_risk.dingtalk_process_code!r}")
print(f"    ⚠️  请到 admin 把 PLACEHOLDER 改成实际钉钉审批模板 code")

print()
print("=" * 60)
print("5) 建 ApprovalPolicy 1: 高风险 → 钉钉 OA")
print("=" * 60)
p1, created = ApprovalPolicy.objects.get_or_create(
    name="高风险 DDL/DML 走钉钉 OA",
    defaults={
        "priority": 100,
        "is_enabled": True,
        "severity": "high",
        "flow": high_risk,
        "sql_type_match_mode": "any",
        "min_affected_rows": 100,
        "max_affected_rows": None,
        "affected_rows_aggregate": "total",
        "require_core_table": False,
        "table_levels": "",
        "legacy_syntax_types": "",
    },
)
p1.sql_types.set([get_sql_type(c) for c in ["DELETE", "UPDATE", "DROP", "ALTER", "TRUNCATE"]])
print(f"  Policy: {p1.name!r} (id={p1.id}, created={created})")
print(f"    severity={p1.severity!r}, sql_types={[t.code for t in p1.sql_types.all()]}")
print(f"    min_affected_rows={p1.min_affected_rows}, max_affected_rows={p1.max_affected_rows}")
print(f"    flow -> {p1.flow.code} ({p1.flow.audit_driver})")

print()
print("=" * 60)
print("6) 建 ApprovalPolicy 2: 中风险 → archery 内审")
print("=" * 60)
p2, created = ApprovalPolicy.objects.get_or_create(
    name="中风险 DML 走 Archery 内审",
    defaults={
        "priority": 50,
        "is_enabled": True,
        "severity": "medium",
        "flow": normal,
        "sql_type_match_mode": "any",
        "min_affected_rows": 10,
        "max_affected_rows": 99,
        "affected_rows_aggregate": "total",
        "require_core_table": False,
        "table_levels": "",
        "legacy_syntax_types": "",
    },
)
p2.sql_types.set([get_sql_type(c) for c in ["DELETE", "UPDATE", "INSERT"]])
print(f"  Policy: {p2.name!r} (id={p2.id}, created={created})")
print(f"    severity={p2.severity!r}, sql_types={[t.code for t in p2.sql_types.all()]}")
print(f"    min_affected_rows={p2.min_affected_rows}, max_affected_rows={p2.max_affected_rows}")
print(f"    flow -> {p2.flow.code} ({p2.flow.audit_driver})")

print()
print("=" * 60)
print("7) 建 CoreBusinessTable 示例")
print("=" * 60)
cbt, created = CoreBusinessTable.objects.get_or_create(
    instance=inst,
    db_name="archery_prod",
    table_name="sql_users,sql_workflow",
    defaults={
        "level": "L1",
        "remark": "v0.1.3-prod 演示用 - 核心业务表（用户表 + 工单表）",
        "is_active": True,
    },
)
print(f"  CoreBusinessTable: {cbt.db_name}.{cbt.table_name} (id={cbt.id}, created={created})")
print(f"    level={cbt.level!r}, instance={cbt.instance.instance_name!r}")

print()
print("=" * 60)
print("8) 补 workflow_audit_setting (上游审流配置)")
print("=" * 60)
# 这一步是 /submitsql/ 页面下拉能显示审批流程的关键
# /submitsql/ 通过 Audit.settings(group_id, workflow_type) 读
# 上游 workflow_audit_setting 表 (见 sql/utils/workflow_audit.py:691)
# 不补这条 -> 表单校验 '请配置审批流程' -> 提交卡死
obj, created = WorkflowAuditSetting.objects.update_or_create(
    group_id=25, workflow_type=2,
    defaults={
        "group_name": "测试组",
        "audit_auth_groups": "3",  # 3 = DBA 组
    },
)
print(f"  {'✓ 新建' if created else '↻ 更新'} workflow_audit_setting "
      f"id={obj.audit_setting_id} group_id=25 workflow_type=2 "
      f"audit_auth_groups={obj.audit_auth_groups!r}")
print("  说明: 这是 *默认* 审流，提交后 ConfigurableAuditor 仍会按")
print("        ext_approval_flow 的策略匹配重新决定走 archery / dingtalk_oa")

print()
print("=" * 60)
print("9) 最终状态汇总")
print("=" * 60)
print(f"  Instance 数: {Instance.objects.count()}")
for x in Instance.objects.all():
    print(f"    - id={x.id} {x.instance_name!r} type={x.db_type} host={x.host}:{x.port}")
print(f"  ApprovalFlow 数: {ApprovalFlow.objects.count()}")
for f in ApprovalFlow.objects.all():
    print(f"    - code={f.code}: driver={f.audit_driver}, groups={f.audit_auth_groups!r}, active={f.is_active}")
print(f"  ApprovalPolicy 数: {ApprovalPolicy.objects.count()}")
for p in ApprovalPolicy.objects.all():
    print(f"    - {p.name}: severity={p.severity!r}, flow={p.flow.code}, rows=[{p.min_affected_rows},{p.max_affected_rows}]")
print(f"  CoreBusinessTable 数: {CoreBusinessTable.objects.count()}")
for c in CoreBusinessTable.objects.all():
    print(f"    - {c.db_name}.{c.table_name} level={c.level}")
print(f"  workflow_audit_setting (上游, /submitsql/ 用):")
for s in WorkflowAuditSetting.objects.filter(group_id=25):
    print(f"    - id={s.audit_setting_id} group_id={s.group_id} "
          f"workflow_type={s.workflow_type} audit_auth_groups={s.audit_auth_groups!r}")
print()
print("DONE - 刷新 /submitsql/ 页面，下拉应显示 'DBA'（来自 auth_group id=3）")
print("      之后点击 SQL检测 -> 提交，会走 ConfigurableAuditor 路由到正确的 driver")
