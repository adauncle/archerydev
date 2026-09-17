# DBA-bug-10 CREATE INDEX 绕过 ALTER 检测修复

> **变更日期**：2026-09-17 17:00
> **修复者**：mavis
> **影响范围**：所有 SQL 审核入口（提交页 / 详情页 / 镜像工单 / gh-ost 检测）
> **关联**：
> - 实战工单：wf#4849（"24512-ETC-账户收费变更增加批量变更"）
> - 用户发现：9/17 16:59 阿达叔叔反馈 CREATE INDEX 绕过检测
> - changelog: 本文件

## 业务背景

DBA 团队 9/17 16:59 收到业务方工单 wf#4849 反馈：业务方用 `CREATE INDEX` 绕过所有 ALTER 检测。

实战工单 SQL：
```sql
use `hly_accesscard`;
CREATE TABLE `consumetally_disputeorder_operation_log` (
  `id` bigint NOT NULL COMMENT '主键ID',
  PRIMARY KEY (`id`)
) COMMENT='争议数据操作日志表';
CREATE INDEX test USING BTREE ON hly_accesscard.accesscard_channel_task (req_url);
```

第 3 条 `CREATE INDEX ... ON accesscard_channel_task (req_url)` 操作的是 170 万行大表。

### 当前漏洞

| 检测项 | 老逻辑 | CREATE INDEX 表现 |
|--------|--------|------------------|
| 大表 alert (detail.html) | 只识别 `ALTER TABLE` | ❌ 170 万行表没告警 |
| gh-ost 预检 | 只识别 `ALTER TABLE` | ❌ 业务方无 gh-ost 选项 |
| 字段 diff 弹窗 | 只识别 `ALTER TABLE` | ❌ 索引列风险不展示 |
| 镜像工单 (ddl_sync) | 只识别 `ALTER TABLE` | ❌ 镜像工单不触发 |
| 混合 DDL 检测 (v1) | 把 `CREATE` 全归非 ALTER | ❌ "请拆分工单" 误报 |

**业务风险**：170 万行表加索引会锁表 5-10 分钟，DBA 审核时**没看到**风险提示，工单走到"立即执行"路径才卡死。

### 修复方案

`CREATE INDEX` 在 MySQL 内部等价于 `ALTER TABLE ADD INDEX`：
- 都是 In-place 操作的 DDL
- 都会触发 online DDL 锁表（在大表上）
- 都可以走 gh-ost 模式

所以应该跟 `ALTER TABLE ADD/DROP INDEX` 走同一路径。

## 实施 (4 文件 + 1 演练脚本)

### 1. `sql/views.py` (detail 页大表 alert + 字段 diff + 混合 DDL 检测)

#### 1.1 `_parse_first_alter` 改 regex

```python
# 老 regex 只识别 ALTER TABLE
m = re.match(
    r"^\s*ALTER\s+TABLE\s+`?(?P<schema>`?[^`\s.()]+`?\.)?`?(?P<table>[^`\s(]+)`?",
    cleaned,
    re.IGNORECASE,
)

# 新增 CREATE INDEX 走单独 regex (跳过 idx_name + USING, 抓 ON 后面 table)
m = re.match(
    r"^\s*ALTER\s+TABLE\s+`?(?P<schema>`?[^`\s.()]+`?\.)?`?(?P<table>[^`\s(]+)`?",
    cleaned,
    re.IGNORECASE,
)
if not m:
    m = re.match(
        r"^\s*CREATE\s+(?:UNIQUE\s+|FULLTEXT\s+|SPATIAL\s+)?INDEX\s+`?[^`\s]+`?\s+"
        r"(?:USING\s+\w+\s+)?ON\s+"
        r"`?(?P<schema>`?[^`\s.()]+`?\.)?`?(?P<table>[^`\s(]+)`?",
        cleaned,
        re.IGNORECASE,
    )
# 修: schema 段 rstrip(".") 去掉尾点 (regex 抓 `\.` 时带)
schema = (m.group("schema") or "").rstrip(".").strip("`")
```

#### 1.2 `_parse_all_alters` 同样改 (扫所有 ALTER/CREATE INDEX)

#### 1.3 `_detect_non_alter` 改 (CREATE INDEX 不归 CREATE)

```python
if first_word == "CREATE":
    # DBA-bug-10: CREATE INDEX 等价 ALTER, 不归 CREATE 类
    if re.match(r"^\s*CREATE\s+(?:UNIQUE\s+|FULLTEXT\s+|SPATIAL\s+)?INDEX\b",
                cleaned, re.IGNORECASE):
        continue  # 跳过, 不归入 non_alter
    result.append({"stmt_type": "CREATE", ...})
```

#### 1.4 `_check_mixed_ddl` 同样改 (CREATE INDEX 归 ALTER 类)

```python
elif first_word == "CREATE":
    if _re.match(r"^\s*CREATE\s+(?:UNIQUE\s+|FULLTEXT\s+|SPATIAL\s+)?INDEX\b",
                 cleaned, _re.IGNORECASE):
        types_seen.add("ALTER")  # 归 ALTER
    else:
        types_seen.add("CREATE")
```

### 2. `sql/extensions/ddl_gh_ost/views.py` (gh-ost 预检)

#### 2.1 加 `_FIRST_CREATE_INDEX_RE`

```python
_FIRST_CREATE_INDEX_RE = re.compile(
    r"^\s*CREATE\s+(?:UNIQUE\s+|FULLTEXT\s+|SPATIAL\s+)?INDEX\s+`?[^`\s]+`?\s+"
    r"(?:USING\s+\w+\s+)?ON\s+"
    r"`?(?P<schema>[^`\s.()]+(?:\.`?[^`\s.()]+`?)?`?\.)?`?"
    r"(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,
)
```

#### 2.2 `_FIRST_ALTER_RE` 保持只识别 ALTER TABLE（保持分工）

#### 2.3 `_parse_all_statements` 改造 (CREATE INDEX 走 ALTER 类)

```python
# 先试 ALTER TABLE
m = _FIRST_ALTER_RE.match(cleaned)
if m:
    # ... 归 ALTER 类
# 再试 CREATE INDEX (DBA-bug-10 新增)
m = _FIRST_CREATE_INDEX_RE.match(cleaned)
if m:
    # ... 归 ALTER 类
```

### 3. `sql/extensions/ddl_sync/services/sync_trigger.py` (镜像工单)

#### 3.1 加 `_CREATE_INDEX_PATTERN`

#### 3.2 `_extract_all_alters` 改造

```python
m = _ALTER_PATTERN.match(cleaned)
if not m:
    m = _CREATE_INDEX_PATTERN.match(cleaned)  # DBA-bug-10
if not m:
    continue
```

### 4. `sql/templates/sqlsubmit.html` (字段 diff 弹窗触发)

#### 4.1 `fetchColumnDiff` 触发条件

```js
// 老: 只识别 ALTER TABLE
if (!/\bALTER\s+TABLE\b/i.test(sqlContent || "")) { ... }

// 新: 兼容 CREATE INDEX
if (!/\b(?:ALTER\s+TABLE|CREATE\s+(?:UNIQUE\s+|FULLTEXT\s+|SPATIAL\s+)?INDEX)\b/i.test(sqlContent || "")) { ... }
```

## 演练 (134 dev + 110 prod 双向 PASS)

**脚本**：`scripts/_w3_dba_bug10_verify.py` (10 个 case)

| Case | 输入 | 期望 | 134 dev | 110 prod |
|------|------|------|---------|----------|
| 1 | 单 CREATE INDEX w/ USING BTREE | table/db 都解 | ✅ | ✅ |
| 2 | 反引号 schema `CREATE INDEX \`idx_x\` ON \`hly_billing\`.\`consume_flow\`` | table=consume_flow, db=hly_billing | ✅ | ✅ |
| 3 | CREATE UNIQUE INDEX | table 解, non_alter=0 | ✅ | ✅ |
| 4 | CREATE FULLTEXT INDEX | table 解, non_alter=0 | ✅ | ✅ |
| 5 | CREATE TABLE (不变) | 仍归 CREATE 类, non_alter=1 | ✅ | ✅ |
| 6 | 混合 ALTER + CREATE INDEX | mixed_ddl ok=True, all_alters=2 | ✅ | ✅ |
| 7 | 混合 CREATE TABLE + CREATE INDEX | mixed_ddl ok=False (CREATE INDEX 归 ALTER) | ✅ | ✅ |
| 8 | wf#4849 实战工单 (use + CREATE TABLE + CREATE INDEX) | all_alters=1, non_alter=1 (CREATE TABLE) | ✅ | ✅ |
| 9 | wf#4841 实战 4 ALTER + CREATE INDEX | all_alters=2 | ✅ | ✅ |
| 10 | CREATE INDEX 不带 USING | table/db 都解 | ✅ | ✅ |

## 部署 (DBA 一条龙, 不动生产任何数据和表结构)

### 134 dev (9/17 17:30)
- 推 4 文件 + 1 演练脚本
- `systemctl restart archery-prod-gunicorn.service` (业务中断 ~10 秒)
- HTTP 200 + 10/10 PASS ✅

### 110 prod (9/17 17:38)
- 推 4 文件 + 1 演练脚本
- pkill gunicorn + 用 `--daemon --pid /tmp/gunicorn_110.pid` 重启 (systemd 仍然 failed)
- source `.env` + export CAS_SERVER_URL 等 7 个占位 env vars
- HTTP 200 + 10/10 PASS ✅

## 实战新发现 (跨项目可复用)

### 1. CREATE INDEX 等价 ALTER TABLE ADD INDEX (跨项目 SQL 语法)
跨项目写 SQL 平台/审核系统/工作流系统时, 必须知道 MySQL 里：
- `CREATE INDEX idx_name ON tbl (col)` ⇔ `ALTER TABLE tbl ADD INDEX idx_name (col)`
- `CREATE UNIQUE INDEX idx_name ON tbl (col)` ⇔ `ALTER TABLE tbl ADD UNIQUE INDEX idx_name (col)`
- `CREATE FULLTEXT INDEX idx_name ON tbl (col)` ⇔ `ALTER TABLE tbl ADD FULLTEXT INDEX idx_name (col)`

修法: 检测/解析/审核 ALTER 类时, 必须同时识别 CREATE INDEX 类语法糖, 否则业务方用 CREATE INDEX 绕过 ALTER 检测 (大表 alert / 锁表检测 / gh-ost 检测 / 字段 diff / 镜像工单)。

### 2. ALTER TABLE / CREATE INDEX 分 2 个 regex (跨项目 regex 实战)
不能合并到 1 个 regex:
- ALTER TABLE 后面直接是 table_name
- CREATE INDEX 后面是 idx_name, 然后 USING [type] (可选), 然后 ON table_name
- 语法结构差异, 合并 regex 复杂且难维护
- 实战踩坑: 9/17 试过合并 `ALTER\s+TABLE|CREATE\s+(?:UNIQUE\s+...)?INDEX`, 结果 CREATE INDEX 的 table 抓成 idx_name (索引名)
- 修法: 2 个独立 regex, 第一个 match ALTER 失败再试第二个, table 抓取逻辑更清晰

### 3. schema 段 regex 必加 rstrip(".") (跨项目 regex 实战)
ALTER TABLE / CREATE INDEX regex 里 schema 段是 `(?P<schema>\`?[^`\s.()]+\`?\.)?`, 抓 schema + 尾点。
实战踩坑: 9/17 修完没加 rstrip, db 字段是 "hly_accesscard." 多尾点, 查表大小走 `instance.host + .hly_accesscard..table` 错路径。
修法: `schema = (m.group("schema") or "").rstrip(".").strip("\`")` 跟 ddl_gh_ost / ddl_sync 现有逻辑一致。

### 4. 详情页 big_table_alert 用 _parse_all_alters (DBA-bug-9.5 实战)
跨项目 detail 页大表 alert, 必扫**所有** ALTER/CREATE INDEX, 不是只第一条:
- 老逻辑 `_parse_first_alter` 只返第一条 statement 的 ALTER
- 实战踩坑: 9/17 wf#4849 工单首条是 CREATE TABLE, 返 None, big_table_alert=None
- 修法: views.py:594 已经用 `_parse_all_alters` 扫所有 ALTER (DBA-bug-9.5 9/16 实战改的)
- 我加了 CREATE INDEX 识别后, _parse_all_alters 自动含 CREATE INDEX 目标表, big_table_alert 自动触发

### 5. SQL 检测弹窗触发条件必含 CREATE INDEX (跨项目 UX)
跨项目 SQL 审核弹窗 (字段 diff / 风险评估) 触发条件:
- 老: `if (!/\bALTER\s+TABLE\b/i.test(sqlContent))` 静默
- 实战踩坑: 9/17 wf#4849 业务方提交 CREATE INDEX, 字段 diff 弹窗不触发, 业务方看不到索引列风险
- 修法: 触发条件加 `CREATE\s+(?:UNIQUE|FULLTEXT|SPATIAL)?\s+INDEX`, 字段 diff / 风险评估都触发

### 6. 跨文件 regex 同步 (实战新发现, 9/17 实战接龙持续)
跨项目 regex 改一个文件必 grep 全代码库找同款:
- 9/12 DBA-bug-5a 改过 4 个 _ALTER_PATTERN 文件, 同步一致
- 9/17 DBA-bug-10 改 4 个文件 (sql/views.py + ddl_gh_ost/views.py + ddl_sync/sync_trigger.py + sqlsubmit.html), 全部一起改
- 实战新发现: 跨项目多文件 regex 一致性, 改一个 regex 必 grep 全代码库找同款, 漏 1 个就出 bug

## commit

```bash
# M: sql/views.py (+26 lines, _parse_first_alter / _parse_all_alters / _detect_non_alter / _check_mixed_ddl)
# M: sql/extensions/ddl_gh_ost/views.py (+19 lines, _FIRST_CREATE_INDEX_RE + _parse_all_statements CREATE INDEX 路径)
# M: sql/extensions/ddl_sync/services/sync_trigger.py (+9 lines, _CREATE_INDEX_PATTERN + _extract_all_alters)
# M: sql/templates/sqlsubmit.html (+5 lines, fetchColumnDiff 触发条件兼容 CREATE INDEX)
# A: scripts/_w3_dba_bug10_verify.py (10 case 演练脚本)
# A: docs/changelogs/2026-09-17_dba-bug-10-create-index-bypass-alter-check.md (本文件)
```