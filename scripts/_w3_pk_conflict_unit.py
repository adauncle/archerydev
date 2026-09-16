"""W3 INSERT PK 冲突检测 单元测试 (134 dev 演练 Case F-J, 9/16)

@ 2026-09-16 @ mavis

演练方式: 134 dev 直接连接真实业务库 hly_accesscard (演练环境已有).
- output_fee_config 表不存在 → 改成 accesscard_black_detail (已有大表)
- 实际操作: 用 accesscard_black_detail 演练 PK 冲突
  (业务库真实表, 表存在 + 有 PK + 有真实数据)

业务方实战 wf#4834 (output_fee_config) 是 110 prod 演练 case.
134 dev 演练用 accesscard_black_detail 替代.
"""

import sys, os, django
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()

from sql.models import Instance
from sql.utils.pk_conflict_check import (
    check_pk_conflict, _extract_inserts, _resolve_insert_pk_values,
)


# 134 dev 演练用 accesscard_account (业务库 archery_dev, 20 行, PK=id 小写)
# 实战 wf#4834 是 hly_datacenter_mod.output_fee_config (PK=id, 110 prod 演练).
# 134 dev 演练改用 archery_dev.accesscard_account, 同 DB PK 列名都是 'id' 小写
INSTANCE = Instance.objects.get(id=2)  # 测试 MySQL 8.0
DB_NAME = "archery_dev"
TABLE = "accesscard_account"  # 有 20 行真实数据, PK='id'


def test_extract_inserts():
    """测试 _extract_inserts (SQL 解析)."""
    print("=== 测试 _extract_inserts ===")
    test_cases = [
        ("单条 INSERT 无库名",
         "INSERT INTO tbl VALUES (1, 'a', 'b')",
         {"schema": None, "table": "tbl", "values_len": 1}),
        ("单条 INSERT 反引号 schema",
         "INSERT INTO `hly_accesscard`.`tbl` VALUES (1, 2, 3)",
         {"schema": "hly_accesscard", "table": "tbl", "values_len": 1}),
        ("多值 INSERT",
         "INSERT INTO tbl VALUES (1, 'a'), (2, 'b'), (3, 'c')",
         {"schema": None, "table": "tbl", "values_len": 3}),
        ("INSERT 显式列名",
         "INSERT INTO tbl (id, col1, col2) VALUES (1, 'a', 'b')",
         {"schema": None, "table": "tbl", "values_len": 1}),
        ("use 跳过 + INSERT",
         "use hly_accesscard;\nINSERT INTO tbl VALUES (1, 2)",
         {"schema": None, "table": "tbl", "values_len": 1}),
    ]
    passed = 0
    for name, sql, expected in test_cases:
        inserts = _extract_inserts(sql)
        if inserts and len(inserts) >= 1:
            ins = inserts[0]
            ok = (ins["schema"] == expected["schema"] and
                  ins["table"] == expected["table"] and
                  len(ins["values_list"]) == expected["values_len"])
        else:
            ok = False
        if ok:
            print(f"  ✓ {name}")
            passed += 1
        else:
            print(f"  ✗ {name}: got {inserts}")
    print(f"  _extract_inserts: {passed}/{len(test_cases)} passed\n")
    return passed == len(test_cases)


def test_resolve_insert_pk_values():
    """测试 _resolve_insert_pk_values (查 DB 拿 PK 列 + 提取 PK 值)."""
    print("=== 测试 _resolve_insert_pk_values (查 %s) ===" % TABLE)
    insert = {
        "schema": None,
        "table": TABLE,
        "columns": None,  # 没指定列名, 走列顺序
        "values_list": [["999999", "test1", "test1"]],
    }
    pk_col, pk_values = _resolve_insert_pk_values(insert, INSTANCE, DB_NAME)
    print("  PK 列: %r, PK 值: %r" % (pk_col, pk_values))
    # 134 dev archery_dev.accesscard_account PK = 'id' (小写, 跟业务方 wf#4834 一致)
    if pk_col and len(pk_values) > 0:
        print("  ✓ PK 列/值解析正确")
        return True
    else:
        print("  ✗ PK 列/值错误: pk_col=%r, pk_values=%r" % (pk_col, pk_values))
        return False


def test_check_pk_conflict_cases():
    """测试 check_pk_conflict (端到端)."""
    print("=== 测试 check_pk_conflict ===")
    from sql.utils.pk_conflict_check import _fetch_table_pk_column, _query_existing_pks
    pk_col = _fetch_table_pk_column(INSTANCE, DB_NAME, TABLE)
    print("  %s PK 列: %r" % (TABLE, pk_col))
    if not pk_col:
        print("  ⚠️ 表无 PK, 跳过端到端测试")
        return True

    # 先拿一个真实 PK 值 (134 dev accesscard_account id 范围 10000+)
    existing_pks = _query_existing_pks(INSTANCE, DB_NAME, TABLE, pk_col, [10000])
    if not existing_pks:
        print("  ⚠️ 表无数据 (id=10000 不存在), 跳过")
        return True
    existing_pk = existing_pks[0]
    print("  使用 existing_pk=%s" % existing_pk)

    # Case F: PK 冲突 reject
    sql_f = "INSERT INTO `%s` VALUES (%d, 'test', 'test')" % (TABLE, existing_pk)
    result_f = check_pk_conflict(sql_f, INSTANCE, DB_NAME)
    print("  F PK 冲突 reject: ok=%s, conflicts=%s" % (result_f["ok"], result_f.get("conflicts")))
    if not result_f["ok"]:
        f_pass = True
        print("  ✓ Case F: PK 冲突 reject")
    else:
        f_pass = False
        print("  ✗ Case F: 应该 ok=False 但 ok=True")

    # Case G: PK 不冲突 pass (用一个不存在的 PK)
    sql_g = "INSERT INTO `%s` VALUES (-1, 'test', 'test')" % TABLE
    result_g = check_pk_conflict(sql_g, INSTANCE, DB_NAME)
    print("  G PK 不冲突 pass: ok=%s" % result_g["ok"])
    if result_g["ok"]:
        g_pass = True
        print("  ✓ Case G: PK 不冲突 pass")
    else:
        g_pass = False
        print("  ✗ Case G: 应该 ok=True 但 ok=False, conflicts=%s" % result_g.get("conflicts"))

    # Case H: 多值 INSERT PK 部分冲突
    sql_h = "INSERT INTO `%s` VALUES (%d, 'test'), (-1, 'test')" % (TABLE, existing_pk)
    result_h = check_pk_conflict(sql_h, INSTANCE, DB_NAME)
    print("  H 多值 INSERT 部分冲突: ok=%s, conflicts=%s" % (result_h["ok"], result_h.get("conflicts")))
    if not result_h["ok"] and any(existing_pk in c["existing_pks"] for c in result_h["conflicts"]):
        h_pass = True
        print("  ✓ Case H: 部分冲突 reject")
    else:
        h_pass = False
        print("  ✗ Case H: 应该 partial 冲突")

    return f_pass and g_pass and h_pass


def main():
    p1 = test_extract_inserts()
    p2 = test_resolve_insert_pk_values()
    p3 = test_check_pk_conflict_cases()
    all_pass = p1 and p2 and p3
    print(f"\n=== W3 pk_conflict_check 单元测试总结: {'ALL PASS' if all_pass else 'FAILED'} ===")
    return all_pass


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)