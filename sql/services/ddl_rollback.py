# -*- coding: UTF-8 -*-
"""DDL 智能回滚 —— 解析原始 ALTER TABLE 拼逆向 SQL.

业务: 解决 gh-ost 任务回滚页面空白 bug (goinception 只支持 DML 行级回滚).
      A 方案: 解析 ALTER → 5 种 DDL 类型逆向 SQL (ADD/DROP COLUMN, ADD/DROP INDEX, MODIFY COLUMN).
      B 方案: 不支持的 DDL 类型 (RENAME / FK / CONSTRAINT / PARTITION) → 返回 warnings 提示.

设计:
- 复用 v0.3.x 字段 diff 解析器 (column_diff._fetch_current_columns + _split_top_level_commas)
- MODIFY COLUMN 智能回滚: 查 information_schema.columns 拿原 schema
- 范围限定: 5 种 DDL, 其它 (B 方案) 不尝试自动逆向 (风险大)
- 失败友好: 任何异常都 catch, 返回 {status: 1, msg, rows: []}, 不抛 500

## CUSTOM-MODIFIED: A+B 方案 DDL 智能回滚 @ 2026-08-13 @ mavis
## 关联: docs/changelogs/2026-08-13_ddl-rollback-parse.md
##       docs/designs/2026-08-13_ddl-rollback-parse-design.md
"""

import re
import logging
from typing import Optional, List, Tuple

from sql.models import SqlWorkflow, SqlWorkflowContent
from sql.extensions.ddl_gh_ost.services.column_diff import (
    _fetch_current_columns,
    _split_top_level_commas,
)

logger = logging.getLogger("default")


# ===========================================================================
# 入口 (A 方案)
# ===========================================================================
def generate_ddl_rollback(workflow: SqlWorkflow) -> dict:
    """DDL 智能回滚入口 —— 给定 SqlWorkflow, 返回 {status, msg, rows, warnings}.

    Args:
        workflow: SqlWorkflow 对象 (有 DdlGhostTask 关联, 走 gh-ost)

    Returns:
        {
            "status": 0,                            # 0=成功 (rows 可能空), 1=失败
            "msg": "",                              # 失败时填错误信息
            "rows": [
                ["原 SQL 1", "回滚 SQL 1"],
                ["原 SQL 2", "回滚 SQL 2"],
                ...
            ],
            "warnings": [                           # B 方案: 不支持的 DDL 提示
                "[ALTER TABLE ... ADD CONSTRAINT ...] 暂不支持 CONSTRAINT 自动回滚, 请手写",
                ...
            ],
        }

    业务:
        1. 拿 workflow.sql_content (原始 ALTER, 可能是多条)
        2. 按分号拆每条 ALTER TABLE
        3. 每条走 _reverse_alter_table 逆向
        4. 失败的写 warning (B 方案), 成功的写 row
        5. 任何异常都 catch, 不抛 500

    跟 goinception 路径对比:
        - goinception 走 backup_dbname 查行级 rollback (DML only)
        - A 方案走 ALTER 解析拼 schema 级别 rollback (DDL)
        - 两条路径互补, backup_sql 端点根据 _should_use_ddl_rollback 路由
    """
    try:
        sql_content = _get_workflow_sql_content(workflow)
        if not sql_content:
            return {
                "status": 1,
                "msg": "工单 SQL 内容为空",
                "rows": [],
                "warnings": [],
            }

        rows = []
        warnings = []
        statements = _split_sql_statements(sql_content)

        for stmt in statements:
            stmt = stmt.strip()
            if not stmt:
                continue
            if not _is_alter_table(stmt):
                # 非 ALTER TABLE (例如 use db, SET, INSERT, UPDATE) → 跳过
                # 注: DML 不归我们管, 走 goinception 路径
                continue

            rollback_sql, warning = _reverse_alter_table(workflow, stmt)
            if rollback_sql:
                rows.append([stmt, rollback_sql])
            elif warning:
                # truncate 过长 ALTER 避免 warning 页面难看
                short = stmt[:60] + "..." if len(stmt) > 60 else stmt
                warnings.append(f"[{short}] {warning}")

        return {
            "status": 0,
            "msg": "",
            "rows": rows,
            "warnings": warnings,
        }
    except Exception as exc:  # noqa: BLE001
        # 任何异常 catch, 不抛 500 (让 backup_sql 端点降级到 DML 路径)
        logger.exception("generate_ddl_rollback failed: workflow_id=%s", workflow.id)
        return {
            "status": 1,
            "msg": f"DDL 智能回滚失败: {exc}",
            "rows": [],
            "warnings": [],
        }


# ===========================================================================
# 路径判定 (A 方案)
# ===========================================================================
def _should_use_ddl_rollback(workflow: SqlWorkflow) -> bool:
    """判定 workflow 是否走 A 方案 (DDL 智能回滚).

    True:  workflow 关联 DdlGhostTask (走 gh-ost 改造的工单)
    False: 普通 DML 工单, 走原 goinception 路径

    设计:
        - 不查 ghost_task.status, 因为任何 status (含 failed/cancelled) 都有意义
          (用户可能想知道"如果当初成功, 怎么回滚")
        - rebuild 任务 (task_type=rebuild) workflow=NULL, 走 DdlGhostTask.DoesNotExist
          分支, 不会误入 A 路径
    """
    try:
        workflow.ghost_task  # reverse OneToOne, 不存在就 DoesNotExist
        return True
    except Exception:  # noqa: BLE001
        return False


# ===========================================================================
# 工具函数
# ===========================================================================
def _get_workflow_sql_content(workflow: SqlWorkflow) -> str:
    """拿 workflow 的 SQL 内容 (SqlWorkflowContent 走 OneToOne)."""
    try:
        return SqlWorkflowContent.objects.get(workflow=workflow).sql_content or ""
    except SqlWorkflowContent.DoesNotExist:
        return ""


def _split_sql_statements(sql_content: str) -> List[str]:
    """按分号拆 SQL, 跳过空行 + 注释. 兼容多 ALTER 在一个工单.

    设计:
        - 按 ; 拆 (MySQL 没有 BEGIN...END 包裹, 简单拆够用)
        - 跳过纯注释 + 空行的 statement
        - 保留单条 ALTER 内部的换行 (DDL 解析需要)
    """
    statements = []
    for stmt in sql_content.split(";"):
        lines = []
        for line in stmt.splitlines():
            stripped = line.strip()
            if stripped.startswith("--") or not stripped:
                continue
            lines.append(line)
        cleaned = "\n".join(lines).strip()
        if cleaned:
            statements.append(cleaned)
    return statements


def _is_alter_table(stmt: str) -> bool:
    """是否是 ALTER TABLE 语句 (忽略大小写 + 前导空白)."""
    return re.match(r"^\s*ALTER\s+TABLE\b", stmt, re.IGNORECASE) is not None


def _strip_quotes(name: str) -> str:
    """去掉表名/列名外面的反引号."""
    return name.strip("`").strip()


def _quote(name: str) -> str:
    """给表名/列名加反引号 (用于拼接 SQL)."""
    return f"`{name}`"


def _build_column_def(col_def: dict) -> str:
    """从 information_schema.columns 查到的 col_def dict 拼 column_definition 段.

    格式参考 information_schema.columns.COLUMN_TYPE 整段:
        varchar(100) NOT NULL DEFAULT '0' COMMENT '...' AUTO_INCREMENT

    Args:
        col_def: _fetch_current_columns 返回的字典 (key lowercase)
            - type: e.g. "varchar(100)"
            - nullable: bool
            - default: str or None
            - comment: str
            - extra: e.g. "auto_increment" (lowercase)

    Returns:
        column_definition 字符串 (不含字段名, 拼 ADD/MODIFY 时用)
    """
    parts = [col_def.get("type", "")]
    if not col_def.get("nullable", True):
        parts.append("NOT NULL")
    default = col_def.get("default")
    if default is not None:
        # 字符串默认值要加引号
        if isinstance(default, str) and not default.upper() in ("CURRENT_TIMESTAMP", "NULL"):
            parts.append(f"DEFAULT '{default}'")
        else:
            parts.append(f"DEFAULT {default}")
    extra = col_def.get("extra", "")
    if extra:
        parts.append(extra.upper())
    comment = col_def.get("comment", "")
    if comment:
        # 注释里的单引号要 escape
        safe_comment = comment.replace("'", "''")
        parts.append(f"COMMENT '{safe_comment}'")
    return " ".join(parts)


# ===========================================================================
# ALTER TABLE 逆向核心
# ===========================================================================
def _reverse_alter_table(workflow: SqlWorkflow, alter_sql: str) -> Tuple[Optional[str], Optional[str]]:
    """逆向单条 ALTER TABLE → (rollback_sql, warning).

    Args:
        workflow: SqlWorkflow (查 instance/db_name 用)
        alter_sql: 单条 ALTER TABLE 语句

    Returns:
        (rollback_sql, warning)
        - rollback_sql: 成功逆向则返回 SQL 字符串, 否则 None
        - warning: 失败/不识别时返回提示信息 (B 方案), 否则 None

    设计:
        - 解析每条 ALTER 操作 (逗号分隔, 嵌套 () 内的逗号不计)
        - 5 种 DDL 类型分别处理
        - 其它类型返回 (None, warning_msg)
    """
    # 1. 拆表名 + 操作段
    m = re.match(
        r"^\s*ALTER\s+TABLE\s+"
        r"(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?",
        alter_sql.strip(),
        re.IGNORECASE,
    )
    if not m:
        return None, "无法解析表名"

    schema = m.group("schema") or ""
    table = _strip_quotes(m.group("table"))
    full_table = f"{schema}.{_quote(table)}" if schema else _quote(table)

    operations_text = alter_sql[m.end():].strip().rstrip(";").strip()
    if not operations_text:
        return None, "ALTER TABLE 无操作段"

    operations = _split_top_level_commas(operations_text)

    # 2. 尝试逆向多操作
    instance = workflow.instance
    db_name = workflow.db_name
    rollback_ops, warnings = _try_reverse_operations(instance, db_name, full_table, operations)

    if rollback_ops:
        rollback_sql = f"ALTER TABLE {full_table}\n  " + ",\n  ".join(rollback_ops) + ";"
        if warnings:
            return rollback_sql, "; ".join(warnings)
        return rollback_sql, None
    elif warnings:
        return None, "; ".join(warnings)
    else:
        return None, "未识别任何支持的 DDL 操作 (支持: ADD/DROP COLUMN, ADD/DROP INDEX, MODIFY/CHANGE COLUMN)"


def _try_reverse_operations(instance, db_name: str, full_table: str, operations: List[str]) -> Tuple[List[str], List[str]]:
    """尝试逆向多个 ALTER 操作.

    Returns:
        (rollback_operations, warnings)
        - rollback_operations: 成功逆向的操作列表 (可拼成 ALTER TABLE ... ops;)
        - warnings: 失败的提示 (B 方案)
    """
    rollback_ops = []
    warnings = []
    for op in operations:
        op = op.strip().rstrip(",").strip()
        if not op:
            continue
        rb, warn = _reverse_single_op(instance, db_name, full_table, op)
        if rb:
            rollback_ops.append(rb)
        elif warn:
            warnings.append(warn)
    return rollback_ops, warnings


# ===========================================================================
# 单操作逆向 (5 种 DDL)
# ===========================================================================
def _reverse_single_op(instance, db_name: str, full_table: str, op: str) -> Tuple[Optional[str], Optional[str]]:
    """逆向单条 ALTER 操作. 5 种 DDL 分支.

    Args:
        instance: Instance 对象 (查 information_schema 用)
        db_name: 数据库名
        full_table: 完整表名 (含 schema 和反引号, 如 "`db`.`t`" 或 "`t`")
        op: 单条 ALTER 操作 (不含 ALTER TABLE 前缀)

    Returns:
        (rollback_op, warning)
        - rollback_op: 逆向 SQL 片段 (不含 ALTER TABLE 前缀, 可直接拼)
        - warning: 失败/不识别时返回提示 (B 方案)
    """
    op_stripped = op.strip()

    # ----- ADD COLUMN -----
    # ALTER TABLE t ADD COLUMN x TYPE [NOT NULL] [DEFAULT ...] [COMMENT '...']
    m = re.match(
        r"^\s*ADD\s+COLUMN\s+`?(?P<col>\w+)`?\s+(?P<def>.+?)\s*$",
        op_stripped, re.IGNORECASE | re.DOTALL,
    )
    if m:
        col = _strip_quotes(m.group("col"))
        # 逆向: DROP COLUMN (原类型不需要, 用户 drop 字段不影响)
        return f"DROP COLUMN {_quote(col)}", None

    # ----- DROP COLUMN -----
    m = re.match(
        r"^\s*DROP\s+COLUMN\s+`?(?P<col>\w+)`?",
        op_stripped, re.IGNORECASE,
    )
    if m:
        col = _strip_quotes(m.group("col"))
        return _reverse_drop_column(instance, db_name, full_table, col)

    # ----- ADD INDEX / ADD KEY / ADD UNIQUE / ADD FULLTEXT / ADD SPATIAL -----
    m = re.match(
        r"^\s*ADD\s+(?P<type>INDEX|KEY|UNIQUE\s+(?:KEY|INDEX)|FULLTEXT\s+(?:KEY|INDEX)|SPATIAL\s+(?:KEY|INDEX))\s+`?(?P<name>\w+)`?\s*\((?P<cols>[^)]+)\)",
        op_stripped, re.IGNORECASE,
    )
    if m:
        idx_name = _strip_quotes(m.group("name"))
        # 逆向: DROP INDEX
        return f"DROP INDEX {_quote(idx_name)}", None

    # ----- DROP INDEX / DROP KEY -----
    m = re.match(
        r"^\s*DROP\s+(?:INDEX|KEY)\s+`?(?P<name>\w+)`?",
        op_stripped, re.IGNORECASE,
    )
    if m:
        idx_name = _strip_quotes(m.group("name"))
        return _reverse_drop_index(instance, db_name, full_table, idx_name)

    # ----- MODIFY COLUMN / CHANGE COLUMN -----
    m = re.match(
        r"^\s*(?P<verb>MODIFY|CHANGE)\s+COLUMN\s+`?(?P<col>\w+)`?(\s+`?(?P<new_col>\w+)`?)?\s+(?P<def>.+?)\s*$",
        op_stripped, re.IGNORECASE | re.DOTALL,
    )
    if m:
        verb = m.group("verb").upper()
        col = _strip_quotes(m.group("col"))
        new_col = _strip_quotes(m.group("new_col")) if m.group("new_col") else col
        return _reverse_modify_column(instance, db_name, full_table, col, new_col, verb)

    # ----- 不支持的 DDL 类型 (B 方案) -----
    op_upper = op_stripped.upper()
    # 注意顺序: FOREIGN KEY 用 in 检测 (可能被 ADD CONSTRAINT 包裹),
    #         其他用 startswith 检测 (操作关键词必须在开头)
    unsupported_keywords_contains = [
        ("FOREIGN KEY", "FOREIGN KEY"),
    ]
    for kw, label in unsupported_keywords_contains:
        if kw in op_upper:
            return None, f"暂不支持 {label} 自动回滚, 请手写"

    unsupported_keywords_startswith = [
        ("RENAME", "RENAME"),
        ("PARTITION", "PARTITION"),
        ("ADD CONSTRAINT", "CONSTRAINT"),
        ("DROP CONSTRAINT", "CONSTRAINT"),
        ("ADD CHECK", "CHECK"),
        ("DROP CHECK", "CHECK"),
        ("ADD PRIMARY KEY", "PRIMARY KEY"),
        ("DROP PRIMARY KEY", "PRIMARY KEY"),
        ("AUTO_INCREMENT", "AUTO_INCREMENT"),
        ("CHARACTER SET", "CHARACTER SET"),
        ("COLLATE", "COLLATE"),
        ("ENGINE", "ENGINE"),
        ("ROW_FORMAT", "ROW_FORMAT"),
        ("ORDER BY", "ORDER BY"),
    ]
    for kw, label in unsupported_keywords_startswith:
        if op_upper.startswith(kw):
            return None, f"暂不支持 {label} 自动回滚, 请手写"

    return None, f"未识别的 DDL 操作"


# ===========================================================================
# DROP COLUMN 逆向 (需查 information_schema.columns)
# ===========================================================================
def _reverse_drop_column(instance, db_name: str, full_table: str, col_name: str) -> Tuple[Optional[str], Optional[str]]:
    """DROP COLUMN 逆向: 查 information_schema.columns 拿原 column_definition.

    业务: 走 gh-ost DROP COLUMN 走通后, 怎么回滚?
    答: 查当前表 schema (gh-ost cut-over 前的 schema 已存到 information_schema),
        拿原 column_definition, 拼 ADD COLUMN <原定义>.

    Args:
        instance: Instance 对象
        db_name: 数据库名
        full_table: 完整表名 (含反引号)
        col_name: 列名 (用户传入的, 大小写未规范化)

    Returns:
        (rollback_op, warning)
        - rollback_op: "ADD COLUMN `x` <原定义>"
        - warning: 字段不存在 / 查 schema 失败时

    设计:
        - _fetch_current_columns 返回的 col key 是 lowercase
        - 用户传的 col_name 可能大写, lower() 后比对
        - 字段不存在 → warning (B 方案), 不抛错
    """
    try:
        current_cols = _fetch_current_columns(instance, db_name, _strip_quotes(full_table))
    except Exception as exc:  # noqa: BLE001
        logger.exception("_fetch_current_columns failed in _reverse_drop_column")
        return None, f"查原 schema 失败: {exc}"

    if not current_cols:
        return None, f"表 {_strip_quotes(full_table)} 不存在或无权限读取"

    col_key = col_name.lower()
    if col_key not in current_cols:
        return None, f"DROP COLUMN 失败: 表中已无字段 {col_name} (可能已被 drop 多次)"

    col_def = current_cols[col_key]
    col_type = col_def.get("type", "VARCHAR(50)")  # fallback 防止空
    add_def = _build_column_def(col_def)
    return f"ADD COLUMN {_quote(col_name)} {add_def}", None


# ===========================================================================
# DROP INDEX 逆向 (需查 information_schema.statistics)
# ===========================================================================
def _reverse_drop_index(instance, db_name: str, full_table: str, idx_name: str) -> Tuple[Optional[str], Optional[str]]:
    """DROP INDEX 逆向: 查 information_schema.statistics 拿原 index 定义.

    业务: 走 gh-ost DROP INDEX 走通后, 怎么回滚?
    答: 查 information_schema.statistics 拿原 index 包含的列, 拼 ADD INDEX <原列>.

    Returns:
        (rollback_op, warning)
        - rollback_op: "ADD INDEX idx (col1, col2)" 或 "ADD UNIQUE INDEX idx (...)"
        - warning: 索引不存在 / 查 schema 失败时
    """
    import pymysql

    try:
        user, password = (
            instance.get_username_password()
            if hasattr(instance, "get_username_password")
            else (instance.user, instance.password)
        )
        conn = pymysql.connect(
            host=instance.host, port=instance.port, user=user, password=password,
            database=db_name, connect_timeout=5, autocommit=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("_reverse_drop_index: connect failed")
        return None, f"查原 schema 失败: {exc}"

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT NON_UNIQUE, INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME "
                "FROM information_schema.statistics "
                "WHERE table_schema=%s AND table_name=%s AND index_name=%s "
                "ORDER BY SEQ_IN_INDEX",
                (db_name, _strip_quotes(full_table), idx_name),
            )
            rows = cur.fetchall()
            if not rows:
                return None, f"DROP INDEX 失败: 索引 {idx_name} 不存在"

            is_unique = not rows[0][0]
            cols = [r[3] for r in rows]
            cols_str = ", ".join(_quote(c) for c in cols)

            if idx_name.upper() == "PRIMARY":
                # PRIMARY KEY 不在这里恢复 (太复杂, B 方案提示)
                return None, "DROP PRIMARY KEY 暂不支持自动回滚, 请手写 (需重命名原有 PK 字段)"

            if is_unique:
                return f"ADD UNIQUE INDEX {_quote(idx_name)} ({cols_str})", None
            else:
                return f"ADD INDEX {_quote(idx_name)} ({cols_str})", None
    except Exception as exc:  # noqa: BLE001
        logger.exception("_reverse_drop_index failed")
        return None, f"查 information_schema.statistics 失败: {exc}"
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


# ===========================================================================
# MODIFY / CHANGE COLUMN 逆向 (需查 information_schema.columns)
# ===========================================================================
def _reverse_modify_column(instance, db_name: str, full_table: str, col_name: str, new_col: str, verb: str) -> Tuple[Optional[str], Optional[str]]:
    """MODIFY/CHANGE COLUMN 逆向: 查 information_schema.columns 拿原 column_definition.

    业务: 走 gh-ost MODIFY COLUMN 走通后, 怎么回滚?
    答: 查当前表 schema, 拿原 column_definition, 拼 MODIFY/CHANGE 回原类型.

    Args:
        verb: "MODIFY" 或 "CHANGE"
        col_name: 原列名 (CHANGE 时是 old name)
        new_col: CHANGE 时的 new name (MODIFY 时跟 col_name 一样)

    Returns:
        (rollback_op, warning)
        - rollback_op: "MODIFY COLUMN `x` <原定义>" 或 "CHANGE COLUMN `y` `x` <原定义>"
        - warning: 字段不存在 / 查 schema 失败时

    设计:
        - CHANGE COLUMN 逆向时, name 顺序反转 (用原 col_name 作 new name)
        - MODIFY COLUMN 直接 MODIFY 回原定义
    """
    try:
        current_cols = _fetch_current_columns(instance, db_name, _strip_quotes(full_table))
    except Exception as exc:  # noqa: BLE001
        logger.exception("_fetch_current_columns failed in _reverse_modify_column")
        return None, f"查原 schema 失败: {exc}"

    if not current_cols:
        return None, f"表 {_strip_quotes(full_table)} 不存在或无权限读取"

    col_key = col_name.lower()
    if col_key not in current_cols:
        return None, f"MODIFY/CHANGE COLUMN 失败: 字段 {col_name} 不存在 (可能已经被 rename)"

    col_def = current_cols[col_key]
    modify_def = _build_column_def(col_def)

    if verb == "CHANGE" and new_col != col_name:
        # 用户写了 CHANGE COLUMN old_name new_name TYPE
        # 逆向: CHANGE COLUMN new_name old_name <原类型>
        return f"CHANGE COLUMN {_quote(new_col)} {_quote(col_name)} {modify_def}", None
    # MODIFY 或 CHANGE 同名 (虽然 CHANGE 通常改名, 但理论上可以)
    return f"MODIFY COLUMN {_quote(col_name)} {modify_def}", None
