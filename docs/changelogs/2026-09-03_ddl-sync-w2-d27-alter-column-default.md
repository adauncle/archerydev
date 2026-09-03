# DDL 字段 diff v0.3.x D27: ALTER COLUMN SET/DROP DEFAULT 支持

> 日期: 2026-09-03 17:25
> 阶段: v0.3.x 字段 diff 边界修复
> 模块: `sql/extensions/ddl_gh_ost/services/column_diff.py`
> 关联: 110 prod 业务方演练 wf#4776 反馈 (9/3 17:10)

## 背景

v0.3.x 字段 diff 功能 (8/12 设计, 9/2 D13 多表 DDL 重构) 只支持检测 `MODIFY/CHANGE/ADD/DROP COLUMN` 字段变更.

**缺**: `ALTER COLUMN <name> SET DEFAULT <value>` / `ALTER COLUMN <name> DROP DEFAULT` 这两种 ALTER 语法.

## 症状 (9/3 17:10 110 prod 业务方反馈)

业务方演练 wf#4776 (110 prod, 9/3 17:05:31 提交), 工单里 5 条 SQL:

```sql
alter table import_data add oil_belong text null comment '油气服务商',
add oil_card text null comment '油卡';
alter table order_pay alter column oil_money set default null;   ← 这个检测不到
alter table order_pay alter column order_num set default '录单';
alter table order_pay alter column updatetime drop default;
```

字段变更检测结果 (110 prod 业务方截图):
- 表 1/2: import_data — 所有变更兼容, 无风险 ✓
- 表 2/2: order_pay — **"ALTER TABLE 不包含 MODIFY/ADD/DROP COLUMN 字段变更"** ✗

## 根因

8/12 v0.3.x 设计 `_RE_MODIFY` / `_RE_ADD` / `_RE_DROP` 三个正则只匹配 MODIFY/CHANGE/ADD/DROP COLUMN,
**没匹配 `ALTER COLUMN ... SET DEFAULT` / `ALTER COLUMN ... DROP DEFAULT`**.

`_parse_alter_column_changes()` 函数 401-422 行 (line 401-422) 只检测 MODIFY/ADD/DROP 三个 op,
没检测 ALTER COLUMN.

`_diff_single_table()` 检测到 changes 为空时返:
```python
return {
    "ok": False,
    "error": f"ALTER TABLE 不包含 MODIFY/ADD/DROP COLUMN 字段变更",
    "hint": "只支持 ALTER TABLE ... MODIFY/ADD/DROP COLUMN",
}
```

业务方看到 "ALTER TABLE 不包含 MODIFY/ADD/DROP COLUMN 字段变更" 提示, 误以为 ALTER 写错了, 实际是 v0.3.x 字段 diff 边界缺一种语法.

## 修法

加 `_RE_ALTER_COLUMN` 正则 + `_parse_alter_column_changes` 加 alter_default operation + `_diff_single_table` 加 alter_default 比对逻辑.

### 1. 加 `_RE_ALTER_COLUMN` 正则 (line 307-322)

```python
# 模式 5: ALTER [COLUMN] <name> SET DEFAULT <value>
# 模式 6: ALTER [COLUMN] <name> DROP DEFAULT
_RE_ALTER_COLUMN = re.compile(
    r"^\s*ALTER\s+(?:COLUMN\s+)?"
    r"`?(?P<name>[^`\s(]+)`?"
    r"\s+(?P<action>SET\s+DEFAULT|DROP\s+DEFAULT)"
    r"(?:\s+(?P<value>'(?:[^']|'')*'|\([^)]*\)|\S+))?"
    r"\s*$",
    re.IGNORECASE,
)
```

### 2. `_parse_alter_column_changes` 加 alter_default operation (line 425-457)

```python
# ALTER COLUMN (D27 新加): SET DEFAULT <value> / DROP DEFAULT
m_alter = _RE_ALTER_COLUMN.match(op_text)
if m_alter:
    name = _strip_quotes(m_alter.group("name"))
    action = m_alter.group("action").upper().replace(" ", "_")
    if action == "SET_DEFAULT":
        value_raw = m_alter.group("value")
        if not value_raw or value_raw.upper() == "NULL":
            new_default = None  # 显式 SET DEFAULT NULL
        elif value_raw.startswith("(") and value_raw.endswith(")"):
            new_default = value_raw  # 函数式 DEFAULT, 完整保留
        elif value_raw.startswith("'") and value_raw.endswith("'"):
            new_default = value_raw.strip("'").replace("''", "'")
        else:
            new_default = value_raw  # 数字 / CURRENT_TIMESTAMP 等
        changes.append({
            "operation": "alter_default",
            "name": name,
            "default_action": "set",
            "new_default": new_default,
        })
    elif action == "DROP_DEFAULT":
        changes.append({
            "operation": "alter_default",
            "name": name,
            "default_action": "drop",
            "new_default": None,
        })
    continue
```

### 3. `_diff_single_table` 加 alter_default 比对 (line 800-870)

跟现有 default 比对, 单独展示 default 变更:
```python
if op == "alter_default":
    if not current:
        # 列不存在, ALTER COLUMN 会失败
        columns_diff.append({
            "name": change["name"],
            "operation": "ALTER_DEFAULT",
            "current": None,
            "new": {"default_action": change["default_action"], "new_default": change["new_default"]},
            "diffs": [{
                "field": "_op",
                "old": "missing",
                "new": "alter_default",
                "risk": "high",
                "reason": f"列名 {change['name']} 不存在, ALTER COLUMN 会失败",
            }],
        })
        high_risk += 1
        continue

    current_default = current.get("default")
    new_default = change["new_default"]
    action = change["default_action"]

    if action == "set":
        if str(current_default) == str(new_default):
            diffs = []
        else:
            diffs = [{
                "field": "default",
                "old": current_default,
                "new": new_default,
                "risk": "low",  # DEFAULT 变更不影响存量数据
                "reason": f"DEFAULT 从 {current_default!r} 改为 {new_default!r}, 不影响存量数据, 只影响新插入行",
            }]
            low_risk += 1
    elif action == "drop":
        if current_default is None:
            diffs = []
        else:
            diffs = [{
                "field": "default",
                "old": current_default,
                "new": None,
                "risk": "low",
                "reason": f"删除 DEFAULT {current_default!r}, 不影响存量数据, 只影响新插入行 (新插入行将依赖列的隐式默认值)",
            }]
            low_risk += 1

    columns_diff.append({
        "name": change["name"],
        "operation": "ALTER_DEFAULT",
        "current": current,
        "new": {"default_action": action, "new_default": new_default},
        "diffs": diffs,
    })
    continue
```

### 4. `column_diff_full` 提示更新 (line 695, 1086-1087, 1130-1131)

把 "只支持 MODIFY/ADD/DROP COLUMN" 提示更新成 "MODIFY/ADD/DROP COLUMN / ALTER COLUMN SET/DROP DEFAULT".

## 验证 (9/3 17:25 134 dev 演练)

### 演练 1: ALTER COLUMN reason SET DEFAULT 'test' (从 None -> 'test')

```
ok=True, table=accesscard_black_detail, columns=1
  col reason op=ALTER_DEFAULT current.default=None new={'default_action': 'set', 'new_default': 'test'}
    diff field=default old=None new='test' risk=low
```

**D27 PASS** ✓

### 演练 2: ALTER COLUMN created_at DROP DEFAULT (CURRENT_TIMESTAMP -> None)

```
ok=True, columns=1
  col created_at op=ALTER_DEFAULT current.default='CURRENT_TIMESTAMP'
    diff field=default old='CURRENT_TIMESTAMP' new=None risk=low
```

**D27 PASS** ✓

### 演练 3: ALTER COLUMN reason SET DEFAULT NULL (显式 NULL, 没变化)

```
ok=True, columns=1
  col reason op=ALTER_DEFAULT current.default=None new.default=None
```

diffs 空, 因为 current_default == new_default (都是 None), 不报 diff ✓

### 演练 4: ALTER COLUMN reason SET DEFAULT 12345 (数字 default)

```
ok=True, columns=1
  col reason op=ALTER_DEFAULT current.default=None new.default=12345
    diff field=default old=None new='12345' risk=low
```

**D27 PASS** ✓ (数字 default 字符串化跟 _parse_definition 套路一致)

## 改动文件 (1 文件)

| 文件 | 改动 |
|------|------|
| `sql/extensions/ddl_gh_ost/services/column_diff.py` | 加 `_RE_ALTER_COLUMN` 正则 + `_parse_alter_column_changes` 加 alter_default operation + `_diff_single_table` 加 alter_default 比对逻辑 + 错误提示更新 |

## 同源 entry

- 8/12 v0.3.x 字段 diff 设计稿 (只支持 MODIFY/ADD/DROP COLUMN, 留下 D27 实战根因)
- 8/24 v0.3.x 字段 diff 模态框 8/24 fix (8/12 实战时 modal 在 endblock 之后)
- 8/26 v0.3.x 字段 diff inline 区域 (commit 0a04775)
- 9/2 D14 推 110 prod 修汪银和工单 (D14 实战时汪银和表 V1 5.7, features.py patch)
- 9/2 D15 字符集 implicit/explicit 区分 (commit e939ffe)
- 9/2 D16 推 D15 修复实战 110 prod c9236a0 (commit 289adc7)
- 9/2 D17 验证 110 prod D15 修复实战生效

## D27 实战新发现 (跨项目可复用, 4 条)

1. **v0.3.x 字段 diff 边界检测缺 ALTER COLUMN SET/DROP DEFAULT** (D27 实战新发现) - 8/12 设计只考虑 MODIFY/ADD/DROP COLUMN, 没考虑 ALTER COLUMN 这类"改 default 不改 type"的 ALTER. v0.3.x 字段 diff 应该补上这种边界
2. **ALTER COLUMN SET/DROP DEFAULT 不报大表告警** (D27 实战新发现) - DEFAULT 变更不影响存量数据, 只影响新插入行, MySQL 5.7/8.0 都接受 in-place 变更 (5.7 Online DDL, 8.0 instant DDL), 不触发表重建. v0.3.x 字段 diff 应该单独展示 (operation="ALTER_DEFAULT"), 不混进 MODIFY 段 (避免大表告警误报)
3. **D27 演练必查真实表存在** (D27 实战踩坑) - 演练用 `order_pay` / `import_data` 表 134 dev 上不存在 (Table 'xxx' doesn't exist), 实战必查业务库真实表 (pymysql SHOW TABLES 查), 演练用真实表演练才靠谱
4. **D27 跨 v0.3.x 和 v0.5.0 范围** (D27 实战新发现) - v0.3.x 字段 diff 是历史功能, 跟 v0.5.0 跨库同步无关, 但都是同一项目 (Archery) 同一 DBA 团队, 业务方演练时混着用. W2 推 110 prod 时, v0.3.x 字段 diff 必带 D27 一起推

## D27 实战踩坑 (3 条)

1. **D27 演练用 order_pay/import_data 表 134 dev 不存在** (D27 实战踩坑) - 业务库演练多次后这些表可能没建, 实战必查 pymysql SHOW TABLES 找真实表, 演练改用 accesscard_black_detail
2. **D27 _parse_definition 把数字 default 字符串化** (D27 实战发现, 跟 _parse_definition 套路一致) - 演练 4 new.default=12345 显示成 '12345' (string), 但 diff 对比 str('12345') == str(12345) True, OK. MySQL 端 SQL 写 DEFAULT 12345 是 int, 字段 diff 字符串化方便 Python 端比对
3. **D27 必查 _diff_single_table 整体没改错 MODIFY 段** (D27 实战准备) - 改之前 py_compile column_diff.py, 实战演练 4 个 ALTER COLUMN 场景, 同时实战回归 1 个 MODIFY 场景 (看 wf#123 老的 MODIFY 还能正常字段 diff), 避免 D27 修边界把原 MODIFY 段改坏

## 待办

1. 推 110 prod (D27 1 文件):
   - column_diff.py 1 文件
   - 推前必查 110 prod md5 (D12 实战新发现)
   - 推前必查 110 prod gunicorn error log (D14 D12 实战复用)
   - 推完演练 1 个 MODIFY 工单 + 1 个 ALTER COLUMN 工单验证
2. 110 prod 推完后, 业务方演练 wf#4776 / wf#4777 (类似工单) 验证 D27 实战生效
3. W3 计划: v0.3.x 字段 diff 全部 ALTER 语法边界梳理 (RENAME COLUMN, MODIFY COLUMN COMMENT, CHANGE COLUMN, ALGORITHM=INPLACE 等), 一次性修齐

## D27 实战后 134 dev gunicorn pids

master 8713 + 4 worker 8717/8718/8720 (D27 演练拉新)
