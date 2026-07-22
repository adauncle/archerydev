"""模拟前端 /api/v1/workflow/auditors/ 调 Audit.settings() 验证。"""
import os
import sys

sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()

from sql.utils.workflow_audit import Audit

# 这是前端 /api/v1/workflow/auditors/ 的核心调用
test_cases = [
    (25, "测试组"),
    (24, "prod AI"),
    (13, "prod 业务部"),
]

for group_id, group_name in test_cases:
    auth_groups = Audit.settings(group_id=group_id, workflow_type=2)
    print(f"  group_id={group_id:2d} ({group_name!r:20s})  "
          f"Audit.settings(workflow_type=2) -> {auth_groups!r}")

print()
print("DONE - 测试组 (group_id=25) 现在应返回 '3' (DBA 组)")
print("       刷新 /submitsql/ 页面，下拉应显示 'DBA'")
