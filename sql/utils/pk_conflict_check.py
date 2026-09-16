"""W3 INSERT 主键冲突检测 (9/16 阿达叔叔拍板 A 严格, reject + 阻止提交)

## 业务背景

9/16 09:00 阿达叔叔反馈 wf#4834 业务方实战工单: 15 条 INSERT INTO `output_fee_config`
VALUES (302, ...), (303, ...), ..., (311, ...), 其中 306/307/308/309 重复 (跟前面 #1-#9
行错位, 实际执行时第 10 条 error: `Duplicate entry '306' for key 'output_fee_config.PRIMARY'`.

9/16 09:23 阿达叔叔拍板 A 严格 (PK 冲突 reject 阻止提交), DBA 一条龙全包.

## 9/16 调研

- Archery 上游 SQL 检测走 inception/goinception, inception `--real_row_count` 只能拿影响行数
- inception 不查 DB 现有 PK 值, 不知道 INSERT VALUES 里的 PK 是否冲突
- 业务方 INSERT 错位重复, 14 条 warning + 1 条 error 全 approve 后跑, 浪费工单流

## 9/16 修法

sql_api/api_workflow.py:50-78 ExecuteCheck.post 走 inception 检测**之后** + 走
pk_conflict_check. 前端 sqlsubmit.html 检测后回调: 检测到 PK 冲突 → 红框 alert + 阻止提交.

## 关联

- 9/11 DBA-bug-1 套路: SQL 预处理 use/-- 注释/空行
- 9/11 DBA-bug-2 套路: regex 支持反引号 schema
- 9/11 DBA-bug-3 套路: 端点 ok=False 失败分支保留次要数据
- 9/12 DBA-bug-4 (软提示): 业务方实战 PK 冲突
- DBA-bug-6 实战新发现: UI 跟后端判断逻辑必须对齐
- gh-ost precheck 套路: 用 `Instance.get_username_password()` 拿 mirage 解密凭据
@ 2026-09-16 @ mavis
"""

import logging
import re

import pymysql
from mirage import exceptions as mirage_exceptions

logger = logging.getLogger("default")


# ===== SQL 解析辅助 =====

# 跟 cross_db_check.py / column_diff.py / sync_trigger.py 一致 (regex 一致性)
_RE_INSERT = re.compile(
    r"^\s*INSERT\s+INTO\s+"
    r"(?:(?:`?(?P<schema>[^`\s.()]+)`?)\.)?"
    r"`?(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,
)

# use 前缀跳过 (DBA-bug-1 套路)
_RE_USE = re.compile(r"^\s*use\s+", re.IGNORECASE)


def _preprocess_sql(sql_content: str) -> str:
    """预处理 SQL: 跳过 use/-- 注释/空行."""
    cleaned_lines = []
    for line in sql_content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if _RE_USE.match(stripped):
            continue
        cleaned_lines.append(stripped)
    return "\n".join(cleaned_lines).strip()


def _strip_quotes(value: str) -> str:
    """去掉单/双引号/反引号 + 数值化尝试.

    - '123' → '123' (字符串)
    - \"123\" → '123'
    - `123` → '123'
    - 123 → 123 (int)
    - 'NULL' → 'NULL' (特殊值)
    - 'NULL' → None (业务方 SQL 用 NULL 表示 NULL)
    """
    v = value.strip()
    # 反引号 (MySQL 反引号引用列名, 一般不会出现在 VALUE 里)
    if v.startswith("`") and v.endswith("`"):
        v = v[1:-1]
    # 双引号
    if v.startswith('"') and v.endswith('"') and len(v) >= 2:
        v = v[1:-1]
    # 单引号
    if v.startswith("'") and v.endswith("'") and len(v) >= 2:
        v = v[1:-1]
    # NULL (case insensitive)
    if v.upper() == "NULL":
        return None
    # 9/16 实战踩坑: 之前用 v.isdigit() 无法识别负数 -1, 改用 try/except int/float 统一处理
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _split_values_tuples(values_str: str) -> list:
    """拆分 VALUES 后面的 (v1, v2, ...), (v3, v4, ...) 列表.

    边界:
    - 嵌套括号: VALUES (1, 'func(x)', 3)
    - 单/双引号转义: VALUES ('O''Brien', 1)
    - 多行: VALUES 跨行 + INSERT 分号前后

    返回: [[val1_str, val2_str, ...], [val3_str, val4_str, ...], ...]

    9/16 实战踩坑: 之前 if cur: 判断时机错了 (cur 永远空 list, append 之后 cur 非空才能添加)
    + 漏了 ',' 字段切分. 修法: ',' 切字段 + ')' 切 tuple, 立即 append cur.
    """
    tuples = []
    i = 0
    n = len(values_str)
    while i < n:
        # 找下一个 '('
        while i < n and values_str[i] != "(":
            i += 1
        if i >= n:
            break
        i += 1  # 跳过 '('
        cur = []
        buf = ""
        in_single = False
        in_double = False
        while i < n:
            ch = values_str[i]
            if ch == "'" and not in_double:
                in_single = not in_single
                buf += ch
                i += 1
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                buf += ch
                i += 1
                continue
            if ch == "\\" and i + 1 < n:
                buf += ch + values_str[i + 1]
                i += 2
                continue
            if ch == "(" and not in_single and not in_double:
                # 嵌套, 不算 VALUES 边界 (应该是函数调用)
                buf += ch
                i += 1
                continue
            if ch == "," and not in_single and not in_double:
                # 9/16 实战踩坑加: ',' 切分字段 (这是修复的关键)
                if buf.strip():
                    cur.append(buf.strip())
                buf = ""
                i += 1
                continue
            if ch == ")" and not in_single and not in_double:
                i += 1
                if buf.strip():
                    cur.append(buf.strip())
                # 9/16 修: 不再用 if cur: (永远是空), 改成 if len(cur) > 0
                if len(cur) > 0:
                    tuples.append(cur)
                break
            buf += ch
            i += 1
    return tuples


def _parse_insert_columns_and_values(stmt: str) -> tuple:
    """解析单条 INSERT 语句, 拿到 (列名列表, VALUES 元组列表).

    返回: (columns, values_list)
    - columns: ['id', 'col1', 'col2'] 或 None (未显式指定)
    - values_list: [['302', 'a', 'b'], ['303', 'c', 'd']]

    业务方 INSERT 形态:
    - INSERT INTO `tbl` VALUES (1, 2, 3)
    - INSERT INTO `tbl` (id, col1) VALUES (1, 'a')
    - INSERT INTO `tbl` VALUES (1, 'a'), (2, 'b'), (3, 'c')
    - INSERT INTO `schema`.`tbl` (id) VALUES (1)

    失败返 (None, []).
    """
    # 匹配 INSERT INTO table [(cols)] VALUES (...)
    m = re.match(
        r"^\s*INSERT\s+INTO\s+"
        r"(?:(?:`?(?P<schema>[^`\s.()]+)`?)\.)?"
        r"`?(?P<table>[^`\s(]+)`?"
        r"\s*(?P<cols>\([^)]*\))?\s*"
        r"VALUES\s*(?P<values>.*)$",
        stmt,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None, []
    cols_part = m.group("cols")
    values_str = m.group("values")
    # 列名列表
    columns = None
    if cols_part:
        columns = [c.strip().strip("`") for c in cols_part.strip("()").split(",")]
    # VALUES 元组列表
    values_list = _split_values_tuples(values_str)
    return columns, values_list


def _extract_inserts(sql_content: str) -> list:
    """扫描 SQL, 提取所有 INSERT 语句的 (schema, table, columns, values_list).

    返回: [{schema, table, columns, values_list}, ...]
    """
    cleaned = _preprocess_sql(sql_content)
    if not cleaned:
        return []

    inserts = []
    for stmt in cleaned.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        m = _RE_INSERT.match(stmt)
        if not m:
            continue
        schema = m.group("schema")
        table = (m.group("table") or "").strip("`")
        columns, values_list = _parse_insert_columns_and_values(stmt)
        if not table or not values_list:
            continue
        inserts.append({
            "schema": schema,
            "table": table,
            "columns": columns,
            "values_list": values_list,
        })
    return inserts


def _fetch_table_pk_column(instance, db_name: str, table_name: str) -> str:
    """查表 PK 列名 (information_schema.statistics INDEX_NAME='PRIMARY').

    返回: PK 列名 (str) 或 None (无 PK).

    边界:
    - 无 PK: INFORMATION_SCHEMA.STATISTICS INDEX_NAME='PRIMARY' 查不到 → None
    - 复合 PK: INDEX_NAME='PRIMARY' + SEQ_IN_INDEX=1 的 COLUMN_NAME (只取第 1 列, 实战够用)
    - 表不存在: SQL 抛 OperationalError → None
    - 权限不够: SQL 抛 OperationalError → None
    """
    try:
        conn = pymysql.connect(
            host=instance.host,
            port=instance.port,
            user=instance.user,
            password=instance.password,
            database=db_name,
            charset="utf8mb4",
            connect_timeout=5,
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COLUMN_NAME FROM information_schema.statistics "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                    "AND INDEX_NAME='PRIMARY' ORDER BY SEQ_IN_INDEX LIMIT 1",
                    (db_name, table_name),
                )
                row = cursor.fetchone()
                return row[0] if row else None
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "pk_conflict_check._fetch_table_pk_column 失败 db=%s table=%s err=%s",
            db_name, table_name, e,
        )
        return None


def _fetch_columns_order(instance, db_name: str, table_name: str) -> list:
    """查表列顺序 (information_schema.columns ORDINAL_POSITION).

    用于: 业务方 INSERT 没显式指定列名时, 通过列顺序拿 PK 值位置.

    返回: [col1, col2, ...] 或 [] (查不到).
    """
    try:
        conn = pymysql.connect(
            host=instance.host,
            port=instance.port,
            user=instance.user,
            password=instance.password,
            database=db_name,
            charset="utf8mb4",
            connect_timeout=5,
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COLUMN_NAME FROM information_schema.columns "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                    "ORDER BY ORDINAL_POSITION",
                    (db_name, table_name),
                )
                return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "pk_conflict_check._fetch_columns_order 失败 db=%s table=%s err=%s",
            db_name, table_name, e,
        )
        return []


def _query_existing_pks(
    instance, db_name: str, table_name: str, pk_col: str, pk_values: list
) -> list:
    """查 DB 中已存在的 PK 值 (SELECT pk_col FROM table WHERE pk_col IN (...)).

    边界:
    - pk_values 空: 返 []
    - pk_values > 1000 个: 截断到 1000 个 (避免 SQL IN 太大)
    - 表无权限: OperationalError → []
    - 表不存在: OperationalError → []
    """
    if not pk_values:
        return []
    # 截断到 1000 个
    truncated = pk_values[:1000]
    if len(pk_values) > 1000:
        logger.warning(
            "pk_conflict_check._query_existing_pks 截断 db=%s table=%s total=%s truncated=1000",
            db_name, table_name, len(pk_values),
        )
    try:
        conn = pymysql.connect(
            host=instance.host,
            port=instance.port,
            user=instance.user,
            password=instance.password,
            database=db_name,
            charset="utf8mb4",
            connect_timeout=5,
        )
        try:
            with conn.cursor() as cursor:
                placeholders = ",".join(["%s"] * len(truncated))
                cursor.execute(
                    f"SELECT `{pk_col}` FROM `{table_name}` "
                    f"WHERE `{pk_col}` IN ({placeholders}) LIMIT {len(truncated)}",
                    truncated,
                )
                return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "pk_conflict_check._query_existing_pks 失败 db=%s table=%s err=%s",
            db_name, table_name, e,
        )
        return []


def _get_instance_credentials(instance):
    """拿 instance user/password (mirage 解密), 兼容加密字段.

    跟 gh-ost precheck 同样的方式: `Instance.get_username_password()` (password mixin).
    """
    try:
        user, password = instance.get_username_password()
        return user, password
    except Exception:
        # fallback: 直接读字段 (instance.password 是 mirage EncryptedCharField)
        return instance.user, instance.password


def _resolve_insert_pk_values(insert: dict, instance, db_name: str) -> tuple:
    """解析单条 INSERT 提取**仅 PK 列对应**的 VALUES 值列表.

    返回: (pk_col_name, pk_values_list)
    - (None, []): 表无 PK 列 (业务方 INSERT 不触发 PK 冲突)
    - (pk_col, [v1, v2, ...]): PK 列名 + 仅 PK 列对应的 VALUES 值

    业务方 INSERT 形态覆盖:
    - INSERT INTO tbl (id, col1, col2) VALUES (1, 'a', 'b'), (2, 'c', 'd')
      → 显式指定列, columns=['id', 'col1', 'col2'], VALUES 第 1 列 = PK
      → pk_values = [1, 2] (只取 PK 列对应的值, 不是整行 VALUES)
    - INSERT INTO tbl VALUES (1, 'a', 'b'), (2, 'c', 'd')
      → 未指定列, 查 information_schema.columns 拿列顺序, PK 在第几列就拿第几列
      → pk_values = [1, 2] (只取 PK 列对应的值)
    - INSERT INTO tbl (col1, id, col2) VALUES ('a', 1, 'b')
      → 显式指定列但列顺序乱, 找 'id' 在 columns 里的索引位置拿
      → pk_values = [1]

    关键修复 (9/16): 只提取 PK 列对应的值, **不要把整行都返**.
    实战踩坑: 之前 _query_existing_pks(pk_values=[10000, 'test', 'test']) 会报
      "Truncated incorrect DOUBLE value: 'test'", MySQL 把 'test' 当 DOUBLE 解析失败.
    """
    table = insert["table"]
    columns = insert["columns"]
    values_list = insert["values_list"]
    if not values_list:
        return None, []

    # 1. 拿 PK 列名
    pk_col = _fetch_table_pk_column(instance, db_name, table)
    if not pk_col:
        return None, []

    # 2. 找 PK 在 columns 里的索引位置
    if columns is not None:
        # 业务方显式指定了列名 (e.g. INSERT INTO tbl (id, col1) VALUES (1, 'a'))
        try:
            pk_idx = [c.strip("`") for c in columns].index(pk_col)
        except ValueError:
            # 业务方 INSERT 列名里没有 PK 列 (e.g. INSERT INTO tbl (col1) VALUES ('a'))
            return pk_col, []  # 不报错, 跳过
    else:
        # 业务方没指定列名, 走列顺序查 information_schema.columns
        cols_order = _fetch_columns_order(instance, db_name, table)
        try:
            pk_idx = cols_order.index(pk_col)
        except ValueError:
            return pk_col, []

    # 3. 从 values_list 每行**只取第 pk_idx 个值** (PK 列对应的值, 不是整行)
    pk_values = []
    for row in values_list:
        if pk_idx < len(row):
            v = _strip_quotes(row[pk_idx])
            if v is not None:  # 跳过 NULL
                pk_values.append(v)
    return pk_col, pk_values


def check_pk_conflict(sql_content: str, instance, db_name: str) -> dict:
    """INSERT 主键冲突检测.

    参数:
    - sql_content: 业务方提交的 SQL 文本
    - instance: Instance 对象
    - db_name: 业务方 select 的库

    返回: dict
    - ok=True: 无冲突
    - ok=False: 有冲突, conflicts 列表含详情
    - conflicts: [{table, pk_col, existing_pks, duplicate_count, hint}]

    ## 9/16 实战案例

    - 表: output_fee_config, PK: id
    - 业务方 INSERT 15 条: VALUES (302, 1, 159, ...), (303, 2, 160, ...), ..., (311, 2, 215, ...)
    - 提取 schemas = {} → 同库
    - INSERT 解析: 15 行, 每行 id = 302..311
    - _fetch_table_pk_column: id
    - _query_existing_pks: 查 SELECT id FROM output_fee_config WHERE id IN (302..311)
    - 实战 (wf#4834): 302-305/310/311 没冲突 (首次插入), 306-309 已在表里
    - 预期 conflicts=[{table: "hly_datacenter_mod.output_fee_config", pk_col: "id",
      existing_pks: [306, 307, 308, 309], duplicate_count: 4}]

    ## 边界

    - 表无 PK: ok=True (skip, 没有 PK 列不冲突)
    - 表不存在: ok=True (inception 已经报错)
    - 表权限不够: ok=True + warning (业务方要看 audit)
    - 业务方 INSERT 没指定列名: 走 information_schema.columns 查列顺序
    - 复合 PK: 只取第 1 列 (实战够用, 9/16 阿达叔叔拍板)
    - PK 值 NULL: skip (NULL 不冲突)
    - PK 值 > 1000: 截断 + warning
    """
    inserts = _extract_inserts(sql_content)
    if not inserts:
        return {"ok": True, "conflicts": []}

    # 处理 instance 加密凭据 (跟 gh-ost precheck 一致)
    instance.user, instance.password = _get_instance_credentials(instance)

    # 合并所有 INSERT 的 (table, pk_values)
    table_pk_map = {}  # {table_name: {"pk_col": str, "pk_values": []}}
    for ins in inserts:
        pk_col, pk_values = _resolve_insert_pk_values(ins, instance, db_name)
        if not pk_col or not pk_values:
            continue
        if ins["table"] not in table_pk_map:
            table_pk_map[ins["table"]] = {"pk_col": pk_col, "pk_values": []}
        # 去重 (业务方可能同 INSERT 重复 PK)
        existing_set = set(table_pk_map[ins["table"]]["pk_values"])
        for v in pk_values:
            if v not in existing_set:
                table_pk_map[ins["table"]]["pk_values"].append(v)
                existing_set.add(v)

    # 查 DB 拿每个表的 PK 冲突
    conflicts = []
    for table, info in table_pk_map.items():
        pk_col = info["pk_col"]
        pk_values = info["pk_values"]
        existing = _query_existing_pks(instance, db_name, table, pk_col, pk_values)
        if existing:
            conflicts.append({
                "table": f"{db_name}.{table}",
                "pk_col": pk_col,
                "existing_pks": sorted(existing),
                "duplicate_count": len(existing),
                "hint": (
                    f"INSERT 语句中 PK 值 {sorted(pk_values)[:20]}... 在 {db_name}.{table} 表中已存在, "
                    f"实际 {len(existing)} 个冲突. "
                    f"请修改 VALUES 或拆分成多个工单."
                ),
            })

    return {"ok": not conflicts, "conflicts": conflicts}