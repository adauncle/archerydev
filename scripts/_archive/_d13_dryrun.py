"""D13 dryrun - 测试 column_diff_full 多表 DDL 解析 (不连 DB, 用 mock Instance)"""
import sys
import os
import json
from unittest.mock import MagicMock

sys.path.insert(0, "G:/MiniMax工作空间/archery_dev")

# Configure Django settings (避免 _build_big_table_alert 报 settings not configured)
import django
from django.conf import settings as dj_settings
if not dj_settings.configured:
    dj_settings.configure(
        DEBUG=False,
        DATABASES={},
        INSTALLED_APPS=[],
        CUSTOM_BIG_TABLE_ROW_THRESHOLD=100000,
        CUSTOM_BIG_TABLE_SIZE_THRESHOLD_MB=100,
    )
    django.setup()

# 直接用 ast 读 column_diff.py, 模拟 _fetch_current_columns / _fetch_table_size 返回值
# 实战: 汪银和 7 张表 DDL, 134 dev 演练用 5 张表演练表

# 准备 5 张表演练表的列定义 (跟 accesscard_black_detail 类似的字段)
TEST_TABLES = {
    "accesscard_test_diff1": {
        "id": {"name": "id", "type": "int(11)", "charset": "", "collation": "", "nullable": False, "default": None, "comment": "ID", "extra": "auto_increment", "column_key": "PRI"},
        "name": {"name": "name", "type": "varchar(100)", "charset": "utf8mb4", "collation": "utf8mb4_general_ci", "nullable": True, "default": None, "comment": "名称", "extra": "", "column_key": ""},
    },
    "accesscard_test_diff2": {
        "id": {"name": "id", "type": "bigint(20)", "charset": "", "collation": "", "nullable": False, "default": None, "comment": "ID", "extra": "auto_increment", "column_key": "PRI"},
    },
    "accesscard_test_diff3": {
        "id": {"name": "id", "type": "int(11)", "charset": "", "collation": "", "nullable": False, "default": None, "comment": "ID", "extra": "auto_increment", "column_key": "PRI"},
    },
    "accesscard_test_diff4": {
        "id": {"name": "id", "type": "int(11)", "charset": "", "collation": "", "nullable": False, "default": None, "comment": "ID", "extra": "auto_increment", "column_key": "PRI"},
    },
    "accesscard_test_diff5": {
        "id": {"name": "id", "type": "int(11)", "charset": "", "collation": "", "nullable": False, "default": None, "comment": "ID", "extra": "auto_increment", "column_key": "PRI"},
    },
}

# 实战 SQL: 5 张表 ALTER
TEST_SQL = """ALTER TABLE accesscard_test_diff1
    MODIFY name varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'test' COMMENT '新名称';
ALTER TABLE accesscard_test_diff1
    ADD new_col varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '新列';
ALTER TABLE accesscard_test_diff2
    MODIFY id bigint(20) NOT NULL AUTO_INCREMENT COMMENT 'BIGINT id';
ALTER TABLE accesscard_test_diff3
    ADD col3 varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'x' COMMENT 'col3';
ALTER TABLE accesscard_test_diff4
    DROP old_col;
ALTER TABLE accesscard_test_diff5
    MODIFY id int(11) NOT NULL DEFAULT 0 COMMENT 'ID';"""

# 用真实 column_diff.py 但 mock _fetch_* 函数
import importlib.util
spec = importlib.util.spec_from_file_location("column_diff", r"G:/MiniMax工作空间/archery_dev/sql/extensions/ddl_gh_ost/services/column_diff.py")
cd_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd_module)

# Mock _fetch_current_columns
orig_fetch_current = cd_module._fetch_current_columns
def mock_fetch_current(instance, db_name, table_name):
    return TEST_TABLES.get(table_name, {})
cd_module._fetch_current_columns = mock_fetch_current

# Mock _fetch_table_size
orig_fetch_size = cd_module._fetch_table_size
def mock_fetch_size(instance, db_name, table_name):
    return {"rows": 100, "size_mb": 10.0, "table_name": table_name}
cd_module._fetch_table_size = mock_fetch_size

# Mock instance
mock_instance = MagicMock()

# 调 column_diff_full
result = cd_module.column_diff_full(mock_instance, "hly_accesscard", TEST_SQL)

print("=" * 60)
print(f"ok: {result.get('ok')}")
print(f"tables: {len(result.get('tables', []))} 张")
print(f"high_risk_count: {result.get('high_risk_count')}")
print(f"mid_risk_count: {result.get('mid_risk_count')}")
print(f"low_risk_count: {result.get('low_risk_count')}")
print(f"summary: {result.get('summary')}")
print()
print("=" * 60)
print("顶层兼容字段 (老前端用):")
print(f"  table_name: {result.get('table_name')}")
print(f"  table_exists: {result.get('table_exists')}")
print(f"  columns: {len(result.get('columns', []))} 个")
print()
print("=" * 60)
print("tables 字段 (新前端用):")
for t in result.get("tables", []):
    print(f"\n  [{t.get('table_name')}] exists={t.get('table_exists')} ok={t.get('ok')}")
    print(f"    summary: {t.get('summary')}")
    print(f"    high={t.get('high_risk_count')} mid={t.get('mid_risk_count')} low={t.get('low_risk_count')}")
    print(f"    columns: {len(t.get('columns', []))} 个")
    for c in t.get("columns", []):
        print(f"      - {c.get('operation')} {c.get('name')}: {len(c.get('diffs', []))} 个 diff")
        for d in c.get("diffs", []):
            print(f"        · {d.get('field')}: {d.get('risk')} - {d.get('reason')[:60]}")
        if c.get("suggested_sql"):
            print(f"        [SUGGESTED] {c['suggested_sql'][:80]}")
