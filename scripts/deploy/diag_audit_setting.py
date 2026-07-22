"""临时诊断：查 sql_workflow_audit_setting 表当前状态。"""
import os
import sys

sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()

from django.db import connection

cur = connection.cursor()
print("=" * 70)
print("1) 所有 sql_ 开头的表")
print("=" * 70)
cur.execute("SHOW TABLES LIKE 'sql_%'")
for r in cur.fetchall():
    print("  " + r[0])

print()
print("=" * 70)
print("2) 找包含 'audit' 或 'workflow' 的表")
print("=" * 70)
cur.execute("SHOW TABLES")
for r in cur.fetchall():
    name = r[0]
    if "audit" in name.lower() or "workflow" in name.lower() or "setting" in name.lower():
        print("  " + name)

print()
print("=" * 70)
print("3) 找上游 model WorkflowAuditSetting 实际表名")
print("=" * 70)
from django.apps import apps
for m in apps.get_app_configs():
    for model in m.get_models():
        if "audit" in model.__name__.lower() or "workflow" in model.__name__.lower():
            try:
                print("  %s.%s -> %s" % (m.name, model.__name__, model._meta.db_table))
            except Exception:
                pass

print()
print("=" * 70)
print("4) DESCRIBE workflow_audit_setting")
print("=" * 70)
cur.execute("DESCRIBE workflow_audit_setting")
for r in cur.fetchall():
    print("  " + " | ".join(str(c) for c in r))

print()
print("=" * 70)
print("5) ALL rows in workflow_audit_setting")
print("=" * 70)
cur.execute("SELECT id, group_id, group_name, workflow_type, audit_auth_groups FROM workflow_audit_setting ORDER BY group_id, workflow_type")
rows = cur.fetchall()
if not rows:
    print("  (empty)")
else:
    for r in rows:
        print("  id=%s group_id=%s group_name=%r workflow_type=%s audit_auth_groups=%r" % r)

print()
print("=" * 70)
print("6) 测试组 (group_id=25) 的设置")
print("=" * 70)
cur.execute("SELECT id, group_id, group_name, workflow_type, audit_auth_groups FROM workflow_audit_setting WHERE group_id=25")
rows = cur.fetchall()
if not rows:
    print("  (empty) ← 这就是问题：测试组没配置 SQL 上线审流，")
    print("           所以 /submitsql/ 拿不到 auditors，弹 '请配置审批流程'")
else:
    for r in rows:
        print("  id=%s group_id=%s group_name=%r workflow_type=%s audit_auth_groups=%r" % r)

print()
print("=" * 70)
print("7) ResourceGroup 25 (测试组) 是否存在")
print("=" * 70)
cur.execute("SELECT group_id, group_name, is_deleted FROM sql_resourcegroup WHERE group_id=25")
for r in cur.fetchall():
    print("  group_id=%s group_name=%r is_deleted=%s" % r)

print()
print("=" * 70)
print("8) archery 用户的资源组")
print("=" * 70)
cur.execute("""
SELECT u.username, u.is_superuser, rg.group_id, rg.group_name
FROM sql_users u
LEFT JOIN sql_users_resource_group ur ON ur.users_id = u.id
LEFT JOIN sql_resourcegroup rg ON rg.group_id = ur.resourcegroup_id
WHERE u.username='archery'
ORDER BY rg.group_id
""")
for r in cur.fetchall():
    print("  user=%s is_superuser=%s group_id=%s group_name=%r" % r)
