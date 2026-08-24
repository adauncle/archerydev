# 2026-08-24 字段 diff Modal 模板错误修复 (移到 content block 内)

## 摘要

修复 8/12 v0.3.x 字段 diff 功能因模板错误, 详情页点"字段 diff" 按钮**后端返 ok=True 但 modal 不显示**的问题。

## 根因

8/12 写 `sql/templates/detail.html` 时, `columnDiffModal` 元素放在 **`{% endblock content %}` 之后** (line 594 后):

```html
{% block content %}
    ... form ...
    </form>
{% endblock content %}  ← line 594

{# 这里 columnDiffModal (line 599)  #}
{# 在 endblock 之后, Django template 不渲染 #}
<div class="modal fade" id="columnDiffModal" ...>...</div>

{% block js %}  ← line 616
    ... JS 脚本 (含按钮 click handler + renderColumnDiffModal) ...
{% endblock %}
```

**Django template 行为**: `{% block %}` 之外的内容被忽略。所以 `columnDiffModal` HTML 元素**不会渲染到响应**。

**为什么用户看不到 modal**:
1. 按钮 `btn-big-table-column-diff` 在 `{% block content %}` 内, 正常渲染
2. JS 按钮 handler 在 `{% block js %}` 内, 正常注册
3. AJAX 调 `/gh_ost/column_diff/` 端点, 后端返 `ok=True` + diff 数据 (8/24 修法已生效)
4. `renderColumnDiffModal(data)` 执行, 但 `document.getElementById("columnDiffModal")` 是 `null`
5. `$("#columnDiffModal").modal("show")` 静默失败, modal 不显示
6. 用户看页面"没反应", 实际是 modal HTML 元素缺失

## 复现 (8/24 用户报, 第二次)

8/24 15:37 用户再报: "点击了还是没有显示变更差异" (第一次报 8/24 15:05 后, 修了 column_diff.py 后端, 但用户仍然看不到)

演练脚本 (`scripts/_archive/_drill_wf89_curl_20260824.py`) 用 Django test client 模拟浏览器请求, 看响应 HTML:
- 修前: `columnDiffModal 不存在!` 但 `btn-big-table-column-diff 存在` (button 显示但 modal 元素缺失)
- 后端 `/gh_ost/column_diff/` 返 `status=200, ok=True, columns=[test3 DROP mid risk]` (后端正常)

**判断**: 8/24 第一次修法 (column_diff.py 兼容 use 前缀) 是正确的, 但**模板错误**导致 modal 不显示。

## 修法

`sql/templates/detail.html:594-614`:

把 `columnDiffModal` 元素从 `{% endblock content %}` 之后**移到 content block 内**, 在 form 关闭后 `{% endblock %}` 之前:

```html
    </form>

    {# CUSTOM-MODIFIED: 8/24 字段 diff Modal 移到 content block 内 @ 2026-08-24 @ mavis #}
    <div class="modal fade" id="columnDiffModal" tabindex="-1" role="dialog" aria-labelledby="columnDiffModalLabel">
        <div class="modal-dialog modal-lg" role="document" style="width:90%;max-width:1100px;">
            ...
        </div>
    </div>

{% endblock content %}

{% block js %}
```

**修后演练** (`scripts/_archive/_drill_wf89_curl_20260824.py`):
```
=== /detail/89/ ===
  status_code: 200
  ✓ columnDiffModal 存在
  ✓ btn-big-table-column-diff 存在
  sqlContent (前端传): 'ALTER TABLE accesscard_black_detail drop COLUMN test3 ;'

=== /gh_ost/column_diff/ ===
  status_code: 200
  body: {"ok": true, "table_name": "accesscard_black_detail", ... "mid_risk_count": 1, ...}
```

## 教训 (跨项目可复用)

**Django template 调试 5 步**:
1. **后端 OK?** - `curl` 或 `Django test client` 直接调端点, 看返什么
2. **HTML 元素存在?** - 模拟请求, 在响应 HTML 里 `grep` 关键 id
3. **JS 注册成功?** - 浏览器 F12 → Console, 看有没有 JS 错误
4. **DOM 找到元素?** - F12 → Console 跑 `document.getElementById("xxx")`, 看是不是 null
5. **业务事件触发?** - F12 → Network, 看 AJAX 调没调, 状态码, 响应

**模板错误判断**:
- 端点返 ok=True + 完整数据, 但前端不显示 → 99% 是 **HTML 元素缺失或位置错**
- 按钮在但 modal 元素不在 → Django template block 错误
- **修法**: 找 `{% block %}` `{% endblock %}` 边界, 把元素移进对应 block

**类似案例排查清单**:
- gh-ost 任务管理页 modal (待验证)
- 智能回滚 reverse SQL modal (待验证)
- v0.4.5 gh-ost 进度面板 (待验证)

## 8/24 教训关联

跟昨天其他修法**不是同一个根因**:
- commit `a41c4d0` ConfigurableAuditor 审批流覆盖 - Python 业务逻辑
- commit `9d66064` gh-ost precheck 过度限制 - Python 业务逻辑
- commit `eaf9853` cancel 已审核工单崩 - Python 业务逻辑
- commit `e669567` column_diff use 前缀不展示 - Python 业务逻辑
- **本次** - **Django template 错误** (新增类别)

## 推 110 必做

跟 commit `e669567` 一起推, 业务代码 + template 改动, 5 步必做步骤 13 覆盖。

## 文件改动

- `sql/templates/detail.html` (1 处: 移 modal 元素从 endblock 后到 block 内)

## 关联

- 8/12 字段 diff 设计: `docs/designs/2026-08-12_gh-ost-column-diff-mockup.html`
- 8/12 字段 diff changelog: `docs/changelogs/2026-08-12_gh-ost-column-diff.md`
- 8/24 修法 1 (后端): `docs/changelogs/2026-08-24_column-diff-prefix-compat.md`
- 8/24 reload SOP: `docs/runbooks/2026-08-24_gunicorn-reload-after-code-change.md`
