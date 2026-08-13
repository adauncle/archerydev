# -*- coding: UTF-8 -*-
"""
v0.3.x 字段 diff 检测 —— 业务逻辑层。

## CUSTOM-MODIFIED: gh-ost 字段 diff 检测 @ 2026-08-12 @ mavis
## 关联: docs/designs/2026-08-12_gh-ost-column-diff-mockup.html
## 业务背景: 生产事故 —— 字段类型变更没带字符集, 跨表 JOIN 索引失效, 性能暴跌。
## 关联 changelog: docs/changelogs/2026-08-12_gh-ost-column-diff.md

提供 3 个 helper + 11 条风险规则:
    - _fetch_current_columns(instance, db, table) -> dict
    - _parse_alter_column_changes(sql_content) -> list
    - _assess_column_risk(field, old, new) -> (risk, reason)
    - column_diff_full(instance, db, sql_content) -> dict   # 整合入口

端点: POST /gh_ost/column_diff/
调用: views.column_diff(request)
"""
import re
import logging

logger = logging.getLogger("default")


# ============================================================
# 1. 查 information_schema.columns 拿当前列定义
# ============================================================
def _fetch_current_columns(instance, db_name: str, table_name: str) -> dict:
    """CUSTOM: 查 instance 库的某表所有列定义.

    返回: {col_name: ColumnDef}  失败返 None 或 {}.
    ColumnDef = {
        "type": str (e.g. "varchar(100)"),
        "data_type": str (e.g. "varchar"),
        "max_length": int,
        "charset": str (e.g. "utf8mb4" or "" for non-string),
        "collation": str (e.g. "utf8mb4_general_ci" or ""),
        "nullable": bool,
        "default": str (e.g. "0" or None or "CURRENT_TIMESTAMP"),
        "comment": str,
        "extra": str (e.g. "auto_increment"),
        "column_key": str ("PRI"/"UNI"/"MUL"/""),
    }
    """
    if not (instance and db_name and table_name):
        return {}
    try:
        from sql.models import Instance
        user, password = (
            instance.get_username_password()
            if hasattr(instance, "get_username_password")
            else (instance.user, instance.password)
        )
        import pymysql
        conn = pymysql.connect(
            host=instance.host, port=instance.port, user=user, password=password,
            database=db_name, connect_timeout=5, autocommit=True,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COLUMN_NAME, COLUMN_TYPE, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
                              CHARACTER_SET_NAME, COLLATION_NAME, IS_NULLABLE, COLUMN_DEFAULT,
                              COLUMN_COMMENT, EXTRA, COLUMN_KEY
                       FROM information_schema.columns
                       WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
                       ORDER BY ORDINAL_POSITION""",
                    (db_name, table_name),
                )
                cols = {}
                for row in cur.fetchall():
                    name = row[0]
                    cols[name.lower()] = {
                        "name": name,
                        "type": row[1] or "",
                        "data_type": (row[2] or "").lower(),
                        "max_length": row[3],
                        "charset": row[4] or "",
                        "collation": row[5] or "",
                        "nullable": (row[6] or "").upper() == "YES",
                        "default": row[7],  # None 表示 IS NULL
                        "comment": row[8] or "",
                        "extra": (row[9] or "").lower(),
                        "column_key": row[10] or "",
                    }
                return cols
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        logger.exception("_fetch_current_columns failed: %s.%s", db_name, table_name)
        return {}


def _fetch_table_size(instance, db_name: str, table_name: str) -> dict:
    """CUSTOM: 查 instance 库的某表行数 + 数据大小 (information_schema.tables).

    返回 {"rows": int, "size_mb": float, "table_name": str} 或 None (查不到).
    复用 sql.views._get_table_size_info 的实现, 复制到这里避免循环 import。
    用于 SQL 提交页大表 DDL 防呆 (跟详情页 big_table_alert 一致)。
    """
    if not (instance and db_name and table_name):
        return None
    try:
        from sql.models import Instance
        user, password = (
            instance.get_username_password()
            if hasattr(instance, "get_username_password")
            else (instance.user, instance.password)
        )
        import pymysql
        conn = pymysql.connect(
            host=instance.host, port=instance.port, user=user, password=password,
            database=db_name, connect_timeout=5, autocommit=True,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT TABLE_ROWS, DATA_LENGTH + INDEX_LENGTH "
                    "FROM information_schema.tables "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                    (db_name, table_name),
                )
                row = cur.fetchone()
                if not row:
                    return None
                rows = int(row[0] or 0)
                size_bytes = int(row[1] or 0)
                return {
                    "rows": rows,
                    "size_mb": round(size_bytes / 1024 / 1024, 1),
                    "table_name": table_name,
                }
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        logger.exception("_fetch_table_size failed: %s.%s", db_name, table_name)
        return None


def _build_big_table_alert(size_info: dict) -> dict:
    """CUSTOM: 拼大表 DDL 防呆 alert 字典 (SQL 提交页 + 详情页共用).

    返回 dict 给前端渲染, 包含阈值 + 实际值, 跟 detail.html big_table_alert 字段一致。
    size_info=None 或小于阈值返 None (不触发 alert)。
    """
    if not size_info:
        return None
    from django.conf import settings as dj_settings
    row_threshold = int(getattr(dj_settings, "CUSTOM_BIG_TABLE_ROW_THRESHOLD", 100000))
    size_threshold_mb = int(getattr(dj_settings, "CUSTOM_BIG_TABLE_SIZE_THRESHOLD_MB", 100))
    if (size_info["rows"] >= row_threshold
            or size_info["size_mb"] >= size_threshold_mb):
        return {
            "table_name": size_info["table_name"],
            "rows": size_info["rows"],
            "size_mb": size_info["size_mb"],
            "row_threshold": row_threshold,
            "size_threshold_mb": size_threshold_mb,
        }
    return None


# ============================================================
# 2. 解析 ALTER TABLE MODIFY/ADD/DROP COLUMN 子句
# ============================================================
# 注: 不用 re.VERBOSE, 因为 verbose 模式字符类 [^X\s] 里的 \s 在某些 Python 版本
# 会被当字面 \s 处理, 导致列名末尾 1 字符被吞 (status → statu, id → i)
# 改用普通 re.IGNORECASE, 显式 \s+
# 模式 1: MODIFY [COLUMN] <name> <definition>
# 模式 2: CHANGE [COLUMN] <old_name> <new_name> <definition>  (暂只取新名)
# 模式 3: ADD [COLUMN] <name> <definition> [FIRST|AFTER ...]
# 模式 4: DROP [COLUMN] <name>
_RE_MODIFY = re.compile(
    r"(?:MODIFY|CHANGE)\s+(?:COLUMN\s+)?"
    r"`?(?P<name>[^`\s(]+)`?"
    r"\s+(?P<definition>"
    r"[^,]+"  # 类型段 (greedy, 吃尽可能多, 后面 optional 段会锚定具体关键字)
    r"(?:\s+CHARACTER\s+SET\s+\S+)?"  # 可选 CHARSET
    r"(?:\s+COLLATE\s+\S+)?"           # 可选 COLLATE
    r"(?:\s+NOT\s+NULL)?"               # 可选 NOT NULL
    r"(?:\s+NULL)?"                     # 可选 NULL
    r"(?:\s+DEFAULT\s+\S+(?:\s*\([^)]*\))?)?"  # 可选 DEFAULT
    r"(?:\s+COMMENT\s+'(?:[^']|'')*')?"  # 可选 COMMENT
    r"(?:\s+ON\s+UPDATE\s+CURRENT_TIMESTAMP(?:\(\d+\))?)?"  # 可选 ON UPDATE
    r")",
    re.IGNORECASE,
)

_RE_ADD = re.compile(
    r"ADD\s+(?:COLUMN\s+)?"
    r"`?(?P<name>[^`\s(]+)`?"
    r"\s+(?P<definition>"
    r"[^,]+"
    r"(?:\s+CHARACTER\s+SET\s+\S+)?"
    r"(?:\s+COLLATE\s+\S+)?"
    r"(?:\s+NOT\s+NULL)?"
    r"(?:\s+NULL)?"
    r"(?:\s+DEFAULT\s+\S+(?:\s*\([^)]*\))?)?"
    r"(?:\s+COMMENT\s+'(?:[^']|'')*')?"
    r")",
    re.IGNORECASE,
)

_RE_DROP = re.compile(
    r"^\s*DROP\s+(?:COLUMN\s+)?`?(?P<name>[^`\s,]+)`?\s*$",
    re.IGNORECASE,
)


def _strip_quotes(s: str) -> str:
    """去反引号 + 标准化空白."""
    return s.strip().strip("`").strip()


def _parse_definition(definition: str) -> dict:
    """从 MODIFY/ADD 的 definition 段解析出结构化属性."""
    s = definition.strip()
    result = {
        "type": "",
        "charset": "",
        "collation": "",
        "nullable": True,  # 默认 NULL
        "default": None,
        "comment": "",
        "extra": "",
    }
    # 1. COMMENT '...'
    m = re.search(r"COMMENT\s+('(?:[^']|'')*')", s, re.IGNORECASE)
    if m:
        result["comment"] = m.group(1).strip("'").replace("''", "'")
        s = s[: m.start()].rstrip()
    # 2. ON UPDATE CURRENT_TIMESTAMP
    if re.search(r"ON\s+UPDATE\s+CURRENT_TIMESTAMP", s, re.IGNORECASE):
        result["extra"] = "on_update_current_timestamp"
    # 3. DEFAULT 段 (注意: 字符串 DEFAULT '0' vs 数字 DEFAULT 0)
    m = re.search(r"DEFAULT\s+('(?:[^']|'')*'|\([^)]*\)|\S+)", s, re.IGNORECASE)
    if m:
        default_raw = m.group(1)
        if default_raw.startswith("(") and default_raw.endswith(")"):
            result["default"] = default_raw  # 函数式 DEFAULT, 完整保留
        elif default_raw.startswith("'") and default_raw.endswith("'"):
            result["default"] = default_raw.strip("'").replace("''", "'")
        elif default_raw.upper() == "NULL":
            result["default"] = None  # 显式 DEFAULT NULL
        else:
            result["default"] = default_raw  # 数字 / CURRENT_TIMESTAMP 等
        s = s[: m.start()].rstrip()
    # 4. NOT NULL / NULL
    if re.search(r"\bNOT\s+NULL\b", s, re.IGNORECASE):
        result["nullable"] = False
        s = re.sub(r"\bNOT\s+NULL\b", "", s, flags=re.IGNORECASE).rstrip()
    elif re.search(r"\bNULL\b", s, re.IGNORECASE):
        result["nullable"] = True
        s = re.sub(r"\bNULL\b", "", s, flags=re.IGNORECASE).rstrip()
    # 5. COLLATE xxx
    m = re.search(r"COLLATE\s+(\S+)", s, re.IGNORECASE)
    if m:
        result["collation"] = m.group(1)
        s = s[: m.start()].rstrip()
    # 6. CHARACTER SET xxx
    m = re.search(r"CHARACTER\s+SET\s+(\S+)", s, re.IGNORECASE)
    if m:
        result["charset"] = m.group(1)
        s = s[: m.start()].rstrip()
    # 7. 剩下的就是 type 段
    result["type"] = s.strip().upper()
    return result


def _parse_alter_column_changes(sql_content: str) -> list:
    """CUSTOM: 解析 ALTER TABLE 的列定义变更.

    返回: [{
        "operation": "modify" | "add" | "drop",
        "name": str,
        "definition": dict  (modify/add 才有)
    }]
    """
    if not sql_content:
        return []

    # 先识别 ALTER TABLE <table> 段
    m = re.match(
        r"^\s*ALTER\s+TABLE\s+"
        r"(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?",
        sql_content.strip(),
        re.IGNORECASE,
    )
    if not m:
        return []

    # 用逗号拆分每个 ALTER 操作 (小心 DEFAULT 里的逗号)
    # 简化: 假设逗号都在顶层, 嵌套()里的逗号不计
    operations_text = sql_content[m.end():]
    operations = _split_top_level_commas(operations_text)

    changes = []
    for op_text in operations:
        op_text = op_text.strip().rstrip(";").strip()
        if not op_text:
            continue

        # MODIFY / CHANGE
        m_mod = _RE_MODIFY.match(op_text)
        if m_mod:
            name = _strip_quotes(m_mod.group("name"))
            definition = _parse_definition(m_mod.group("definition"))
            changes.append({"operation": "modify", "name": name, "definition": definition})
            continue

        # ADD
        m_add = _RE_ADD.match(op_text)
        if m_add:
            name = _strip_quotes(m_add.group("name"))
            definition = _parse_definition(m_add.group("definition"))
            changes.append({"operation": "add", "name": name, "definition": definition})
            continue

        # DROP
        m_drop = _RE_DROP.match(op_text)
        if m_drop:
            name = _strip_quotes(m_drop.group("name"))
            changes.append({"operation": "drop", "name": name, "definition": None})
            continue

    return changes


def _split_top_level_commas(text: str) -> list:
    """拆分顶层逗号 (忽略 () 和 '' 里的逗号)."""
    parts = []
    depth = 0
    in_quote = False
    quote_char = ""
    current = []
    for ch in text:
        if in_quote:
            current.append(ch)
            if ch == quote_char:
                in_quote = False
        elif ch in ("'", '"'):
            in_quote = True
            quote_char = ch
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


# ============================================================
# 3. 11 条风险规则 —— 单字段变更风险评估
# ============================================================
def _assess_column_risk(field: str, old_val, new_val) -> tuple:
    """CUSTOM: 11 条风险规则.

    Args:
        field: 字段名 (type/charset/collation/nullable/default/comment/extra/column_key)
        old_val: 改前值
        new_val: 改后值

    Returns:
        (risk_level, reason)
        risk_level: "high" | "mid" | "low" (无变化时返 "none")
    """
    if field == "type":
        return _assess_type_risk(old_val, new_val)
    elif field == "charset":
        return _assess_charset_risk(old_val, new_val)
    elif field == "collation":
        return _assess_collation_risk(old_val, new_val)
    elif field == "nullable":
        return _assess_nullable_risk(old_val, new_val)
    elif field == "default":
        return _assess_default_risk(old_val, new_val)
    elif field == "comment":
        return ("low", f"COMMENT 变更: '{old_val}' → '{new_val}' (无影响)")
    elif field == "extra":
        return _assess_extra_risk(old_val, new_val)
    elif field == "column_key":
        return _assess_column_key_risk(old_val, new_val)
    return ("low", f"{field}: {old_val} → {new_val}")


def _assess_type_risk(old_type: str, new_type: str) -> tuple:
    """类型变更风险."""
    if not old_type or not new_type:
        return ("low", "类型未指定")
    if old_type == new_type:
        return ("none", "类型未变")

    # 解析基础类型 + 长度
    def parse_type(t):
        t = (t or "").lower()
        m = re.match(r"(\w+)(?:\((\d+)\))?", t)
        if m:
            return m.group(1), int(m.group(2)) if m.group(2) else None
        return t, None

    old_base, old_len = parse_type(old_type)
    new_base, new_len = parse_type(new_type)

    # 1) 基础类型不同 → 高风险 (VARCHAR→TEXT / INT→BIGINT 等)
    if old_base != new_base:
        # 一些安全升级
        if {old_base, new_base} <= {"int", "bigint", "smallint", "tinyint", "mediumint"}:
            return ("low", f"整数类型兼容升级: {old_type} → {new_type}")
        return ("high", f"类型不兼容: {old_type} → {new_type}, 数据格式/索引可能丢失")
    # 2) 同一基础类型
    if old_len is not None and new_len is not None:
        if new_len < old_len:
            return ("mid", f"类型缩短 {old_len}→{new_len}, 已有数据可能截断")
        elif new_len > old_len:
            return ("low", f"类型变长 {old_len}→{new_len}, 兼容")
    return ("low", f"类型变更: {old_type} → {new_type}")


def _assess_charset_risk(old: str, new: str) -> tuple:
    """字符集变更风险."""
    if old == new:
        return ("none", "字符集未变")
    if not old or not new or "(table default)" in (old, new):
        return (
            "high",
            f"字符集变化 {old!r} → {new!r}, 跨表 JOIN 索引可能失效 (生产事故根因!)",
        )
    return ("high", f"字符集变化: {old} → {new}, 跨表 JOIN 索引可能失效")


def _assess_collation_risk(old: str, new: str) -> tuple:
    """排序规则变更风险."""
    if old == new:
        return ("none", "排序规则未变")
    if not old or not new or "(table default)" in (old, new):
        return (
            "high",
            f"排序规则变化 {old!r} → {new!r}, 排序/大小写敏感行为会变",
        )
    return ("high", f"排序规则变化: {old} → {new}, 排序/大小写敏感行为会变")


def _assess_nullable_risk(old: bool, new: bool) -> tuple:
    """可空性变更风险."""
    if old == new:
        return ("none", "可空性未变")
    # 业务调用方要传 default 信息, 这里只看 nullable 变化
    if not old and new:  # NOT NULL → NULL, 没问题
        return ("low", "从 NOT NULL 改为 NULL (兼容)")
    return ("low", "可空性变化, 注意配 DEFAULT 评估")


def _assess_nullable_with_default_risk(old_nullable: bool, new_nullable: bool, has_default: bool) -> tuple:
    """可空性变更风险 (带 DEFAULT 信息)."""
    if old_nullable == new_nullable:
        return ("none", "可空性未变")
    if not old_nullable and new_nullable:  # NOT NULL → NULL, 没问题
        return ("low", "从 NOT NULL 改为 NULL (兼容)")
    # NULL → NOT NULL
    if old_nullable and not new_nullable:
        if has_default:
            return ("mid", "NULL → NOT NULL 有 DEFAULT, 已有数据会被默认值填充")
        return ("high", "NULL → NOT NULL 无 DEFAULT, 已有 NULL 数据 ALTER 会失败")
    return ("low", "可空性变化")


def _assess_default_risk(old, new) -> tuple:
    """默认值变更风险."""
    if old == new:
        return ("none", "默认值未变")
    # 字符串 vs 数字 类型隐式转换
    old_is_str = isinstance(old, str) and old.startswith("'")
    new_is_str = isinstance(new, str) and new.startswith("'")
    if old_is_str != new_is_str:
        return ("low", f"默认值类型变化: {old!r} → {new!r} (隐式类型转换)")
    return ("low", f"默认值变化: {old!r} → {new!r}")


def _assess_extra_risk(old: str, new: str) -> tuple:
    """Extra 变更风险 (AUTO_INCREMENT / ON UPDATE)."""
    if old == new:
        return ("none", "Extra 未变")
    if "auto_increment" in old and "auto_increment" not in new:
        return ("high", "AUTO_INCREMENT 被删, 业务写入可能产生重复 ID, 序列错乱")
    if "auto_increment" not in old and "auto_increment" in new:
        return ("mid", "新增 AUTO_INCREMENT, 已有数据需要确认无重复")
    if "on_update" in old and "on_update" not in new:
        return ("mid", "ON UPDATE CURRENT_TIMESTAMP 被删, 时间字段自动更新失效")
    if "on_update" not in old and "on_update" in new:
        return ("mid", "新增 ON UPDATE, 时间字段会自动更新")
    return ("low", f"Extra 变化: {old!r} → {new!r}")


def _assess_column_key_risk(old: str, new: str) -> tuple:
    """键变更风险 (PRI / UNI)."""
    if old == new:
        return ("none", "键未变")
    if "PRI" in old and "PRI" not in new:
        return ("high", "删除主键 (PRI), 破坏表结构")
    if "PRI" not in old and "PRI" in new:
        return ("high", "新增主键, 需要表数据无重复")
    if "UNI" in old and "UNI" not in new:
        return ("mid", "删除唯一键 (UNI), 索引失效")
    return ("low", f"键变化: {old!r} → {new!r}")


# ============================================================
# 4. 整合入口: 给定 instance + db + sql, 返回完整 diff 结果
# ============================================================
def column_diff_full(instance, db_name: str, sql_content: str, table_name: str = None) -> dict:
    """字段 diff 完整流程.

    Args:
        instance: Instance model
        db_name: 数据库名
        sql_content: 用户 SQL (通常是一条 ALTER TABLE)
        table_name: 可选, 显式指定表名; 否则从 SQL 解析

    Returns:
        {
            "ok": bool,
            "table_name": str,
            "table_exists": bool,
            "columns": [{...}],  # 字段变更列表
            "high_risk_count": int,
            "mid_risk_count": int,
            "low_risk_count": int,
            "summary": str,
        }
    """
    # 1. 解析 ALTER 子句
    changes = _parse_alter_column_changes(sql_content)
    if not changes:
        return {
            "ok": False,
            "error": "SQL 不是 ALTER TABLE 或不包含 MODIFY/ADD/DROP COLUMN",
            "hint": "只支持 ALTER TABLE ... MODIFY/ADD/DROP COLUMN",
        }

    # 2. 拿表名 (从 SQL 解析 或 显式)
    if not table_name:
        m = re.match(
            r"^\s*ALTER\s+TABLE\s+"
            r"(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?",
            sql_content.strip(),
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
                    parts.append(f"DEFAULT '{new_default}'")
                else:
                    parts.append(f"DEFAULT {new_default}")
            elif not new_nullable:
                # NOT NULL 无 DEFAULT 是个 bug, 建议加 0
                parts.append("DEFAULT 0")
            if new_comment:
                parts.append(f"COMMENT '{new_comment}'")
            suggested_sql = " ".join(parts)

        columns_diff.append({
            "name": change["name"],
            "operation": "MODIFY",
            "current": current,
            "new": new_def,
            "diffs": diffs,
            "suggested_sql": suggested_sql,
        })

    # 5. 总结
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
        "big_table_alert": big_table_alert,  # None 或 dict, 前端按需渲染
    }
