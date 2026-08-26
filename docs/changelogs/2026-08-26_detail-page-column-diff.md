# 2026-08-26 detail 页字段 diff inline 区域 新功能

**类型**: feat (业务 RD 审核/执行阶段新功能)
**严重度**: 中 (业务 RD 提单后 detail 页审核阶段无字段 diff 区域, 不影响功能)
**修复时间**: 2026-08-26 21:13-21:28 (15min 改 + 演练)
**commit**: 待补 (本次 commit)

---

## 业务需求

**alter 变更不管表大小, 都属于业务高风险操作, 提交 / 审核 / 执行 三个阶段都要有字段 diff.**

8/12 v0.3.x 字段 diff 设计只覆盖了:
- **提交检测 (sqlsubmit.html)**: SQL 检测成功后自动弹 modal 一次 ✓
- **审核/执行 (detail.html)**: 只在大表 DDL 时显示"字段 diff"按钮 (DBA 兜底, 弹 modal) — **小表 ALTER 字段变更工单没地方重看**

8/26 21:11 业务 RD mkq 业务工单 4746 反馈: 工单 detail 页没字段 diff 区域, 提单时 modal 一次看过但 detail 页审核/执行时想重看, 没地方.

---

## 修法

**detail.html 加 inline 字段 diff 区域**, 所有 ALTER 字段变更工单自动触发 AJAX 调端点, 渲染到 inline 区域 (8 维 + 11 风险点).

### 改动 1: HTML inline 区域 (sql/templates/detail.html line 617+)

```html
{# CUSTOM-MODIFIED: 8/26 detail 页字段 diff inline 区域 @ 2026-08-26 @ mavis #}
{# 不删 modal + 按钮, 保留 DBA 兜底; inline 区域给业务 RD 审核/执行时看. #}
<div id="column-diff-result" style="display:none; margin-top:14px;"></div>
```

放在 `{% endblock content %}` 之前, 跟原 8/24 modal 区域并列.

### 改动 2: JS 函数 (sql/templates/detail.html {% block js %} 末尾)

复用 sqlsubmit.html 8/12 同样 3 个函数:
- `fetchColumnDiff(sqlContent, instanceId, dbName)` — AJAX 调 `/gh_ost/column_diff/` 端点
- `renderColumnDiff(data)` — 渲染数据到 `#column-diff-result` inline 区域
- `escapeHtml(s)` — XSS 转义
- `copyColumnDiffFix(btn)` — 一键复制补全 SQL

### 改动 3: 自动触发 (detail.html {% block js %} 末尾 `$(document).ready`)

```javascript
$(document).ready(function() {
    var sqlContent = {{ workflow_detail.sql_workflow_content|default:""|escapejs|default:"''" }};
    var instanceId = {{ workflow_detail.instance_id|default:0 }};
    var dbName = {{ workflow_detail.db_name|default:""|escapejs|default:"''" }};
    fetchColumnDiff(sqlContent, instanceId, dbName);
});
```

`fetchColumnDiff` 内部判断 `\bALTER\s+TABLE\b` 正则, 命中才发请求, 非 ALTER 静默不显示.

### 改动 4: 保留 8/12 modal + 8/24 fix

- **不删 8/12 modal 元素** (line 599 `<div class="modal fade" id="columnDiffModal">`)
- **不删 8/24 modal 移 content block 内 fix** (0b62856)
- **不删大表 DDL "字段 diff" 按钮** (line 388, DBA 兜底弹 modal 重看)

3 个新功能 (inline 区域 + 自动触发 + 函数) **叠加** 在 8/12 + 8/24 之上, 不破坏现有功能.

---

## 134 dev 演练 (8/26 21:28)

```python
# 找最近 ALTER TABLE 工单 + force_login archery 渲染 detail/<id>/
- 24 个 ALTER TABLE 工单找到
- 工单 103 (accesscard_black_detail MODIFY COLUMN test4) HTTP 200
- column-diff-result 出现 3 次 (HTML 1 + JS 2)
- fetchColumnDiff 出现 2 次, renderColumnDiff 5 次, escapeHtml 21 次
- inline 区域 div 正确渲染
```

`fetchColumnDiff` AJAX 调端点 → 端点返 ok=True + data → `renderColumnDiff` 渲染到 inline 区域 → 业务 RD 看到 8 维 + 11 风险点 + 修复建议.

---

## 8/26 推 110 范围更新

原计划 (commit `1d4fbf6` 范围瘦身): detail.html 4 fix 跟着推 (8/24 0b62856 modal 移 content block 内).

**新增 1 个 commit**: detail.html 加 inline 字段 diff 区域 (8/26 21:13-21:28, 15min).

**8/26 推 110 总物料**:
- 1 detail.html (新功能 + 8/24 4 fix 集成)
- 1 changelog (本次)
- 5 步必做 idempotent 调整 (detail.html 跟着推 110, 5 步必做脚本 idempotent 检查)
- 110 prod 推代码 + kill gunicorn + nohup 拉新

---

## 教训 (跨项目可复用, 3 条)

1. **DBA 设计 vs 业务 RD 实际使用场景有 gap** — 8/12 v0.3.x 字段 diff 设计是"提单时弹 modal + 大表 DDL 显示按钮", 但业务 RD 期望"detail 页所有 ALTER 工单都看得到字段 diff". 8/26 实战暴露 8/12 设计 gap, 业务 RD 评审会上确认真实需求
2. **5+1 端点验证漏 detail 页实际业务流** — 8/26 推 110 5+1 端点走的是 /gh_ost/rebuild/select/ 跟 /detail/<id>/, 但没真登业务 RD 走 detail 页字段 diff 区域. 推 prod 业务流验证必走"业务 RD 浏览器实际场景" (不是 DBA 演练脚本)
3. **detail 页字段 diff inline 区域跟 modal 并存** — 不删 8/12 modal 元素 + 8/24 fix, 新 inline 区域叠加. 业务 RD 审核/执行看 inline, DBA 兜底可点大表 DDL 按钮弹 modal 重看

---

## 关联

- 上一份 changelog: `2026-08-26_push110-ghost-precheck-dev-fallback-bug.md` (K3 CUSTOM_GH_OST_PRECHECK_*)
- 8/12 v0.3.x 字段 diff 原始设计: `docs/changelogs/2026-08-12_gh-ost-column-diff.md`
- 8/24 modal 移 content block 内 fix: `docs/changelogs/2026-08-24_column-diff-modal-template.md`
- sqlsubmit.html 8/12 inline 字段 diff 实现参考: `sql/templates/sqlsubmit.html:155` (column-diff-result div) + `sql/templates/sqlsubmit.html:679-820` (fetchColumnDiff + renderColumnDiff + escapeHtml)
- 后端端点: `POST /gh_ost/column_diff/` (`sql/extensions/ddl_gh_ost/views.py:1357` views.column_diff)
