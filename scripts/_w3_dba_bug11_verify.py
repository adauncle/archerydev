"""
DBA-bug-11 演练: gh-ost precheck 400 错 (## 注释未识别)
- 静态: views.py:147 startswith("--") 不识别 "##" 注释
- mock 演练: 模拟 wf#4871 实际 SQL + _parse_all_statements 行为
- 修复验证: startswith("--") + startswith("##") 都跳过
"""
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.getcwd())
VIEWS = REPO_ROOT / "sql" / "extensions" / "ddl_gh_ost" / "views.py"

# wf#4871 实际 SQL (从 110 prod MySQL 拉出来, 3699 chars)
WF4871_SQL = """## 钉钉审核表关联运单表加字段
alter table dingding_check_waybill
    add hdj_type int default 1 null comment '回单结类型（1：回单结 2：起运结）';

## 下游付款运单关联表
alter table downstream_waybill
    add qyj_amount          decimal(18, 2)          default 0.00 null comment '起运结金额（抵扣起运结）',
    add qyj_discount_amount decimal(18, 2) unsigned default 0.00 null comment '抵扣起运结差价';

## 回单结开通
alter table hdj_open
    add pre_discount_rate      decimal(15, 10) null comment '起运结费率',
    add pre_discount_rate_unit int             null comment '起运结费率单位（ 1:%/日 2:%）';
"""

# 当前 _parse_all_statements 实现 (从 views.py:120-191 抄, 不动原始代码)
_FIRST_ALTER_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+`?(?P<schema>[^`\s.()]+(?:\.`?[^`\s.()]+`?)?`?\.)?`?"
    r"(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,
)
_FIRST_CREATE_INDEX_RE = re.compile(
    r"^\s*CREATE\s+(?:UNIQUE\s+|FULLTEXT\s+|SPATIAL\s+)?INDEX\s+`?[^`\s]+`?\s+"
    r"(?:USING\s+\w+\s+)?ON\s+"
    r"`?(?P<schema>[^`\s.()]+(?:\.`?[^`\s.()]+`?)?`?\.)?`?"
    r"(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,
)


def _parse_all_statements_OLD(sql_content):  # 不处理 ## 注释
    """原版 (buggy) - 只跳过 -- 注释"""
    if not sql_content:
        return []
    statements = []
    raw_stmts = [s.strip() for s in sql_content.split(";") if s.strip()]
    for raw in raw_stmts:
        lines = []
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("--") or not stripped:  # ← 原版不处理 ##
                continue
            lines.append(line)
        cleaned = "\n".join(lines).strip()
        if not cleaned:
            continue
        m = _FIRST_ALTER_RE.match(cleaned)
        if m:
            statements.append({
                "stmt_type": "ALTER",
                "db": (m.group("schema") or "").rstrip(".").strip("`") or None,
                "table": (m.group("table") or "").strip("`"),
                "full": cleaned,
            })
            continue
        m = _FIRST_CREATE_INDEX_RE.match(cleaned)
        if m:
            statements.append({
                "stmt_type": "ALTER",
                "db": (m.group("schema") or "").rstrip(".").strip("`") or None,
                "table": (m.group("table") or "").strip("`"),
                "full": cleaned,
            })
            continue
        first_word = cleaned.split()[0].upper().rstrip(";") if cleaned.split() else ""
        statements.append({"stmt_type": first_word if first_word in ("CREATE", "INSERT", "UPDATE", "DELETE", "USE") else "OTHER",
                          "db": None, "table": None, "full": cleaned})
    return statements


def _parse_all_statements_NEW(sql_content):  # 处理 ## 注释
    """新版 (fix) - 跳过 -- 和 ## 注释"""
    if not sql_content:
        return []
    statements = []
    raw_stmts = [s.strip() for s in sql_content.split(";") if s.strip()]
    for raw in raw_stmts:
        lines = []
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("--") or stripped.startswith("##") or not stripped:  # ← fix
                continue
            lines.append(line)
        cleaned = "\n".join(lines).strip()
        if not cleaned:
            continue
        m = _FIRST_ALTER_RE.match(cleaned)
        if m:
            statements.append({
                "stmt_type": "ALTER",
                "db": (m.group("schema") or "").rstrip(".").strip("`") or None,
                "table": (m.group("table") or "").strip("`"),
                "full": cleaned,
            })
            continue
        m = _FIRST_CREATE_INDEX_RE.match(cleaned)
        if m:
            statements.append({
                "stmt_type": "ALTER",
                "db": (m.group("schema") or "").rstrip(".").strip("`") or None,
                "table": (m.group("table") or "").strip("`"),
                "full": cleaned,
            })
            continue
        first_word = cleaned.split()[0].upper().rstrip(";") if cleaned.split() else ""
        statements.append({"stmt_type": first_word if first_word in ("CREATE", "INSERT", "UPDATE", "DELETE", "USE") else "OTHER",
                          "db": None, "table": None, "full": cleaned})
    return statements


# ==================== 静态用例 ====================
def check_static():
    print("=" * 70)
    print("静态用例: gh-ost precheck ## 注释支持 (DBA-bug-11)")
    print("=" * 70)
    src = VIEWS.read_text(encoding="utf-8")
    cases = []

    # Case 1: views.py:147 当前只识别 -- 不识别 ##
    has_old = 'if stripped.startswith("--") or not stripped:' in src
    cases.append(("Case 1: views.py:147 当前只识别 -- (不识别 ##)", has_old))

    # Case 2: 修法 - 加 startswith("##")
    has_new = 'startswith("##")' in src
    cases.append(("Case 2: views.py 修法加 startswith('##')", has_new))

    # Case 3: precheck 端点 status=400 触发条件
    has_400 = '"summary": "未找到 ALTER TABLE 语句"' in src and "status=400" in src
    cases.append(("Case 3: precheck status=400 触发条件 (parsed is None)", has_400))

    # Case 4: _FIRST_ALTER_RE 必须以 ALTER 开头
    has_re = 'r"^\\s*ALTER\\s+TABLE' in src
    cases.append(("Case 4: _FIRST_ALTER_RE ^\\s*ALTER (必须 ALTER 开头)", has_re))

    # Case 5: _parse_first_alter 兼容老 (9/16 注释说明)
    has_deprecated = "DBA-bug-9 deprecated" in src
    cases.append(("Case 5: _parse_first_alter 9/16 标记 deprecated 兼容老", has_deprecated))

    # Case 6: CREATE INDEX 单独 regex (9/17 DBA-bug-10)
    has_create_index = "_FIRST_CREATE_INDEX_RE" in src and "CREATE INDEX" in src
    cases.append(("Case 6: CREATE INDEX 单独 regex (9/17 DBA-bug-10 兼容)", has_create_index))

    passed = 0
    for name, ok in cases:
        marker = "[PASS]" if ok else "[FAIL]"
        print(f"  {marker} {name}")
        if ok:
            passed += 1
    print(f"\nPASS {passed}/{len(cases)}")
    return passed == len(cases)


# ==================== Mock 演练 ====================
def check_mock():
    print()
    print("=" * 70)
    print("Mock 演练: 模拟 wf#4871 实际 SQL")
    print("=" * 70)

    # 1. 旧版解析 (buggy) - 应该解析不到 ALTER
    print("\n  旧版 (## 注释不跳过, 期望 0 个 ALTER):")
    old_result = _parse_all_statements_OLD(WF4871_SQL)
    old_alters = [s for s in old_result if s["stmt_type"] == "ALTER"]
    print(f"    parsed: {len(old_result)} 个 statement")
    for s in old_result:
        print(f"      {s['stmt_type']:8s} table={s['table']!r}")
    assert len(old_alters) == 0, f"❌ 旧版居然解析出 ALTER: {old_alters}"
    print(f"    [PASS] 旧版解析不到 ALTER → precheck 返 400 (复现 bug)")

    # 2. 新版解析 (fix) - 应该解析出 3 个 ALTER
    print("\n  新版 (## 注释跳过, 期望 3 个 ALTER):")
    new_result = _parse_all_statements_NEW(WF4871_SQL)
    new_alters = [s for s in new_result if s["stmt_type"] == "ALTER"]
    print(f"    parsed: {len(new_result)} 个 statement, {len(new_alters)} 个 ALTER")
    for s in new_alters:
        print(f"      ALTER table={s['table']!r}")
    assert len(new_alters) == 3, f"❌ 新版应该 3 个 ALTER, 实际 {len(new_alters)}"
    assert new_alters[0]["table"] == "dingding_check_waybill", f"❌ 第 1 条表名错: {new_alters[0]}"
    assert new_alters[1]["table"] == "downstream_waybill", f"❌ 第 2 条表名错: {new_alters[1]}"
    assert new_alters[2]["table"] == "hdj_open", f"❌ 第 3 条表名错: {new_alters[2]}"
    print(f"    [PASS] 新版正确解析 3 个 ALTER (dingding_check_waybill / downstream_waybill / hdj_open)")

    # 3. 边界: 只有 -- 注释 (MySQL 风格, 旧版也支持)
    print("\n  边界 1: 纯 -- 注释 (MySQL 风格, 旧版也支持):")
    mysql_style = """-- this is a comment
ALTER TABLE t1 ADD col INT;
-- another comment
ALTER TABLE t2 ADD col2 INT;"""
    new_result = _parse_all_statements_NEW(mysql_style)
    assert len(new_result) == 2, f"❌ 边界 1 失败: {new_result}"
    print(f"    [PASS] 纯 -- 注释 {len(new_result)} 个 ALTER (兼容)")

    # 4. 边界: 混合 ## + -- 注释
    print("\n  边界 2: 混合 ## + -- 注释:")
    mixed = """## python style comment
-- mysql style comment
ALTER TABLE t1 ADD col INT;"""
    new_result = _parse_all_statements_NEW(mixed)
    assert len(new_result) == 1, f"❌ 边界 2 失败: {new_result}"
    print(f"    [PASS] 混合 ## + -- 注释 {len(new_result)} 个 ALTER (兼容)")

    # 5. 边界: 嵌套 ## (comment 含 ##)
    print("\n  边界 3: ## 注释但没 ALTER (空 cleaned, 应该 skip):")
    only_comment = """## this is a comment
## another comment"""
    new_result = _parse_all_statements_NEW(only_comment)
    assert len(new_result) == 0, f"❌ 边界 3 失败: {new_result}"
    print(f"    [PASS] 纯注释 (无 ALTER) → 0 个 statement (不抛错)")

    # 6. 边界: ALTER 后面有 ## 注释
    print("\n  边界 4: ALTER 后面跟 ## 注释 (中间行):")
    with_mid_comment = """ALTER TABLE t1
    ADD col INT;
## mid comment
ALTER TABLE t2
    ADD col2 INT;"""
    new_result = _parse_all_statements_NEW(with_mid_comment)
    assert len(new_result) == 2, f"❌ 边界 4 失败: {new_result}"
    print(f"    [PASS] ALTER 之间 ## 注释 {len(new_result)} 个 ALTER (兼容)")

    print()
    print("[PASS] Mock 演练 6/6 通过")
    return True


# ==================== 跨文件 ## 注释审计 ====================
def check_other_files():
    """其他 5 文件也有 startswith('--') 不处理 ## 的问题"""
    print()
    print("=" * 70)
    print("跨文件 ## 注释审计 (DBA-bug-11 已知未修, 待清理)")
    print("=" * 70)
    files_with_bug = [
        ("sql/extensions/ddl_gh_ost/views.py", 147),  # wf#4871 紧急
        ("sql/extensions/ddl_sync/services/sync_trigger.py", 110),  # 镜像工单解析
        ("sql/views.py", 288),  # 业务方提交流水
        ("sql/services/ddl_rollback.py", 167),  # 回滚解析
        ("sql/extensions/dingtalk_oa/services/sql_type_detect.py", 79),  # 钉钉 OA 检测
        ("sql/extensions/dingtalk_oa/drivers/dingtalk.py", 281),  # 钉钉 OA driver
    ]

    for fp, line in files_with_bug:
        full_path = REPO_ROOT / fp
        if not full_path.exists():
            print(f"  [SKIP] {fp}: not found")
            continue
        src = full_path.read_text(encoding="utf-8")
        if 'startswith("--")' in src and 'startswith("##")' not in src:
            print(f"  [BUG] {fp}:{line} startswith('--') 但不处理 ##")
        elif 'startswith("##")' in src:
            print(f"  [OK]  {fp}: 已支持 ## 注释")
        else:
            print(f"  [N/A] {fp}: 未发现 startswith('--')")
    return True


if __name__ == "__main__":
    print(f"Repo: {REPO_ROOT}")
    print(f"views.py: {VIEWS}")
    print()
    ok1 = check_static()
    ok2 = check_mock()
    ok3 = check_other_files()

    if ok1 and ok2:
        print("\n" + "=" * 70)
        print("[ALL PASS] 6 静态 + 6 mock 演练")
        print("下一步: 改 1 文件 (gh-ost views.py:147) + 134 dev + 110 prod 部署")
        print("其他 5 文件已知有同样问题, 待下一波清理 (DBA-bug-11 全项目扫尾)")
        print("=" * 70)
        sys.exit(0)
    else:
        sys.exit(1)