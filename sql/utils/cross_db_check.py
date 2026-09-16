"""W3 跨库 SQL 检测 (9/16 阿达叔叔拍板 A 严格, reject + 阻止提交)

## 业务背景

9/16 09:00 阿达叔叔反馈 wf#4821 (alter table hly_usercenter.accesscard_user_vehicle_change
跨库) + wf#4834 (INSERT 306 重复 PK) 业务方实战工单.
9/16 09:23 阿达叔叔拍板 A 严格 (跨库 reject 阻止提交 + PK 冲突 reject 阻止提交), DBA 一条龙全包.

## 9/16 调研

- Archery 上游 SQL 检测走 inception/goinception, 这两个都是 SQL 语法/语义级检测.
- sql/engines/goinception.py:82-87 execute_check 强制 `use '{db_name}'` 走 inception,
  inception 检测的是 db_name 库的 SQL.
- 业务方 SQL 文本 `alter table hly_usercenter.accesscard_user_vehicle_change` 走 inception
  时只检测语法, **不判定是不是 db_name 库** (inception 不知道业务方 select 的库).

## 9/16 修法

sql_api/api_workflow.py:50-78 ExecuteCheck.post 走 inception 检测**之后** + 走
cross_db_check. 前端 sqlsubmit.html 检测后回调: 检测到跨库 → 红框 alert + 阻止提交按钮.

## 关联

- 9/11 DBA-bug-1 套路: SQL 预处理 use/-- 注释/空行
- 9/11 DBA-bug-2 套路: regex 支持反引号 schema + 不带反引号 schema
- column_diff.py:402-405 / sync_trigger.py:67-71 套路: regex 一致性
- DBA-bug-6 实战新发现: UI 跟后端判断逻辑必须对齐, 别让用户看到提示还能提交
@ 2026-09-16 @ mavis
"""

import re

from common.config import SysConfig


# ===== SQL 解析辅助 =====

# 跟 column_diff.py:402-405 / sync_trigger.py:67-71 一致 (regex 一致性)
# DDL/DML regex: ALTER TABLE / INSERT INTO / UPDATE / DELETE FROM / CREATE TABLE / DROP TABLE
# schema 段: `?[^`\s.()]+\`?\. (可选 schema. + 不带/带反引号)
# table 段: `?[^`\s(]+\`? (不带/带反引号)
_RE_ALTER = re.compile(
    r"^\s*ALTER\s+TABLE\s+"
    r"(?:(?:`?(?P<schema>[^`\s.()]+)`?)\.)?"
    r"`?(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,
)
_RE_INSERT = re.compile(
    r"^\s*INSERT\s+INTO\s+"
    r"(?:(?:`?(?P<schema>[^`\s.()]+)`?)\.)?"
    r"`?(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,
)
_RE_UPDATE = re.compile(
    r"^\s*UPDATE\s+"
    r"(?:(?:`?(?P<schema>[^`\s.()]+)`?)\.)?"
    r"`?(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,
)
_RE_DELETE = re.compile(
    r"^\s*DELETE\s+FROM\s+"
    r"(?:(?:`?(?P<schema>[^`\s.()]+)`?)\.)?"
    r"`?(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,
)
_RE_CREATE = re.compile(
    r"^\s*CREATE\s+TABLE\s+"
    r"(?:(?:`?(?P<schema>[^`\s.()]+)`?)\.)?"
    r"`?(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,
)
_RE_DROP = re.compile(
    r"^\s*DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
    r"(?:(?:`?(?P<schema>[^`\s.()]+)`?)\.)?"
    r"`?(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,
)

# use 前缀跳过 (DBA-bug-1 套路)
_RE_USE = re.compile(r"^\s*use\s+", re.IGNORECASE)


def _preprocess_sql(sql_content: str) -> str:
    """预处理 SQL: 跳过 use/-- 注释/空行, 找第一条有效语句.

    跟 9/11 DBA-bug-1 _parse_first_alter 套路一致, 这里**返回整个 cleaned SQL** (不去单条).
    """
    cleaned_lines = []
    for line in sql_content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if _RE_USE.match(stripped):
            continue
        cleaned_lines.append(stripped)
    return "\n".join(cleaned_lines).strip()


def _extract_schemas(sql_content: str) -> set:
    """扫描 SQL, 提取所有 DDL/DML 语句的 schema 名.

    返回: set of schema names (含 `None` 表示无 schema, 即同库)

    - ALTER TABLE `hly_usercenter`.`accesscard_xxx` → {'hly_usercenter'}
    - ALTER TABLE accesscard_xxx → {None} (无 schema, 同库)
    - ALTER TABLE `hly_usercenter`.xxx + ALTER TABLE `hly_accesscard`.xxx → {'hly_usercenter', 'hly_accesscard'}
    """
    cleaned = _preprocess_sql(sql_content)
    if not cleaned:
        return set()

    schemas = set()
    # 按 `;` 拆分多条 SQL
    for stmt in cleaned.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        # 5 个 DDL/DML regex 都试一次 (顺序不影响, 性能 OK)
        for regex in (_RE_ALTER, _RE_INSERT, _RE_UPDATE, _RE_DELETE, _RE_CREATE, _RE_DROP):
            m = regex.match(stmt)
            if m:
                schema = m.group("schema")
                # schema 段可能是 None (无 schema, 同库) 或字符串
                schemas.add(schema)  # None 直接 set 加进去
                break  # 一个语句匹配一个 regex 就够了

    return schemas


def check_cross_db(sql_content: str, instance, db_name: str) -> dict:
    """跨库 SQL 检测.

    参数::
    - sql_content: 业务方提交的 SQL 文本
    - instance: Instance 对象 (业务方 select 的实例)
    - db_name: 业务方 select 的 的库 (instance 上选定的)

    返回: dict
    - ok=True: 无跨库
    - ok=False: 有跨库, error 含详情
    - schemas: 提取到的所有 schema (含 None 表示无 schema)

    ## 9/16 实战案例

    - 业务方 select db_name = hly_accesscard
    - SQL: ALTER TABLE `hly_usercenter`.`accesscard_user_vehicle_change` ADD COLUMN xxx
    - 提取 schemas = {'hly_usercenter'} ≠ {'hly_accesscard'} → 跨库 ❌ reject
    - error: "SQL 涉及库 ['hly_usercenter'] 跟您选的库 hly_accesscard 不一致"

    - SQL: ALTER TABLE accesscard_vehicle_change ADD COLUMN xxx (无库名)
    - 提取 schemas = {None} → 同库 (无 schema = 同库) ✅ pass

    - SQL: ALTER TABLE `hly_accesscard`.accesscard_vehicle_change ADD COLUMN xxx
    - 提取 schemas = {'hly_accesscard'} == {'hly_accesscard'} → 同库 ✅ pass

    - SQL: use hly_usercenter; ALTER TABLE accesscard_vehicle_change ADD COLUMN xxx
    - use 跳过, ALTER 不带 schema → 同库 ✅ pass (业务方主动 use 切换库后, alter 同库)
    """
    schemas = _extract_schemas(sql_content)

    # 没提取到任何 schema (空 SQL 或全 SELECT) → 默认同库 pass
    # 含 None (业务方没写库名) → 默认同库 pass
    if not schemas or schemas == {None}:
        return {"ok": True, "schemas": [], "expected_db": db_name}

    # 业务方 select 的库 vs SQL 里提取的库
    other_schemas = sorted([s for s in schemas if s and s.lower() != db_name.lower()])
    if other_schemas:
        return {
            "ok": False,
            "error": (
                f"⚠️ 跨库 SQL 检测失败: SQL 涉及库 {other_schemas} 跟您选的库 "
                f"{db_name} 不一致. Archery 工单不允许跨库执行, "
                f"请选择对应库 (如 {other_schemas[0]}), "
                f"或删除库名前缀 (如 `{other_schemas[0]}`.table_name → table_name). "
                f"如需跨库变更, 请拆分成多个工单."
            ),
            "schemas": sorted(s for s in schemas if s),
            "expected_db": db_name,
        }

    # 所有 schema 都跟 db_name 一致 → 同库 pass
    return {
        "ok": True,
        "schemas": sorted(s for s in schemas if s),
        "expected_db": db_name,
    }