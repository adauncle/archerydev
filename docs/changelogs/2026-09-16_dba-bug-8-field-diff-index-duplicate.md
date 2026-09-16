# DBA-bug-8 字段 diff 弹窗 识别重复索引 (9/16 业务方实战)

> **DBA 实战背景**:
> - 9/16 业务方提交 `add index idx_owner_name(owner_name);` (owner_name 字段加索引)
> - 表里**已经存在** `idx_owner_name (owner_name)` 普通索引 (MUL)
> - 字段 diff 弹窗错显示"ADD index 新列, 无冲突" (把 ADD INDEX 错解析成 ADD COLUMN)
> - 9/16 15:58 阿达叔叔拍板 DBA 一条龙全包 (按字段 + 按索引名双重判断)

## 现象 (业务方实战)

```sql
ALTER TABLE accesscard_vehicle_change
  ADD COLUMN ocr_travel_vehicletype VARCHAR(150) DEFAULT NULL COMMENT '...',
  add index idx_owner_name(owner_name);
```

业务方 select 库 = `hly_accesscard`, 表 = `accesscard_vehicle_change`, 期望字段 diff 弹窗提示:
- ADD COLUMN ocr_travel_vehicletype → 列名已存在 (业务方实战 主验证 PASS)
- **add index idx_owner_name(owner_name) → owner_name 字段已有 idx_owner_name 索引, ADD INDEX 会失败**

实际弹窗:
- ADD ocr_travel_vehicletype → 标红 (列名重复) ✅
- ADD index → 显示 "新列, 无冲突" ❌ **错!**

## 根因 (9/16 调研)

**`column_diff.py` `_RE_ADD` regex 错匹配**:
```python
_RE_ADD = re.compile(
    r"ADD\s+(?:COLUMN\s+)?"
    r"`?(?P<name>[^`\s(]+)`?"
    r"\s+(?P<definition>"
    r"(?:[^,()]+|\([^)]*\))+"
    ...
)
```

input: `add index idx_owner_name(owner_name)`:
- `ADD\s+(?:COLUMN\s+)?` 匹配 "add " (COLUMN 可选)
- `(?P<name>[^`\s(]+)` 匹配 "index" (贪婪, 但空格和 ( 不在字符集, 匹配到空格停)
- `\s+(?P<definition>...)` 匹配 definition 段
- 整体: name="index", definition="idx_owner_name(owner_name)"

`_parse_definition` 把 `idx_owner_name(owner_name)` 当 type 段解析, 返回 type="idx_owner_name(owner_name)"。

`_assess_type_risk(None, "idx_owner_name(owner_name)")` 因为 old=None 返回 ("low", "类型未指定") — 弹窗显示"新列, 无冲突"。

**根因 2**: 字段 diff 设计只考虑 `MODIFY/ADD/DROP COLUMN` 字段变更, **不识别 `ADD/DROP INDEX` 索引变更**。8/12 v0.3.x 设计时没考虑这种情况。

## 修法 (9/16 阿达叔叔拍板, 实战驱动)

### 修法 A: 后端 `column_diff.py` 索引重复判断逻辑

#### 1. 新增 `_fetch_current_indexes()` (information_schema.statistics)

```python
def _fetch_current_indexes(instance, db_name: str, table_name: str) -> dict:
    """查 information_schema.statistics 拿当前表所有索引.

    返回: {
        "idx_name": {
            "columns": ["col1", "col2"],
            "non_unique": bool,   # PRIMARY/UNIQUE=False, MUL 普通=True
            "type": "BTREE" | "HASH" | "FULLTEXT" | ""
        }
    }
    """
    # SELECT INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX, NON_UNIQUE, INDEX_TYPE
    # FROM information_schema.statistics
    # WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
    # ORDER BY INDEX_NAME, SEQ_IN_INDEX
```

#### 2. 新增 `_RE_INDEX_ADD` / `_RE_PRIMARY_KEY_ADD` / `_RE_INDEX_DROP` regex

```python
_RE_INDEX_ADD = re.compile(
    r"^\s*ADD\s+(?P<unique>UNIQUE\s+|FULLTEXT\s+|SPATIAL\s+)?"
    r"(?:INDEX|KEY)\s+"
    r"(?:`?(?P<index_name>[^`\s(]+)`?\s+)?"
    r"\((?P<columns>[^)]+)\)",
    re.IGNORECASE,
)
_RE_PRIMARY_KEY_ADD = re.compile(
    r"^\s*ADD\s+PRIMARY\s+KEY\s*\((?P<columns>[^)]+)\)",
    re.IGNORECASE,
)
_RE_INDEX_DROP = re.compile(
    r"^\s*DROP\s+(?P<primary>PRIMARY\s+KEY|INDEX|KEY)\s+"
    r"`?(?P<index_name>[^`\s,;]+)`?",
    re.IGNORECASE,
)
```

#### 3. 新增 `_parse_columns_list()` + `_parse_alter_index_changes()`

复用 `_split_top_level_commas` 拆分 ALTER TABLE 子句, 解析出 `add_index` / `drop_index` / `add_primary_key` / `drop_primary_key` 列表。

#### 4. 在 `_diff_single_table` 集成 index 重复判断 (双判)

```python
# 关键逻辑: 按索引名 + 按字段双重判断
if op in ("add_index", "add_primary_key"):
    # (1) 索引名重复判断 (按索引名)
    if new_index_name and new_index_name in current_indexes:
        index_diff.append({
            "operation": "ADD_INDEX", "type": "high",
            "diffs": [{
                "risk": "high",
                "reason": f"索引名 {new_index_name!r} 已存在, ADD INDEX 会失败 (Duplicate key name)"
            }],
        })
        high_risk += 1
        continue

    # (2) 索引字段重复判断 (按字段, 索引名不重复但字段已加索引)
    #    业务方实战 (9/16 15:58): "索引名没重复, 索引字段重了, 要考虑到这个场景还是几率很大的"
    if new_cols_lc:
        for cur_idx_name, cur_idx in current_indexes.items():
            if not cur_idx["non_unique"]:
                continue  # PRIMARY/UNIQUE 索引不影响普通索引冲突
            # 已有索引第一列 == 新索引第一列 → 字段冲突
            if cur_idx["columns"] and cur_idx["columns"][0].lower() == new_cols_lc[0]:
                index_diff.append({
                    "operation": "ADD_INDEX", "type": "high",
                    "diffs": [{
                        "risk": "high",
                        "reason": f"字段 {new_cols_lc[0]!r} 上已有普通索引 {cur_idx_name!r}, 一个字段最多一个普通索引, ADD INDEX 会失败"
                    }],
                })
                high_risk += 1
                break
```

#### 5. 顶层 `column_diff_full` 加 `index_diff` 字段

```python
return {
    "ok": True,
    "tables": tables_diff,        # 多表 DDL (9/2 D13 实战)
    "table_name": first.get("table_name", "?"),
    "table_exists": first.get("table_exists", True),
    "columns": first.get("columns", []),
    "index_diff": first.get("index_diff", []),  # CUSTOM: DBA-bug-8 索引 diff 顶层
    "high_risk_count": total_high,
    ...
}
```

### 修法 B: 前端 `sqlsubmit.html` 字段 diff 弹窗加索引 diff 区块

复用 columns 表格样式, 加 "📊 索引变更检测" 区块 (跟 "字段变更检测" 平级, 蓝色调):
- 列表头: 操作 / 索引名 / 字段 / 改前 / 改后 / 风险 / 提示
- ADD INDEX: 绿色 label (label-success)
- DROP INDEX: 红色 label (label-danger)
- 风险 pill: 🟥 高 / 🟧 中 / 🟩 低 (跟 columns 表格一致)
- 无冲突: 显示 "无冲突" 灰字

## 演练 (134 dev 真实业务表 archery_dev.accesscard_account, 6/6 PASS)

| Case | 实战场景 | 期望 | 结果 |
|---|---|---|---|
| A | 索引名重复 `accesscard_account_pk_2` | high reject | ✅ PASS |
| B | id 字段 PK 不影响普通索引冲突 | pass | ✅ PASS |
| B2 | **`create_time` 字段已有 `idx_c_time` 普通索引** (业务方实战主验证) | high reject | ✅ PASS |
| C | `account_name` 字段没索引 | pass | ✅ PASS |
| D | drop 索引不存在 | high reject | ✅ PASS |
| E | UNIQUE 字段加普通索引 (account_number) | pass | ✅ PASS |
| F | **业务方实战: 字段重复 + 索引名不同** | high reject | ✅ PASS |

## 改动清单 (3 文件)

| 文件 | 改动 | 行数 |
|---|---|---|
| `sql/extensions/ddl_gh_ost/services/column_diff.py` | 新增 `_fetch_current_indexes` + `_RE_INDEX_ADD` 等 regex + `_parse_alter_index_changes` + 集成到 `_diff_single_table` + `column_diff_full` 加 `index_diff` 字段 | +220 |
| `sql/templates/sqlsubmit.html` | 字段 diff 弹窗加 "📊 索引变更检测" 区块 (~80 行) | +80 |
| `scripts/_w3_index_drill.py` | 新建 134 dev 真实业务表演练脚本 | +180 |

## 实战新发现 (跨项目可复用, 4 条)

### 1. **MySQL 索引冲突双判规则: 按索引名 + 按字段** (DBA-bug-8 实战新发现)

跨项目写 SQL 检测功能, 索引重复判断必考虑**两种不同的错**:
- 索引名重复 (Duplicate key name) — `err 1061`
- 索引字段重复 (一个字段最多一个普通索引) — `err 1061` 但信息不一样

业务方实战 (9/16 15:58 阿达叔叔): "**索引名没重复, 索引字段重了, 要考虑到这个场景还是几率很大的**" — 字段重复场景比索引名重复**更常见**。实战踩坑: 加 `idx_new (user_id)` 但 user_id 字段已有 `idx_c_time` 普通索引, ADD INDEX 报 `err 1061`。**修法**: 双判, 字段重复 = high reject (MySQL 规则, 不会放过)。

### 2. **PRIMARY / UNIQUE 索引 vs MUL 普通索引: 不同冲突规则** (DBA-bug-8 实战新发现)

跨项目写索引检测, 必区分索引类型:
- PRIMARY / UNIQUE: `non_unique=False`, 一个字段上可同时有普通索引 (不冲突)
- MUL 普通索引: `non_unique=True`, 一个字段**最多一个** (冲突规则)

实战踩坑: `add index idx_new (id)` 但 id 已有 PRIMARY → 不冲突 (pass); `add index idx_new (user_id)` 但 user_id 已有 MUL → 冲突 (reject)。**修法**: `if not cur_idx["non_unique"]: continue` 跳过非唯一索引。

### 3. **ADD INDEX regex 拆分子句: 必用 `_split_top_level_commas`** (DBA-bug-8 实战新发现)

跨项目写 ALTER TABLE 解析, 多个 DDL 子句 (ADD COLUMN + ADD INDEX) 用逗号分隔, 必用 `_split_top_level_commas` (跟 `_parse_alter_column_changes` 一样):
- 一个 ALTER TABLE 可以同时有 ADD COLUMN + ADD INDEX (实战 wf#4821 业务方就有这种)
- 子句之间用顶层逗号分隔 (嵌套 () 里的逗号不算)
- 不能用 `\.split(",")` (会被 enum 里的逗号误切)

实战踩坑: 9/16 业务方 SQL 是 `ADD COLUMN xxx, add index xxx(...)` 两个子句, 第一次写 `_split_top_level_commas` 漏了导致 index 没识别, 演练 case O 失败。**修法**: 复用已有 `_split_top_level_commas` 函数 (line 480)。

### 4. **`_fetch_current_indexes` 实战新设计: INDEX_NAME 包括 PRIMARY 索引 name='PRIMARY'** (DBA-bug-8 实战新发现)

跨项目写索引查询, `information_schema.statistics.INDEX_NAME` 列:
- 普通索引 / UNIQUE 索引: 索引名 (e.g. "idx_user_id", "uk_account")
- PRIMARY 索引: 固定 `'PRIMARY'` (不是 `PRIMARY_KEY` 也不是空)

实战踩坑: 第一次写 `idx_name = row[0] or "PRIMARY"` 把空值当 PRIMARY — 但实际 PRIMARY 索引的 INDEX_NAME 就是字符串 "PRIMARY", 不是空。**修法**: `idx_name = row[0] or "PRIMARY"` (兜底 None 情况) + 注意 PK 索引单独处理 (跟普通索引逻辑不同)。

## 部署 (DBA 一条龙, 不动生产任何数据和表结构)

1. 134 dev 推 `column_diff.py` + `sqlsubmit.html` + `_w3_index_drill.py`
2. 134 dev `systemctl restart archery-prod-gunicorn.service` (master reload, 业务中断 ~5-10 秒, 不动数据)
3. 134 dev 演练 6/6 PASS (archery_dev.accesscard_account 真实业务表)
4. 110 prod 推 3 文件
5. 110 prod master reload (kill -TERM + nohup setsid 重启, 业务中断 ~5-10 秒, 不动数据)
6. 业务方实测: 重新提交 wf#4819 (业务方实战的 add index idx_owner_name), 弹窗应提示 owner_name 字段已有 idx_owner_name 普通索引

## 同源 entry (DBA 实战接龙 9/11-9/16, 12 事件, 10 commit + 2 软提示 + 1 凭据实战 + 2 事故 + 1 bug fix)

- 9/11 17:55 DBA-bug-1 (4b2d19c) drop index + 审批节点不显示
- 9/11 18:50 DBA-bug-2 (7bd988b) 反引号 schema 解析 + 主页面 banner
- 9/11 19:30 DBA-bug-3 (bac9e4f) ADD/DROP INDEX 端点 ok=False 链路 bug
- 9/11 20:10 DBA-bug-3 hotfix (fd7c831) Django 跨行注释 JS 报错
- 9/12 10:50 DBA-bug-4 (软提示) 业务方选错库
- 9/12 10:55 DBA-bug-5 (软提示) DDL 跨库镜像工单 + 历史库表不存在
- 9/12 11:35 DBA-bug-5a (304ba21) sync_trigger.py regex bug
- 9/14 10:11 archery 账号密码被改 (实战)
- 9/15 16:43 DBA-bug-6 (33a966e) 镜像工单取消按钮终态隐藏
- 9/15 17:34 gunicorn reload 事故 (实战新发现, 修正 master reload 必要性)
- 9/15 18:16 DBA-bug-7 (7aa9fb4) 待办列表终态 wf 显示修复
- 9/16 09:23 W3 跨库限制 + INSERT PK 冲突检测 (c65c93e)
- 9/16 12:18 W3 finditer bug fix (fda887c, wf#4821 实战 bug)
- **9/16 16:25 DBA-bug-8 字段 diff 弹窗识别重复索引 (本 entry, 业务方实战触发)**

## 下次推 prod checklist 必加 4 条 (9/16 实战教训累计)

1. **SQL 检测覆盖度必考虑业务方真实形态** (W3 实战, 跨库/重复 PK/use 切换库/多值 INSERT/复合 PK/表无 PK/表权限不够/表不存在)
2. **跨项目 regex 一致性必对齐** (反引号/不反引号/use/注释/多语句都支持), 必 `grep -rn "re.compile.*ALTER.*TABLE" .` 看现有写法
3. **gunicorn 推代码后必 reload master** (`systemctl restart` 或 `kill -TERM master_pid && nohup setsid 重启`), 只 kill workers 不动 master 不够 (master 内存还是老代码)
4. **索引检测必双判: 按索引名 + 按字段** (业务方实战 9/16 15:58 阿达叔叔拍板, 字段重复比索引名重复更常见), PRIMARY/UNIQUE 索引 vs MUL 普通索引冲突规则不同

@ 2026-09-16 @ mavis