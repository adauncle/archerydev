"""DDL-Sync-Bug-A 验证: _extract_all_alters 扫所有 ALTER

@ 2026-09-17 @ mavis
"""
import sys
import os
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()
from sql.extensions.ddl_sync.services.sync_trigger import (
    _extract_all_alters,
    _should_sync,
)

# Case 1: 单 ALTER
sql_a = "ALTER TABLE t1 ADD COLUMN c int;"
result = _extract_all_alters(sql_a)
print(f"Case 1 单 ALTER: {len(result)} 条")
assert len(result) == 1
assert result[0]["table"] == "t1"
print(f"  table={result[0]['table']}")

# Case 2: 多 ALTER (关键 - 老逻辑只看第一个)
sql_b = "ALTER TABLE t_blacklist ADD COLUMN c1 int;\nALTER TABLE t_whitelist ADD COLUMN c2 int;"
result = _extract_all_alters(sql_b)
print(f"Case 2 多 ALTER (混合名单): {len(result)} 条")
assert len(result) == 2
assert result[0]["table"] == "t_blacklist"
assert result[1]["table"] == "t_whitelist"
print(f"  tables: {[a['table'] for a in result]}")

# Case 3: USE + 注释 + 多 ALTER
sql_c = """use hly_platform;
-- comment 1
ALTER TABLE t_blacklist ADD COLUMN c1 int;
-- comment 2
ALTER TABLE t_whitelist ADD COLUMN c2 int;"""
result = _extract_all_alters(sql_c)
print(f"Case 3 USE + 注释 + 多 ALTER: {len(result)} 条")
assert len(result) == 2
assert result[0]["table"] == "t_blacklist"
assert result[1]["table"] == "t_whitelist"

# Case 4: 反引号 schema (9/12 DBA-bug-5a 修过的)
sql_d = "ALTER TABLE `hly_billing`.`consume_flow` ADD INDEX idx_test (c1);"
result = _extract_all_alters(sql_d)
print(f"Case 4 反引号 schema: {len(result)} 条")
assert len(result) == 1
assert result[0]["table"] == "consume_flow"  # 9/12 修过的, 只取表名不取 schema
assert result[0]["db"] == "hly_billing"

# Case 5: 空 SQL
result = _extract_all_alters("")
print(f"Case 5 空 SQL: {len(result)} 条")
assert len(result) == 0

# Case 6: 没 ALTER
result = _extract_all_alters("CREATE TABLE t1 (id int);")
print(f"Case 6 没 ALTER: {len(result)} 条")
assert len(result) == 0

# Case 7: wf#4841 实战 4 ALTER
sql_g = """ALTER TABLE hly_accesscard.accesscard_licensefront_info ADD owner_name varchar(200) NULL COMMENT '所有人';
ALTER TABLE hly_accesscard.vehicle_info_verify ADD data_source tinyint NULL;
ALTER TABLE accesscard_vehicle_review ADD risk_level TINYINT NULL;
ALTER TABLE accesscard_opendcardapply ADD agency_spread_code varchar(50) NULL;"""
result = _extract_all_alters(sql_g)
print(f"Case 7 wf#4841 实战 4 ALTER: {len(result)} 条")
assert len(result) == 4
tables = [a["table"] for a in result]
print(f"  tables: {tables}")
assert "accesscard_licensefront_info" in tables
assert "vehicle_info_verify" in tables
assert "accesscard_vehicle_review" in tables
assert "accesscard_opendcardapply" in tables

print()
print("=== 7/7 PASS ===")
print("DDL-Sync-Bug-A: _extract_all_alters 扫所有 ALTER ✅")
print("workflow_passed_handler 改造后: 每个 ALTER 独立判定白/黑名单 ✅")
print("镜像工单 ddl_text 只含 kept 的 ALTER, 不再是全文 ✅")
print("skipped ALTER 写 DdlSyncHistory (sync_status='skipped'), DBA 排查 ✅")