"""
DBA-bug-1 单元测试: _parse_first_alter 预处理 SQL 解析
@ 2026-09-11 @ mavis

8/26 漏测: 8 个单元测试 case 都是单条干净 ALTER, 没覆盖 use + 注释前缀场景.
9/11 实战踩坑: wf#4803 业务方 drop index 工单 SQL 真实形态是
  use hly_platform;
  -- 删除无用索引 xxx
  ALTER TABLE waybill_union_carrier drop index idx_way_bill_id
8/26 修法 re.match 从字符串开头匹配, 看到 u/- 直接 NO MATCH, table=None, 大表 alert 不显示.
9/11 修法: 逐行扫描, 跳过 use / -- 注释 / 空行, 找到第一个 ALTER 再 re.match.

跑法: 134 dev 容器内 /opt/archery/prod
  python manage.py shell < scripts/_dba_bug1_unit_test.py
"""
import sys
from sql.views import _parse_first_alter

CASES = [
    # 9/11 新增场景: 真实业务方 SQL 形态 (use + 注释 + ALTER, 多行)
    ("test_with_use_and_comment_drop_index_multiline",
     "use `hly_platform`;\n-- 删除无用索引 idx_show_flag\n-- 删除无用索引 idx_sync_flag\nALTER TABLE waybill_union_carrier drop index idx_way_bill_id",
     None, "waybill_union_carrier"),
    ("test_with_use_only",
     "use hly_platform;\nalter table waybill_union_carrier drop index idx_way_bill_id",
     None, "waybill_union_carrier"),
    ("test_with_comment_only",
     "-- 删除无用索引\nalter table waybill_union_carrier drop index idx_way_bill_id",
     None, "waybill_union_carrier"),
    ("test_with_use_schema_drop_index",
     "use hly_platform;\n-- 删除无用索引\nalter table hly_platform.waybill_union_carrier drop index idx_way_bill_id",
     "hly_platform", "waybill_union_carrier"),
    # 8/26 老场景: 单条干净 ALTER (回归)
    ("test_clean_alter_add_column",
     "alter table user add column age int",
     None, "user"),
    ("test_clean_alter_drop_index",
     "ALTER TABLE `user` DROP INDEX idx_user_name",
     None, "user"),
    ("test_with_schema_prefix",
     "alter table hly_platform.waybill_union_carrier add column x int",
     "hly_platform", "waybill_union_carrier"),
    ("test_with_use_and_newline_add_column",
     "use hly_platform;\n\nalter table waybill_union_carrier add column x int",
     None, "waybill_union_carrier"),
    # 边界 case
    ("test_invalid_sql_no_alter",
     "select * from user where id = 1",
     None, None),  # 应返回 None
    ("test_empty_sql",
     "",
     None, None),  # 应返回 None
    ("test_only_comments",
     "-- 注释1\n-- 注释2\n",
     None, None),  # 应返回 None
]

passed = 0
failed = 0
for name, sql, expected_db, expected_table in CASES:
    try:
        parsed = _parse_first_alter(sql)
        if expected_table is None:
            # 期望 None
            if parsed is None:
                print(f"[PASS] {name}: expected None, got None")
                passed += 1
            else:
                print(f"[FAIL] {name}: expected None, got {parsed!r}")
                failed += 1
        else:
            # 期望 (db, table)
            actual_db = parsed.get("db")
            actual_table = parsed.get("table")
            if actual_table == expected_table and actual_db == expected_db:
                print(f"[PASS] {name}: db={actual_db!r} table={actual_table!r}")
                passed += 1
            else:
                print(f"[FAIL] {name}: expected db={expected_db!r} table={expected_table!r}, got db={actual_db!r} table={actual_table!r}")
                failed += 1
    except Exception as e:
        print(f"[ERROR] {name}: {type(e).__name__}: {e}")
        failed += 1

print(f"\n=== Result: {passed} passed, {failed} failed, total {len(CASES)} ===")
sys.exit(0 if failed == 0 else 1)
