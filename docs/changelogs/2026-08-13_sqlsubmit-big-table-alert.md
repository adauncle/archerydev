# 2026-08-13 SQL 提交页大表 DDL 防呆 (开发提交时就能看到)

## 业务背景

8/13 用户反馈: 开发选中 gh-ost 走流程, 提交 SQL 后审批通过到 DBA 执行阶段才提示"大表 DDL"。
开发在**提交阶段**不知道自己提交的 SQL 是大表 DDL, 等审批通过后 DBA 才发现, 流程被动。

期望: SQL 提交页 `/sqlsubmit/` 开发点"SQL检测"时就该看到大表 DDL 警告, 引导开发
      **主动勾选"启用 gh-ost 无锁变更"**, 不要等 DBA 在执行阶段兜底。

## 修法

### 修法 1: `column_diff` 端点返回 `big_table_alert` 字段

`sql/extensions/ddl_gh_ost/services/column_diff.py` — 字段 diff 端点本来就要查
`information_schema.columns` 拿当前列定义, 顺手查 `information_schema.tables` 拿行数 + 大小:

```python
def _fetch_table_size(instance, db_name, table_name) -> dict:
    """查 information_schema.tables 拿行数 + 大小 (复用 views._get_table_size_info 实现)"""
    # SELECT TABLE_ROWS, DATA_LENGTH + INDEX_LENGTH FROM information_schema.tables
    #   WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s

def _build_big_table_alert(size_info: dict) -> dict:
    """拼 alert dict (跟 detail.html big_table_alert 同一字段 + 同一阈值)"""
    # 阈值读 settings.CUSTOM_BIG_TABLE_ROW_THRESHOLD / _SIZE_THRESHOLD_MB
    # 大于等于阈值返 dict, 否则返 None
```

`column_diff_full()` 返回结构加 `big_table_alert: dict | None` 字段:

```python
return {
    "ok": True,
    "table_name": table_name,
    "columns": columns_diff,
    "high_risk_count": high_risk,
    "mid_risk_count": mid_risk,
    "low_risk_count": low_risk,
    "summary": summary,
    "big_table_alert": big_table_alert,  # NEW
}
```

### 修法 2: `sqlsubmit.html` 渲染大表 DDL 提示

`sql/templates/sqlsubmit.html` — `renderColumnDiff(data)` 函数:

```javascript
// 在拼 html 之前先拼大表 alert HTML (放字段 diff 上方)
var bigTableAlertHtml = "";
if (data.big_table_alert) {
    var bta = data.big_table_alert;
    bigTableAlertHtml =
        '<div class="alert" id="sqlsubmit-big-table-alert" ' +
             'style="background:rgba(176, 99, 103, 0.06);border:1px solid #b06367;...">' +
            '<strong style="font-size:15px;">⚠️ 检测到 <code>...</code> 是大表 DDL</strong>' +
            '<div>行数 ... / 数据大小 ... MB (阈值 ... 行 或 ... MB)</div>' +
            '<div>大表 DDL 走原路径"立即执行"会<strong>锁表</strong>... ' +
                 '<strong>强烈建议在上方勾选"启用 gh-ost 无锁变更"</strong>...</div>' +
        '</div>';
}

var html = bigTableAlertHtml + '<div ...>字段变更检测...</div>...';
```

样式跟详情页大表 alert 一致 (浅米色 + 暗红边框 + ⚠️ 图标)。

### 复用 vs 重复

- `_get_table_size_info` (sql/views.py:267) 实现**完全相同**的查表逻辑
- 选择**复制**到 column_diff.py 而不是 import, 避免:
  1. 循环 import (column_diff 被 views 引用, 反向 import 可能麻烦)
  2. 服务模块依赖 Django 视图模块的设计耦合
- 逻辑都是 12 行 PyMySQL + try/except, 复制零风险
- 业务端代码 (drill) 同时验证两个入口, 防止一方失效

## 演练 (134 dev 6 Case + 真实 MySQL)

`scripts/drill_sqlsubmit_big_table.py` — instance=2 (测试 MySQL 8.0) + db=archery_dev, 真实查表

| Case | 场景 | 期望 | 实际 |
|------|------|------|------|
| A. 大表 | accesscard_black_detail 238310 行 / 134.3 MB | size_info 存在, alert 触发 | rows=238310 size=134.3MB, alert 触发 ✓ |
| B. 小表 | accesscard_test_diff 2 行 | size_info 存在, alert=None | rows=2, alert=None ✓ |
| C. 端点 service 大表 | `column_diff_full()` 大表 ALTER | 返回里 big_table_alert 是 dict | dict 含 table_name/rows/size_mb/threshold ✓ |
| D. 端点 service 小表 | `column_diff_full()` 小表 ALTER | 返回里 big_table_alert 是 None | None ✓ |
| E. 端点 HTTP | `POST /gh_ost/column_diff/` | status=200, body 含 alert | status=200, body.alert 完整 ✓ |
| F. 模板渲染 | sqlsubmit.html 含关键代码 | 5/5 关键检查通过 | 全通过 ✓ |

## 验证清单

- [x] 134 dev 6 Case drill 全过 (真实 MySQL, 大表+小表+端点+HTTP+模板全覆盖)
- [x] gunicorn reload 后代码生效
- [ ] **用户浏览器手动验收**: 用 oa_tester_1 登录 134 dev 9003, 进 `/sqlsubmit/` 输一个对 accesscard_black_detail 的 ALTER TABLE, 点"SQL检测", 应该看到大表 DDL 警告 + 字段 diff

## 同源 entry

- 8/11 commit `f87e875` (v0.3.0-beta DBA 兜底 + 大表 DDL 防呆) — 详情页
- 8/12 commit `1f32976` (v0.3.x 字段 diff 检测) — 字段 diff 端点初版
- 8/12 commit `fba0564` (字段 diff 补全 SQL 一键复制)
- 8/13 commit `36eb885` (字段 diff 弹窗调大字号)
- **本次 commit** 把大表 DDL 防呆从详情页扩展到 SQL 提交页
