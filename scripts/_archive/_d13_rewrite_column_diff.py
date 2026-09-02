"""D13 - 重写 column_diff_full 支持多表 DDL
实战 9/2 17:35 业务 RD 汪银和 7 张表 ALTER 工单字段 diff 只显示第 1 张表
"""
import re
from pathlib import Path

PATH = Path(r"G:/MiniMax工作空间/archery_dev/sql/extensions/ddl_gh_ost/services/column_diff.py")
src = PATH.read_text(encoding="utf-8")

# 找 column_diff_full 函数开始 + 结束位置 (到文件末尾, 之前已确认 858 行, 现在 8/24 后可能有微调)
start_marker = "# 4. 整合入口: 给定 instance + db + sql, 返回完整 diff 结果\n"
end_marker = '        "big_table_alert": big_table_alert,\n    }'

start_idx = src.find(start_marker)
end_idx = src.find(end_marker)
if start_idx < 0 or end_idx < 0:
    raise SystemExit(f"找不到 marker: start={start_idx} end={end_idx}")

end_idx += len(end_marker)
print(f"原 column_diff_full 段: {start_idx} ~ {end_idx} ({end_idx - start_idx} 字符)")

# 新的 column_diff_full (重写 + 加 _diff_single_table helper)
new_block = '''# 4. 整合入口: 给定 instance + db + sql, 返回完整 diff 结果
# ============================================================
# CUSTOM-MODIFIED: 9/2 D13 多表 DDL 重构 @ 2026-09-02 @ mavis
# 关联: docs/changelogs/2026-09-02_ddl-sync-w2-d13-multi-table-column-diff.md
# 业务背景: 8/24 v0.3.x 设计只考虑单表 ALTER, 9/2 17:35 业务 RD 汪银和实战
#          7 张表 ALTER 工单, 字段 diff 只显示第一张表 (project_config),
#          其他 6 张表完全忽略 (DBA 看不到风险) → bug fix.
# 根因: 老代码 `for stmt: ... break` 只取第一个 ALTER TABLE 就 break.
# 修法: 拆 SQL 收集所有 ALTER TABLE, 每张表独立 diff 一次, 顶层汇总,
#       顶层字段兼容老单表前端 (data.columns / data.table_name).
def _diff_single_table(instance, db_name: str, alter_sql: str, force_table_name: str = None) -> dict:
    """CUSTOM: 单条 ALTER TABLE 完整 diff 流程 (内部 helper).

    Args:
        instance: Instance model
        db_name: 数据库名
        alter_sql: 单条 ALTER TABLE SQL (不含 use 前缀, 不含 ; 末尾)
        force_table_name: 可选, 显式指定表名 (column_diff_full 兼容老调用)

    Returns:
        {
            "ok": bool,
            "table_name": str,
            "table_exists": bool,
            "columns": [{...}],
            "high_risk_count": int,
            "mid_risk_count": int,
            "low_risk_count": int,
            "summary": str,
            "big_table_alert": dict or None,
        }
    """
    changes = _parse_alter_column_changes(alter_sql)
    if not changes:
        return {
            "ok": False,
            "error": f"ALTER TABLE 不包含 MODIFY/ADD/DROP COLUMN 字段变更",
            "hint": "只支持 ALTER TABLE ... MODIFY/ADD/DROP COLUMN",
        }

    # 2. 拿表名 (从 SQL 解析 或 显式)
    table_name = force_table_name
    if not table_name:
        m = re.match(
            r"^\\s*ALTER\\s+TABLE\\s+"
            r"(?:(?P<schema>[^`\\s.()]+)\\.)?`?(?P<table>[^`\\s(]+)`?",
            alter_sql.strip(),
            re.IGNORECASE,
        )
        if not m:
            return {"ok": False, "error": "解析不到表名"}
        table_name = m.group("table").strip("`")

    # 3. 查当前列定义
    current_cols = _fetch_current_columns(instance, db_name, table_name)
    if not current_cols:
        return {
            "ok": False,
            "error": f"表 {db_name}.{table_name} 不存在或查不到列定义",
            "table_name": table_name,
            "table_exists": False,
        }

    # 4. 逐变更 diff
    columns_diff = []
    high_risk = mid_risk = low_risk = 0

    for change in changes:
        op = change["operation"]
        name_lc = change["name"].lower()
        current = current_cols.get(name_lc)

        if op == "drop":
            # DROP 不做字段 diff, 但提示
            columns_diff.append({
                "name": change["name"],
                "operation": "DROP",
                "current": current,
                "new": None,
                "diffs": [{
                    "field": "_op",
                    "old": "exists",
                    "new": "dropped",
                    "risk": "mid",
                    "reason": f"删除列 {change['name']}, 数据将丢失, 建议先备份",
                }],
            })
            mid_risk += 1
            continue

        if op == "add":
            # ADD 检查列名是否已存在
            if current:
                columns_diff.append({
                    "name": change["name"],
                    "operation": "ADD",
                    "current": current,
                    "new": change["definition"],
                    "diffs": [{
                        "field": "_op",
                        "old": "exists",
                        "new": "add duplicate",
                        "risk": "high",
                        "reason": f"列名 {change['name']} 已存在, ADD COLUMN 会失败",
                    }],
                })
                high_risk += 1
            else:
                # 新列, 没 diff
                columns_diff.append({
                    "name": change["name"],
                    "operation": "ADD",
                    "current": None,
                    "new": change["definition"],
                    "diffs": [],
                })
            continue

        # modify: 逐字段 diff
        if not current:
            columns_diff.append({
                "name": change["name"],
                "operation": "MODIFY",
                "current": None,
                "new": change["definition"],
                "diffs": [{
                    "field": "_op",
                    "old": "missing",
                    "new": "modify",
                    "risk": "high",
                    "reason": f"列名 {change['name']} 不存在, MODIFY 会失败",
                }],
            })
            high_risk += 1
            continue

        diffs = []
        new_def = change["definition"]

        # 字段对比
        if (new_def.get("type") or "").upper() != (current.get("type") or "").upper():
            risk, reason = _assess_type_risk(current.get("type", ""), new_def.get("type", ""))
            if risk != "none":
                diffs.append({
                    "field": "type",
                    "old": current.get("type", ""),
                    "new": new_def.get("type", ""),
                    "risk": risk,
                    "reason": reason,
                })
                if risk == "high":
                    high_risk += 1
                elif risk == "mid":
                    mid_risk += 1
                else:
                    low_risk += 1

        # Charset (只对字符类型有意义)
        if current.get("charset") or new_def.get("charset"):
            old_charset = current.get("charset") or "(未指定)"
            new_charset = new_def.get("charset") or "(table default)"
            if old_charset != new_charset:
                risk, reason = _assess_charset_risk(old_charset, new_charset)
                if risk != "none":
                    diffs.append({
                        "field": "charset",
                        "old": old_charset,
                        "new": new_charset,
                        "risk": risk,
                        "reason": reason,
                    })
                    if risk == "high":
                        high_risk += 1
                    elif risk == "mid":
                        mid_risk += 1
                    else:
                        low_risk += 1

        # Collation
        if current.get("collation") or new_def.get("collation"):
            old_coll = current.get("collation") or "(未指定)"
            new_coll = new_def.get("collation") or "(table default)"
            if old_coll != new_coll:
                risk, reason = _assess_collation_risk(old_coll, new_coll)
                if risk != "none":
                    diffs.append({
                        "field": "collation",
                        "old": old_coll,
                        "new": new_coll,
                        "risk": risk,
                        "reason": reason,
                    })
                    if risk == "high":
                        high_risk += 1
                    elif risk == "mid":
                        mid_risk += 1
                    else:
                        low_risk += 1

        # Nullable
        if current.get("nullable") != new_def.get("nullable"):
            has_default = new_def.get("default") is not None
            risk, reason = _assess_nullable_with_default_risk(
                current.get("nullable", True),
                new_def.get("nullable", True),
                has_default,
            )
            if risk != "none":
                diffs.append({
                    "field": "nullable",
                    "old": "NULL" if current.get("nullable") else "NOT NULL",
                    "new": "NULL" if new_def.get("nullable") else "NOT NULL",
                    "risk": risk,
                    "reason": reason,
                })
                if risk == "high":
                    high_risk += 1
                elif risk == "mid":
                    mid_risk += 1
                else:
                    low_risk += 1

        # Default
        if str(current.get("default") or "") != str(new_def.get("default") or ""):
            risk, reason = _assess_default_risk(current.get("default"), new_def.get("default"))
            if risk != "none":
                diffs.append({
                    "field": "default",
                    "old": current.get("default") if current.get("default") is not None else "(无)",
                    "new": new_def.get("default") if new_def.get("default") is not None else "(无)",
                    "risk": risk,
                    "reason": reason,
                })
                if risk == "high":
                    high_risk += 1
                elif risk == "mid":
                    mid_risk += 1
                else:
                    low_risk += 1

        # Comment
        if (current.get("comment") or "") != (new_def.get("comment") or ""):
            risk, reason = _assess_column_risk("comment", current.get("comment", ""), new_def.get("comment", ""))
            if risk != "none":
                diffs.append({
                    "field": "comment",
                    "old": current.get("comment") or "(空)",
                    "new": new_def.get("comment") or "(空)",
                    "risk": risk,
                    "reason": reason,
                })
                if risk == "high":
                    high_risk += 1
                elif risk == "mid":
                    mid_risk += 1
                else:
                    low_risk += 1

        # Extra (AUTO_INCREMENT)
        old_extra = current.get("extra", "")
        new_extra = new_def.get("extra", "")
        if old_extra != new_extra and (old_extra or new_extra):
            risk, reason = _assess_extra_risk(old_extra, new_extra)
            if risk != "none":
                diffs.append({
                    "field": "extra",
                    "old": old_extra or "(无)",
                    "new": new_extra or "(无)",
                    "risk": risk,
                    "reason": reason,
                })
                if risk == "high":
                    high_risk += 1
                elif risk == "mid":
                    mid_risk += 1
                else:
                    low_risk += 1

        # 生成补全 SQL (CUSTOM: 2026-08-12 mavis) — 修复建议要可复制粘贴
        # 思路: 用 user 提供的 type/nullable/default/comment, 但强制补全原 charset/collation
        suggested_sql = None
        if any(d.get("risk") == "high" for d in diffs):
            fixed_type = new_def.get("type") or current.get("type", "")
            fixed_charset = current.get("charset", "")
            fixed_collation = current.get("collation", "")
            new_nullable = new_def.get("nullable", True)
            new_default = new_def.get("default")
            new_comment = new_def.get("comment", "")

            parts = [f"ALTER TABLE {table_name} MODIFY COLUMN {change['name']} {fixed_type}"]
            if fixed_charset:
                parts.append(f"CHARACTER SET {fixed_charset}")
            if fixed_collation:
                parts.append(f"COLLATE {fixed_collation}")
            if not new_nullable:
                parts.append("NOT NULL")
            if new_default is not None:
                if isinstance(new_default, str):
                    parts.append(f"DEFAULT '\\''{new_default}'\\''")
                else:
                    parts.append(f"DEFAULT {new_default}")
            elif not new_nullable:
                # NOT NULL 无 DEFAULT 是个 bug, 建议加 0
                parts.append("DEFAULT 0")
            if new_comment:
                parts.append(f"COMMENT '\\''{new_comment}'\\''")
            suggested_sql = " ".join(parts)

        columns_diff.append({
            "name": change["name"],
            "operation": "MODIFY",
            "current": current,
            "new": new_def,
            "diffs": diffs,
            "suggested_sql": suggested_sql,
        })

    # 5. 总结 (单表)
    if high_risk > 0:
        summary = f"检测到 {high_risk} 个高风险变更, 强烈建议补全 SQL"
    elif mid_risk > 0:
        summary = f"检测到 {mid_risk} 个中风险变更, 注意已有数据"
    elif any(c.get("diffs") for c in columns_diff):
        summary = "检测到低风险变更, 兼容"
    else:
        summary = "所有变更兼容, 无风险"

    # 6. 大表 DDL 防呆 (CUSTOM: 2026-08-13 mavis)
    # 业务: SQL 提交页开发点"SQL检测"时就该看到大表 DDL 警告, 不需要等审批通过后 DBA 执行阶段才看到。
    # 思路: 字段 diff 已经查了 information_schema.columns, 顺手查一下 information_schema.tables 拿行数+大小,
    #      跟 CUSTOM_BIG_TABLE_* 阈值比, 触发大表 alert (跟详情页 big_table_alert 同一逻辑)。
    size_info = _fetch_table_size(instance, db_name, table_name)
    big_table_alert = _build_big_table_alert(size_info)

    return {
        "ok": True,
        "table_name": table_name,
        "table_exists": True,
        "columns": columns_diff,
        "high_risk_count": high_risk,
        "mid_risk_count": mid_risk,
        "low_risk_count": low_risk,
        "summary": summary,
        "big_table_alert": big_table_alert,
    }


def column_diff_full(instance, db_name: str, sql_content: str, table_name: str = None) -> dict:
    """字段 diff 完整流程 (支持多表 DDL, 9/2 D13 重构).

    业务背景: 8/24 v0.3.x 设计只考虑单表 ALTER TABLE, 9/2 17:35 业务 RD 汪银和实战 7 张表
              ALTER 工单, 字段 diff 只显示第一张表 (project_config), 其他 6 张表完全忽略
              (DBA 看不到风险) → bug fix.
    根因 (D13): 老代码 `for stmt: ... break` 只取第一个 ALTER TABLE 就 break.
    修法: 拆 SQL 收集所有 ALTER TABLE, 每张表独立 diff 一次, 顶层汇总, 顶层字段兼容老单表前端.

    Args:
        instance: Instance model
        db_name: 数据库名
        sql_content: 用户 SQL (可能含 use + 多条 ALTER TABLE)
        table_name: 可选, 显式指定表名 (兼容老调用, 单表时只取该表)

    Returns:
        {
            "ok": bool,
            "tables": [{  # 9/2 D13 新增, 多表 DDL 实战
                "table_name": str,
                "table_exists": bool,
                "columns": [{...}],
                "high_risk_count": int,
                "mid_risk_count": int,
                "low_risk_count": int,
                "summary": str,
                "big_table_alert": dict or None,
            }, ...],
            # 顶层汇总 (兼容老前端 renderColumnDiff, 8/26-9/1 写的)
            "table_name": str,  # = tables[0].table_name, 兼容老单表调用
            "table_exists": bool,  # = tables[0].table_exists
            "columns": [...],  # = tables[0].columns, 兼容老前端
            "high_risk_count": int,  # = 所有表加起来
            "mid_risk_count": int,
            "low_risk_count": int,
            "summary": str,  # = 全局 summary (哪张表风险最高)
            "big_table_alert": dict or None,  # = 触发大表的那张
            # 兼容老 ok=False 返回
            "error": str,
            "hint": str,
        }
    """
    # 1. 拆 SQL, 收集所有 ALTER TABLE statements
    # CUSTOM-MODIFIED: 8/24 兼容 use `xxx` 前缀 @ 2026-08-24 @ mavis
    # CUSTOM-MODIFIED: 9/2 17:35 实战多表 DDL 收集所有 ALTER, 不再 break @ 2026-09-02 @ mavis
    alter_sqls = []
    statements = [s for s in sqlparse.split(sql_content) if s.strip()]
    for stmt in statements:
        # 在每段内找 ALTER TABLE 起始位置 (可能有 use 前缀)
        m = re.search(r"\\bALTER\\s+TABLE\\b", stmt, re.IGNORECASE)
        if m:
            alter_sql = stmt[m.start():].strip().rstrip(";").strip()
            alter_sqls.append(alter_sql)

    if not alter_sqls:
        return {
            "ok": False,
            "error": "SQL 不是 ALTER TABLE 或不包含 MODIFY/ADD/DROP COLUMN",
            "hint": "只支持 ALTER TABLE ... MODIFY/ADD/DROP COLUMN",
        }

    # 2. 遍历每条 ALTER, 单独 diff
    tables_diff = []
    total_high = total_mid = total_low = 0
    first_big_table_alert = None
    any_table_exists = False

    for idx, alter_sql in enumerate(alter_sqls):
        # 兼容老调用: 显式传 table_name 时, 只取匹配的表 (第一个 ALTER)
        force_table = table_name if (table_name and idx == 0) else None
        single = _diff_single_table(instance, db_name, alter_sql, force_table_name=force_table)

        if not single.get("ok"):
            # 单表失败 (无 MODIFY/ADD/DROP 或表不存在), 记录但不中断
            tables_diff.append({
                "ok": False,
                "table_name": single.get("table_name", "?"),
                "table_exists": single.get("table_exists", True),
                "error": single.get("error", "unknown"),
                "columns": [],
                "high_risk_count": 0,
                "mid_risk_count": 0,
                "low_risk_count": 0,
                "summary": single.get("error", "解析失败"),
                "big_table_alert": None,
            })
            continue

        if single.get("table_exists"):
            any_table_exists = True
        tables_diff.append(single)
        total_high += single.get("high_risk_count", 0)
        total_mid += single.get("mid_risk_count", 0)
        total_low += single.get("low_risk_count", 0)
        # 大表 alert 取第一张触发的 (跟 detail.html 行为一致, 只弹一次)
        if single.get("big_table_alert") and not first_big_table_alert:
            first_big_table_alert = single["big_table_alert"]

    if not tables_diff:
        return {
            "ok": False,
            "error": "SQL 不包含任何 MODIFY/ADD/DROP COLUMN 字段变更",
            "hint": "只支持 ALTER TABLE ... MODIFY/ADD/DROP COLUMN",
        }

    if not any_table_exists:
        return {
            "ok": False,
            "error": "所有 ALTER 涉及表都不存在或查不到列定义",
            "tables": tables_diff,
        }

    # 3. 全局 summary
    if total_high > 0:
        global_summary = f"共 {len(tables_diff)} 张表, 检测到 {total_high} 个高风险变更, 强烈建议补全 SQL"
    elif total_mid > 0:
        global_summary = f"共 {len(tables_diff)} 张表, 检测到 {total_mid} 个中风险变更, 注意已有数据"
    elif total_low > 0:
        global_summary = f"共 {len(tables_diff)} 张表, 检测到低风险变更, 兼容"
    else:
        global_summary = f"共 {len(tables_diff)} 张表, 所有变更兼容, 无风险"

    # 4. 顶层字段 (兼容老单表前端)
    first = tables_diff[0]
    return {
        "ok": True,
        # 9/2 D13 新增: 多表数据
        "tables": tables_diff,
        # 兼容老单表调用 (老 detail.html / sqlsubmit.html renderColumnDiff)
        "table_name": first.get("table_name", "?"),
        "table_exists": first.get("table_exists", True),
        "columns": first.get("columns", []),
        # 顶层汇总
        "high_risk_count": total_high,
        "mid_risk_count": total_mid,
        "low_risk_count": total_low,
        "summary": global_summary,
        "big_table_alert": first_big_table_alert,
    }
'''

# 注意: 上面 new_block 里的 '... '\\''{new_default}'\\''..." 是 r-string f-string 转义陷阱
# 我用了 '\\'' 实际应该是 '"'. 让我用更简单的写法
new_block = new_block.replace("'\\\\''", "'")
# 但又会影响其他 ' 部分. 让我用更简单的处理: 直接把 new_block 里的 "DEFAULT '\\''{new_default}'\\''" 改成 f"DEFAULT '{new_default}'"
# 上面已经 replace 了 '\\'' (4 字符) -> ' (1 字符), 所以现在应该是 "DEFAULT '{new_default}'"

# 写新文件
new_src = src[:start_idx] + new_block + src[end_idx:]
PATH.write_text(new_src, encoding="utf-8")
print(f"已重写 column_diff.py, 新文件 {len(new_src)} 字符")

# 简单语法检查
import ast
try:
    ast.parse(new_src)
    print("✓ 语法检查通过")
except SyntaxError as e:
    print(f"❌ 语法错误: {e}")
    raise
