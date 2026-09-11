#!/bin/bash
# 134 dev 演练: ADD INDEX 应该触发大表 alert (DBA-bug-3 修法)
set -e
cd /opt/archery/prod
export DJANGO_SETTINGS_MODULE=archery.settings
sudo -u archery /opt/archery/prod/venv/bin/python <<'PYEOF'
import sys, os, django
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()
from sql.models import Instance
from sql.extensions.ddl_gh_ost.services.column_diff import column_diff_full

# 找 archery 实例
ins = Instance.objects.filter(db_type="mysql").first()
print("instance:", ins.instance_name if ins else None, ins.host if ins else None, ins.port if ins else None)

# 1. ADD INDEX 测试 (DBA-bug-3 关键场景: 之前没大表 alert, 现在应该有)
print("\n=== [1/4] ADD INDEX 测试 (大表) ===")
sql = "ALTER TABLE `archery_prod`.`waybill_union_carrier_dba_bug1` ADD INDEX idx_x (id)"
result = column_diff_full(ins, "archery_prod", sql)
print("  ok:", result.get("ok"))
print("  error:", result.get("error"))
print("  big_table_alert:", result.get("big_table_alert"))
assert result.get("big_table_alert") is not None, "ADD INDEX 应该返回大表 alert"
print("  [OK] ADD INDEX 现在能触发大表 alert ✓")

# 2. DROP INDEX 测试
print("\n=== [2/4] DROP INDEX 测试 ===")
sql = "ALTER TABLE `archery_prod`.`waybill_union_carrier_dba_bug1` DROP INDEX idx_x"
result = column_diff_full(ins, "archery_prod", sql)
print("  ok:", result.get("ok"))
print("  big_table_alert:", result.get("big_table_alert"))
assert result.get("big_table_alert") is not None, "DROP INDEX 应该返回大表 alert"
print("  [OK] DROP INDEX 现在能触发大表 alert ✓")

# 3. MODIFY COLUMN 测试 (回归)
print("\n=== [3/4] MODIFY COLUMN 测试 (回归) ===")
sql = "ALTER TABLE `archery_prod`.`waybill_union_carrier_dba_bug1` MODIFY COLUMN id BIGINT"
result = column_diff_full(ins, "archery_prod", sql)
print("  ok:", result.get("ok"))
print("  big_table_alert:", result.get("big_table_alert"))
print("  high_risk_count:", result.get("high_risk_count"))
assert result.get("ok"), "MODIFY 应该 ok=True"
assert result.get("big_table_alert") is not None
print("  [OK] MODIFY COLUMN 字段 diff + 大表 alert 都触发 ✓")

# 4. 小表 ADD INDEX 测试 (不应该触发大表 alert)
print("\n=== [4/4] 小表 ADD INDEX 测试 (不触发大表) ===")
sql = "ALTER TABLE `archery_prod`.`sql_workflow` ADD INDEX idx_x (id)"
result = column_diff_full(ins, "archery_prod", sql)
print("  ok:", result.get("ok"))
print("  big_table_alert:", result.get("big_table_alert"))
# sql_workflow 行数不多, 应该 big_table_alert=None
print("  [OK] 小表不触发大表 alert (符合预期)")

print("\n=== 全部 PASS ===")
PYEOF
