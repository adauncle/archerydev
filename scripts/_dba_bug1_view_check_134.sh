#!/bin/bash
# 134 dev 验证 view 层 big_table_alert 上下文
set -e
cd /opt/archery/prod
export DJANGO_SETTINGS_MODULE=archery.settings
sudo -u archery /opt/archery/prod/venv/bin/python <<'PYEOF'
import sys, os, django
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()
from sql.models import SqlWorkflow
from sql.views import _parse_first_alter, _get_table_size_info

wf = SqlWorkflow.objects.get(id=9999)
print("=== wf#9999 ===")
print("  status:", wf.status)
print("  db_name:", wf.db_name)
print("  instance:", wf.instance.instance_name, wf.instance.host, wf.instance.port)

# 拿 SQL 内容
from sql.models import SqlWorkflowContent
content_obj = SqlWorkflowContent.objects.get(workflow=wf)
sql_text = content_obj.sql_content
print("  SQL:", repr(sql_text))

# 1. _parse_first_alter 测试
print("\n=== _parse_first_alter 测试 ===")
parsed = _parse_first_alter(sql_text)
print("  parsed:", parsed)
if not parsed or not parsed.get("table"):
    print("  [FAIL] 解析失败, 业务方 SQL 形态覆盖不到")
    sys.exit(1)

# 2. _get_table_size_info 测试
print("\n=== _get_table_size_info 测试 ===")
size_info = _get_table_size_info(
    instance=wf.instance,
    db_name=parsed.get("db") or wf.db_name,
    table_name=parsed["table"],
)
print("  size_info:", size_info)

# 3. 完整流程模拟
print("\n=== 完整流程模拟 (status_for_alert + big_table_alert) ===")
status_for_alert = wf.status in ("workflow_manreviewing", "workflow_review_pass")
print("  status_for_alert:", status_for_alert)
big_table_alert = None
if status_for_alert:
    if parsed and parsed.get("table") and size_info:
        row_threshold = 100000
        size_threshold_mb = 100
        if size_info["rows"] >= row_threshold or size_info["size_mb"] >= size_threshold_mb:
            big_table_alert = size_info
print("  big_table_alert:", big_table_alert)
if big_table_alert:
    print("  [OK] 审批中能触发大表 alert, DBA-bug-1 修法生效")
else:
    print("  [INFO] big_table_alert = None (waybill_union_carrier 在 134 dev 查不到或行数<阈值)")
PYEOF
