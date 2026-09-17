"""DBA-bug-10 演练: CREATE INDEX 视为 ALTER 类 (大表 alert + gh-ost + 字段 diff + 混合 DDL 检测)

@ 2026-09-17 @ mavis
"""
import sys
import os
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()

from sql.views import (
    _parse_first_alter,
    _parse_all_alters,
    _detect_non_alter,
    _check_mixed_ddl,
)
from sql.extensions.ddl_gh_ost.views import _parse_all_statements
from sql.extensions.ddl_sync.services.sync_trigger import _extract_all_alters as sync_extract_all_alters


def check(label, actual, expected):
    mark = "✅" if actual == expected else "❌"
    print(f"  {mark} {label}: 实际={actual!r} 期望={expected!r}")
    return actual == expected


print("=== Case 1: 单 CREATE INDEX (无 schema, USING BTREE) ===")
sql = "CREATE INDEX test USING BTREE ON hly_accesscard.accesscard_channel_task (req_url);"
r1 = _parse_first_alter(sql)
print(f"  _parse_first_alter: {r1}")
check("table", r1["table"], "accesscard_channel_task")
check("db", r1["db"], "hly_accesscard")

r2 = _parse_all_alters(sql)
check("count", len(r2), 1)
check("table", r2[0]["table"], "accesscard_channel_task")

r3 = _detect_non_alter(sql)
check("non_alter_count (CREATE INDEX 不归)", len(r3), 0)

r4 = _check_mixed_ddl(sql)
check("mixed_ddl ok (CREATE INDEX 不算混合)", r4["ok"], True)

r5 = _parse_all_statements(sql)
check("ghost stmts count", len(r5), 1)
check("ghost stmt_type=ALTER", r5[0]["stmt_type"], "ALTER")
check("ghost table", r5[0]["table"], "accesscard_channel_task")

r6 = sync_extract_all_alters(sql)
check("sync stmts count", len(r6), 1)

print()
print("=== Case 2: CREATE INDEX 反引号 schema ===")
sql = "CREATE INDEX `idx_x` ON `hly_billing`.`consume_flow` (`id`);"
r = _parse_first_alter(sql)
check("table", r["table"], "consume_flow")
check("db", r["db"], "hly_billing")

print()
print("=== Case 3: CREATE UNIQUE INDEX ===")
sql = "CREATE UNIQUE INDEX idx_u ON my_db.my_table (col1);"
r = _parse_first_alter(sql)
check("table", r["table"], "my_table")
r = _detect_non_alter(sql)
check("non_alter_count", len(r), 0)

print()
print("=== Case 4: CREATE FULLTEXT INDEX ===")
sql = "CREATE FULLTEXT INDEX idx_ft ON my_db.my_table (col_text);"
r = _parse_first_alter(sql)
check("table", r["table"], "my_table")
r = _detect_non_alter(sql)
check("non_alter_count", len(r), 0)

print()
print("=== Case 5: CREATE TABLE 不变 (应该归 CREATE) ===")
sql = "CREATE TABLE new_t (id int);"
r = _parse_first_alter(sql)
check("should be None", r is None, True)
r = _detect_non_alter(sql)
check("non_alter_count (CREATE TABLE 归 CREATE)", len(r), 1)
check("non_alter stmt_type", r[0]["stmt_type"], "CREATE")

print()
print("=== Case 6: 混合 ALTER + CREATE INDEX (不算混合) ===")
sql = (
    "ALTER TABLE hly_accesscard.accesscard_channel_task ADD COLUMN test_c int;\n"
    "CREATE INDEX idx_x ON hly_accesscard.accesscard_channel_task (col);\n"
)
r = _check_mixed_ddl(sql)
check("mixed_ddl ok", r["ok"], True)
r = _detect_non_alter(sql)
check("non_alter_count", len(r), 0)
r = _parse_all_alters(sql)
check("alters count (ALTER + CREATE INDEX)", len(r), 2)

print()
print("=== Case 7: 混合 CREATE TABLE + CREATE INDEX (应该判定混合) ===")
sql = (
    "CREATE TABLE new_t (id int);\n"
    "CREATE INDEX idx_x ON hly_accesscard.accesscard_channel_task (col);\n"
)
r = _check_mixed_ddl(sql)
check("mixed_ddl ok (CREATE INDEX 归 ALTER, CREATE TABLE 归 CREATE)", r["ok"], False)
check("types", "CREATE" in r["types"], True)

print()
print("=== Case 8: 业务方 wf#4849 实战工单 ===")
sql = (
    "use `hly_accesscard`;\n"
    "CREATE TABLE `consumetally_disputeorder_operation_log` (\n"
    "  `id` bigint NOT NULL COMMENT '主键ID',\n"
    "  PRIMARY KEY (`id`)\n"
    ") COMMENT='争议数据操作日志表';\n"
    "CREATE INDEX test USING BTREE ON hly_accesscard.accesscard_channel_task (req_url);\n"
)
# _parse_first_alter 返 None (第一条是 CREATE TABLE 不是 ALTER/CREATE INDEX, 符合预期)
r = _parse_first_alter(sql)
check("_parse_first_alter (首条不是 ALTER/CREATE INDEX 返 None)", r is None, True)

# 但 _parse_all_alters 应该扫到 CREATE INDEX (detail 页 big_table_alert 用这个)
r = _parse_all_alters(sql)
check("all_alters count (含 CREATE INDEX)", len(r), 1)
check("all_alters[0] table", r[0]["table"], "accesscard_channel_task")
check("all_alters[0] db", r[0]["db"], "hly_accesscard")

r = _detect_non_alter(sql)
check("non_alter count (CREATE TABLE 归 CREATE, CREATE INDEX 归 ALTER)", len(r), 1)
check("non_alter stmt_type", r[0]["stmt_type"], "CREATE")

r = _check_mixed_ddl(sql)
check("mixed_ddl ok (CREATE TABLE + CREATE INDEX 算混合, 应该拒绝)", r["ok"], False)
check("types 含 CREATE (CREATE TABLE)", "CREATE" in r["types"], True)
check("types 含 ALTER (CREATE INDEX 归 ALTER)", "ALTER" in r["types"], True)

r = _parse_all_statements(sql)
check("ghost stmts count (use + CREATE + ALTER)", len(r), 3)
check("ghost stmts[1] type=CREATE", r[1]["stmt_type"], "CREATE")
check("ghost stmts[2] type=ALTER (CREATE INDEX)", r[2]["stmt_type"], "ALTER")
check("ghost stmts[2] table", r[2]["table"], "accesscard_channel_task")

r = sync_extract_all_alters(sql)
check("sync extract count (CREATE INDEX 也算 ALTER)", len(r), 1)
check("sync extract[0] table", r[0]["table"], "accesscard_channel_task")

r = _parse_all_alters(sql)
check("all_alters count", len(r), 1)
check("all_alters[0] table", r[0]["table"], "accesscard_channel_task")

r = _detect_non_alter(sql)
check("non_alter count (CREATE TABLE)", len(r), 1)
check("non_alter stmt_type", r[0]["stmt_type"], "CREATE")

r = _check_mixed_ddl(sql)
check("mixed_ddl ok (CREATE TABLE + CREATE INDEX 算混合)", r["ok"], False)

r = _parse_all_statements(sql)
check("ghost stmts count", len(r), 3)
check("ghost stmts[1] type=CREATE", r[1]["stmt_type"], "CREATE")
check("ghost stmts[2] type=ALTER (CREATE INDEX)", r[2]["stmt_type"], "ALTER")
check("ghost stmts[2] table", r[2]["table"], "accesscard_channel_task")

print()
print("=== Case 9: 业务方 wf#4841 实战 (9/16) + CREATE INDEX ===")
sql = (
    "ALTER TABLE hly_accesscard.accesscard_licensefront_info ADD INDEX idx_owner_name (owner_name);\n"
    "CREATE INDEX idx_x ON hly_accesscard.accesscard_licensefront_info (vehicle_no);\n"
)
r = _parse_all_alters(sql)
check("all alters count", len(r), 2)

r = sync_extract_all_alters(sql)
check("sync extract count", len(r), 2)

print()
print("=== Case 10: CREATE INDEX 不带 USING ===")
sql = "CREATE INDEX idx_x ON hly_accesscard.accesscard_channel_task (req_url);"
r = _parse_first_alter(sql)
check("table", r["table"], "accesscard_channel_task")
check("db", r["db"], "hly_accesscard")
r = _detect_non_alter(sql)
check("non_alter count", len(r), 0)

print()
print("=== 验证完成 ===")