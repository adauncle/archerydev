# DBA-bug-2: views.py regex 不支持反引号 schema + SQL 上线页大表 alert 没在主页面 banner

> **DBA 实战**: 阿达叔叔 9/11 18:00 在 110 prod `/submitsql/` 提交 `ALTER TABLE \`hly_billing\`.\`consume_flow\` ADD INDEX ...` 业务方工单(consume_flow 5M+ 行 / 3.4 GB 大表),点 "SQL 检测" 后**没看到大表 DDL 警告**,modify column 也没看到字段 diff 弹窗。
>
> 同一工单接着改 modify column 提交,同样**没看到大表提示和字段 diff**。
>
> 阿达叔叔说"DDL 变更检测没有大表提示, 字段 diff 也没有展示"。

## 现象

- **触发工单**: 业务方实战 consume_flow 表 (5,238,005 行 / 3,482.4 MB) 工单
- **现状 (DBA-bug-1 修后, 9/11 17:55)**:
  - detail.html 大表 alert: 这次是 SQL 上线页 (/submitsql/) 提交阶段, 走的是 /gh_ost/column_diff/ 端点, 不是 detail.html
  - views.py 的 `_parse_first_alter` regex 在 detail.html 渲染时也调用 (大表 alert 通过同一函数)
  - 但 SQL 上线页 (/submitsql/) 走 /gh_ost/column_diff/ 端点, 端点用 column_diff.py 的 regex (支持反引号)
  - **端点本身能返大表 alert (实测返了 rows=5238005, size_mb=3482.4)**
  - 但 sqlsubmit.html 的大表 alert 拼到 modal body 里, modal 自动弹但用户容易没注意
  - 字段 diff modal 弹出后用户可能没注意, 关掉就找不到入口

## 根因 3 处 (跟 DBA-bug-1 一样的 3 处类型)

### 根因 1: views.py regex 不支持反引号 schema (DBA-bug-1 漏了)

**位置**: `sql/views.py:258` (DBA-bug-1 改了 use/注释预处理, **没改 regex 本身**)

```python
# DBA-bug-1 改后 (line 258)
m = re.match(
    r"^\s*ALTER\s+TABLE\s+(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?",
    cleaned,
    re.IGNORECASE,
)
```

跟 `sql/extensions/ddl_gh_ost/services/column_diff.py:402-405` 的 regex 对比:

```python
# column_diff.py 早就有反引号支持
m = re.match(
    r"^\s*ALTER\s+TABLE\s+"
    r"(?:(?P<schema>`?[^`\s.()]+`?)\.)?`?(?P<table>[^`\s(]+)`?",
    ...
)
```

**DBA 实战踩坑**: 业务方 MySQL 客户端默认输出 `` `schema`.`table` `` 格式 (with backticks), views.py regex 之前是 `[^`\s.()]+` 不接受反引号, 解析时:
- input: `` ALTER TABLE `hly_billing`.`consume_flow` ADD INDEX ... ``
- expected: db=`hly_billing`, table=`consume_flow`
- actual: db=None, table=`hly_billing` (把 schema 当 table 解析, consume_flow 丢了)

→ 大表 alert 不触发, fields diff 端点也跟 view 不一致 (因为 column_diff.py 修过了)

### 根因 2: SQL 上线页大表 alert 只在 modal body, 没在主页面 banner (跟 DBA-bug-1 detail.html 同款)

**位置**: `sql/templates/sqlsubmit.html:770-792, 897`

```javascript
// sqlsubmit.html 拼 bigTableAlertHtml 拼到 modal body
var html = bigTableAlertHtml + ...;
$box.html(html);  // $box = $("#column-diff-modal-body")
$('#columnDiffModal').modal('show');
```

大表 alert **只在 modal 里显示**, modal 自动弹但用户容易没注意 (DBA 阿达叔叔实战就是没看到)。这是 UX 问题, 跟 detail.html 的 alert 在审核按钮下面同款 (DBA-bug-1 修过)。

### 根因 3: 字段 diff modal 弹窗 UX 弱

**位置**: `sql/templates/sqlsubmit.html:735`

```javascript
$('#columnDiffModal').modal('show');
```

modal 自动弹, 但用户提交 SQL 时主要在看编辑器和检测结果表格, modal 弹出来容易没注意。这不是 bug, 是 UX 弱, DBA-bug-2 通过把大表 alert 提到主页面 banner 解决 (字段 diff modal 弹不弹用户都不会漏掉大表 DDL 风险)。

## 修法 3 处

### 1. views.py `_parse_first_alter` regex 支持反引号 schema

```python
# OLD (DBA-bug-1 修后, 9/11 17:55)
m = re.match(
    r"^\s*ALTER\s+TABLE\s+(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?",
    cleaned,
    re.IGNORECASE,
)

# NEW (DBA-bug-2, 9/11 18:35)
# CUSTOM-MODIFIED: 9/11 DBA-bug-2 schema 段支持反引号 (跟 column_diff.py:402-405 保持一致)
m = re.match(
    r"^\s*ALTER\s+TABLE\s+(?:(?P<schema>`?[^`\s.()]+`?)\.)?`?(?P<table>[^`\s(]+)`?",
    cleaned,
    re.IGNORECASE,
)
```

### 2. sqlsubmit.html 主页面加 banner 大表 alert (跟 detail.html 风格一致)

```javascript
// sqlsubmit.html fetchColumnDiff success 回调里 (line 735 后新增)
$("#sqlsubmit-big-table-alert-banner").remove();  // 重复检测先清空
if (data.big_table_alert) {
    var bta = data.big_table_alert;
    var bannerHtml =
        '<div class="alert alert-danger" id="sqlsubmit-big-table-alert-banner" ' +
             'style="margin:12px 0;padding:14px 18px;border-left:4px solid #b06367;' +
                      'background:rgba(176, 99, 103, 0.06);">' +
            // ... ⚠️ 检测到 ... 是大表 DDL / 行数 ... / 数据大小 ... / 建议启用 gh-ost
        '</div>';
    $("#inception-result").after(bannerHtml);  // 插到检测结果表格后面
}
```

### 3. (跟 2 一起) 清空 banner 防止堆叠

`$("#sqlsubmit-big-table-alert-banner").remove()` 在 ok=False 和 new 检测前都调用, 避免重复 SQL 检测时 banner 堆叠。

## 验证

### 134 dev 单元测试 (`scripts/_dba_bug1_unit_test.py` 16/16 PASS, 9/11 18:36)

| 测试 | 期望 | 实际 |
|------|------|------|
| test_with_backtick_schema_drop_index | db=hly_billing table=consume_flow | ✅ |
| test_with_backtick_schema_modify_column | db=hly_billing table=consume_flow | ✅ |
| test_with_backtick_only_table | db=None table=user | ✅ |
| test_with_backtick_only_schema | db=hly_platform table=user | ✅ |
| test_regression_with_use_and_backtick_schema | db=hly_billing table=consume_flow | ✅ |
| (DBA-bug-1 老的 11 个测试) | (全 PASS) | ✅ |

### 110 prod 端点演练 (`scripts/_dba_bug2_drill_110.py`, 9/11 18:46)

| 工单 | 端点返 |
|------|--------|
| 图1 consume_flow ADD INDEX | `ok=True, table_name='consume_flow', big_table_alert={rows: 5238005, size_mb: 3482.4}` ✅ |
| 图2 consume_flow modify column | `ok=True, table_name='consume_flow', big_table_alert={rows: 5238005, size_mb: 3482.4}, high_risk=1, mid_risk=1` ✅ |
| 回归 waybill drop index | `ok=False` (预期, drop index 不算 MODIFY/ADD/DROP COLUMN) |

### 110 prod 老工单回归 (9/11 18:46)

- wf#4803: HTTP 200, 大表 alert 完整渲染 (行数 159660 / 大小 124.7 MB) ✅
- wf#4791: HTTP 200, alert=True ✅
- wf#4792: HTTP 200, alert=False ✅
- wf#4783: HTTP 200, alert=True ✅
- 所有老工单 0 个 500 错误 ✅

## 推 110 prod

- 134 dev 演练通过 → 推 views.py + sqlsubmit.html → md5 完全一致
- kill -TERM 老 workers (17:53 启动的 83802 + 18:05-18:10 4 个) → master 8694 自动拉新 workers 18:46 启动
- 真 HTTP 演练 → 老工单回归 → 0 个 500

## 实战新发现 (跨项目可复用, 2 条)

1. **跨项目 regex 一致性必对齐** (DBA-bug-2 实战新发现) - 跨项目写多个 regex 解析同一类输入 (例: ALTER TABLE schema.table), **必对齐格式** (反引号/不反引号都支持). 实战踩坑: 8/26 D15 引入 regex 时, column_diff.py:402-405 跟 views.py:258 各自写, 9/11 业务方实战才发现 views.py 漏支持反引号. 修法: 跨项目写多个 regex 解析同一类输入, **必抽 helper 函数统一**, 避免 N 处 regex 各写各的
2. **跨项目 alert 必在主页面 banner** (DBA-bug-2 实战新发现) - 跨项目写风险 alert, **不能塞到 modal 里依赖用户主动看** (用户提交表单时主要在编辑器 + 检测结果表格, modal 弹了没注意). 实战踩坑: 9/11 阿达叔叔 SQL 上线页 `/submitsql/` 大表 alert 拼到 modal body, modal 弹了用户没注意, **完全错过 5M+ 行大表 DDL 警告**. 修法: alert 必在主页面 banner (inception-result 下面), 跟 detail.html 大表 alert 风格一致. 跨项目推 alert 必演练真 HTTP 用 `assert "alert" in body[:len(body)//2]` 验证 alert 在主页面 (不是 modal 里)
