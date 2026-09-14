# DBA-bug-5a: DDL 跨库同步 sync_trigger.py regex 漏反引号 schema → 黑名单 miss → 镜像工单误生成

> **DBA 实战**: 阿达叔叔 9/12 10:50 在 110 prod 反馈 wf#4808 (DDL 跨库同步镜像工单, 目标 = history 变更 / hly_billing) 业务方点 "启用 gh-ost" 弹 "预检失败: 未通过: table_type (1/5 失败)"。
>
> 9/12 11:25 阿达叔叔确认 "历史库同步表已经配置了, 这张表是在黑名单里" → 意味着**镜像工单不该生成**,但实际生成了 → DDL 跨库同步机制有 bug。
>
> 9/12 11:30-11:35 排查 `_wf4808_blacklist_110.py` + `_wf4808_inspect_110.py` 推 110 prod 跑, 锁定根因。

## 现象

- **触发工单**: 业务方实战 wf#4806 (源 = etc 变更 / hly_billing, 5,238,005 行 / 3,482.4 MB 大表) → 触发 DDL 跨库同步生成镜像工单 wf#4808 (目标 = history 变更 / hly_billing)
- **业务方 SQL**: `ALTER TABLE \`hly_billing\`.\`consume_flow\` ADD INDEX \`idx_create_time\` (\`create_time\`) USING BTREE` (反引号 schema + 反引号 table)
- **现状 (DBA-bug-2 修后, 9/11 18:50)**:
  - wf#4808 镜像工单已生成 + 已审核通过 (马克群 9/12 10:50 审核通过)
  - 业务方点 "启用 gh-ost" → precheck 端点 (9/11 修过的 views.py `_FIRST_ALTER_RE`) 正确解析出 'consume_flow' → 查历史库 → 找不到 → 1/5 失败
  - 弹窗只显示 "预检失败: 未通过: table_type (1/5 失败)", 业务方看不到具体哪一项失败

## 根因 (跟 DBA-bug-2 同款坑, 第 3 个文件漏修)

### 主因: sync_trigger.py `_ALTER_PATTERN` regex 不支持反引号 schema

**位置**: `sql/extensions/ddl_sync/services/sync_trigger.py:57-60`

```python
# 错的 (sync_trigger.py 当前)
_ALTER_PATTERN = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?",
    re.IGNORECASE,
)
```

**实战解析** (本地 regex 验证脚本 `_sync_trigger_regex_test.py`):

| 业务方 SQL | schema 解析 | table 解析 | 对不对 |
|------------|-------------|------------|--------|
| `` ALTER TABLE `hly_billing`.`consume_flow` ADD INDEX... `` (反引号) | None | `'hly_billing'` | ❌ 错 |
| `ALTER TABLE hly_billing.consume_flow ADD INDEX...` (无反引号) | `'hly_billing'` | `'consume_flow'` | ✅ 对 |
| `` ALTER TABLE `consume_flow` ADD INDEX... `` (只 table 反引号) | None | `'consume_flow'` | ✅ 对 |
| `ALTER TABLE consume_flow ADD INDEX...` (只 table 无反引号) | None | `'consume_flow'` | ✅ 对 |

**根因**: `(?P<schema>[^`\s.()]+)\.` 段**不识别反引号 schema**。当 schema 是反引号写法时, regex 跳过 schema 段, 让 `[^`\s(]+` 贪婪匹配到第一个空白, 吃掉了 `` `hly_billing` `` 整段。

**对比 9/11 DBA-bug-2 修的 `sql/extensions/ddl_gh_ost/views.py:72-76`**:

```python
# views.py (DBA-bug-2 修后)
_FIRST_ALTER_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+`?(?P<schema>[^`\s.()]+(?:\.`?[^`\s.()]+`?)?`?\.)?`?"
    r"(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,
)
```

views.py 用了 `(?:\.`?[^`\s.()]+`?)?` 段让 schema 段能识别反引号, sync_trigger.py **漏了**这段。

### 110 prod 数据库实证 (scripts/_wf4808_blacklist_110.py)

```
DdlSyncPair id=2 sync_mode=blacklist enabled=True
  source=prod core for etc变更/hly_billing → target=prod core for history 变更/hly_billing
  黑名单 7 张 + 白名单 99 张
  consume_flow: in_blacklist=True ✅  (黑名单里**有**)
DdlSyncHistory id=4 (wf#4806 → wf#4808):
  table_name='hly_billing' ❌  (应该是 'consume_flow', regex 错返 schema 名)
  sync_status='syncing'    (应该是 'skipped', 黑名单 miss)
  target_wf=4808           (镜像工单误生成)
```

## 实战调用链 (根因 → 现象)

1. 业务方在 etc 变更提 wf#4806: `` ALTER TABLE `hly_billing`.`consume_flow` ADD INDEX `` (反引号 schema)
2. sync_trigger.py `workflow_passed_handler` signal 触发 → `_extract_table_name` 错返 `'hly_billing'` (不是 `'consume_flow'`)
3. `_should_sync(pair, 'hly_billing')` → `DdlSyncTable(pair, table_name='hly_billing', sync_type='blacklist').exists() == False` (黑名单里是 `'consume_flow'` 不是 `'hly_billing'`)
4. `_should_sync` 返 True → 走 `create_target_workflow` 创建镜像工单 wf#4808
5. 镜像工单 SQL 是原 SQL `` ALTER TABLE `hly_billing`.`consume_flow` ADD INDEX ``
6. 业务方审过 wf#4808 → 点 "启用 gh-ost" → precheck 端点用 views.py._parse_first_alter (9/11 修过的) 正确解析 `'consume_flow'`
7. `check_table_type` 查历史库 `hly_billing.consume_flow` → 不存在 → 1/5 失败

## 修法

**改 1 个 regex (跟 9/11 DBA-bug-2 同款), 跟 views.py 对齐**:

```python
# sql/extensions/ddl_sync/services/sync_trigger.py:57-60
# 修后 (跟 views.py _FIRST_ALTER_RE 对齐)
import re  # 顶部已经 import 了
_ALTER_PATTERN = re.compile(
    r"^\s*ALTER\s+TABLE\s+`?(?P<schema>[^`\s.()]+(?:\.`?[^`\s.()]+`?)?`?\.)?`?"
    r"(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,  # 9/11 实战加 DOTALL 防多行漏匹配
)
```

**配套加 4 个单元测试 case** (跟 9/11 DBA-bug-2 实战新发现 checklist 一致):
1. `` ALTER TABLE `hly_billing`.`consume_flow` ADD INDEX... `` (反引号 schema + table) → schema=`hly_billing`, table=`consume_flow`
2. `ALTER TABLE hly_billing.consume_flow ADD INDEX...` (无反引号 schema + table) → schema=`hly_billing`, table=`consume_flow`
3. `` ALTER TABLE `consume_flow` ADD INDEX... `` (只 table 反引号) → table=`consume_flow`
4. `use hly_billing;\n-- 注释\nALTER TABLE hly_billing.consume_flow ADD INDEX...` (use + 注释前缀) → schema=`hly_billing`, table=`consume_flow` (跟 DBA-bug-1 实战补)

## 验证

### 134 dev

- 单元测试 (scripts/_dba_bug5a_unit_test_134.py): 4 个新 case + 老的 (无 schema 等) 全 PASS
- 演练 (scripts/_dba_bug5a_drill_134.sh): 造一个反引号 schema 工单走 sync_trigger, 验证 DdlSyncHistory 标 skipped, 镜像工单不生成

### 110 prod

- 推完 sync_trigger.py + kill -TERM workers (9/11 实战 reload 法)
- 演练: 触发 wf#4806 的 signal handler (或重建一个工单) 验证黑名单生效
- 业务方回归: wf#4808 已审核通过, 业务方去取消 gh-ost 启用 + 终止流程 (DBA 兜底)

## 同源 entry (DBA-bug-1/2/3/3-hotfix/4/5 + 5a)

- 9/11 17:55 DBA-bug-1: views.py `_parse_first_alter` 改 use/注释预处理 + 状态放宽 + detail.html alert 位置
- 9/11 18:50 DBA-bug-2: views.py regex 改支持反引号 + column_diff.py 对齐 + sqlsubmit.html banner
- 9/11 19:30 DBA-bug-3: column_diff.py `_diff_single_table` 0/0.5 步保留 big_table_alert + sqlsubmit.html
- 9/11 20:10 DBA-bug-3 hotfix: Django 跨行 `{# #}` 改 `//` JS 注释
- 9/12 10:50 DBA-bug-4: DDL 跨库业务方选错库大表 alert 不触发 (用户操作, 软提示)
- 9/12 10:55 DBA-bug-5: DDL 跨库镜像工单目标库表不存在 (业务预期, 软提示, 跟 DBA-bug-5a 一起实战)
- **9/12 11:35 DBA-bug-5a: sync_trigger.py regex 漏反引号 schema 黑名单 miss 镜像工单误生成 (本次必修)**

## 实战新发现 (跨项目可复用)

- **regex 跨文件一致性, 漏修第三个文件实战踩坑** (DBA-bug-5a 实战新发现) - 9/11 DBA-bug-2 修 regex 一致性时只对齐了 2 个文件 (views.py + column_diff.py), 漏了第 3 个文件 `sql/extensions/ddl_sync/services/sync_trigger.py:57-60`. 实战踩坑: 9/12 wf#4806 业务方反引号 SQL, sync_trigger.py regex 错返 schema 名当 table 名, 黑名单 miss 走镜像工单创建, 业务方在历史库走 gh-ost 预检发现目标表不存在.
- 修法: 改一个 regex 修一个 bug 时, **必 grep 全代码库找同款 regex 写法** (例: `re.compile.*ALTER.*TABLE.*schema` 一搜就出来), 别只看当前文件
- 跨项目 **regex 一致性 checklist 必加 1 条**: `grep -rn "re.compile.*ALTER.*TABLE" .` 每次改 regex 前必跑一次, 看有几个文件, 全对齐
