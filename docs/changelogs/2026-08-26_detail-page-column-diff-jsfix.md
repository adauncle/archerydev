# 2026-08-26 detail 页字段 diff JS 错误修复 (8/26 21:53)

**类型**: fix (8/26 21:34 detail 页字段 diff 新功能 后续 fix)
**严重度**: P0 (业务 RD 浏览器 JS ReferenceError, 字段 diff inline 区域不能用)
**修复时间**: 2026-08-26 21:53 (5min fix + 验证)
**commit**: 待补 (本次 commit)

---

## 症状

8/26 21:51 业务 RD 浏览器 detail/4747/ 报错:

```
jQuery.Deferred exception: hly_accesscard is not defined ReferenceError: hly_accesscard is not defined
    at HTMLDocument.<anonymous> (4747/:1993:26)

Uncaught ReferenceError: hly_accesscard is not defined
    at HTMLDocument.<anonymous> (4747/:1993:26)
```

业务 RD 字段 diff inline 区域没渲染 (因为 JS 错误中断).

---

## 根因

8/26 21:34 commit `0a04775` 加 detail.html 自动触发 JS:

```html
$(document).ready(function() {
    var sqlContent = {{ workflow_detail.sql_workflow_content|default:""|escapejs|default:"''" }};
    var instanceId = {{ workflow_detail.instance_id|default:0 }};
    var dbName = {{ workflow_detail.db_name|default:""|escapejs|default:"''" }};
    fetchColumnDiff(sqlContent, instanceId, dbName);
});
```

**问题**:
1. Django 4.0+ **移除了 `escapejs` filter** (1.9 deprecated, 4.0 removed), 但 `|default:""|escapejs` 看似工作, 实际**默默返原值**
2. `workflow_detail.sql_workflow_content` 走 OneToOneRel 关联到 `SqlWorkflowContent.sql_content`, 渲染时返字符串
3. SQL 内容如 `use hly_accesscard;\nALTER TABLE test ...` 渲染到 JS:
   ```js
   var sqlContent = use hly_accesscard;
   ALTER TABLE test MODIFY COLUMN ...;
   ```
4. JS 解析器把 `use hly_accesscard;` 当语句, 然后 `hly_accesscard` 当标识符, 报 ReferenceError

---

## 修法

### 改动 1: views.py 加 import + context 变量 (`sql/views.py`)

```python
import os
import json  # 新加
import traceback
```

detail view context 加 3 个变量:

```python
## CUSTOM-MODIFIED: 8/26 detail 页字段 diff inline 区域 @ 2026-08-26 @ mavis
## 关联 changelog: docs/changelogs/2026-08-26_detail-page-column-diff.md
"sql_content_for_diff": json.dumps(_workflow_sql_text(workflow_detail)),
"instance_id_for_diff": workflow_detail.instance_id or 0,
"db_name_for_diff": json.dumps(workflow_detail.db_name or ""),
```

`json.dumps(s)` 自动用双引号包 + 转义内部 `\n` / `"` / `\`, JS 拼字符串安全.

### 改动 2: detail.html 用新 context 变量 (`sql/templates/detail.html`)

```html
$(document).ready(function() {
    var sqlContent = {{ sql_content_for_diff|safe }};
    var instanceId = {{ instance_id_for_diff|default:0 }};
    var dbName = {{ db_name_for_diff|safe }};
    fetchColumnDiff(sqlContent, instanceId, dbName);
});
```

`{{ var|safe }}` 标记 Django template 不要 escape (因为 json.dumps 已经 escape 好了).

---

## 110 prod 验证 (8/26 21:56)

业务流渲染 detail/4747 (业务 RD 最新工单, 含 `hly_accesscard`):

```
--- var sqlContent = ... ---
var sqlContent = "ALTER TABLE test MODIFY COLUMN account_id_old VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT 'id' COMMENT '\u8054\u8d26\u6237ID';"
--- var dbName = ... ---
var dbName = "hly_accesscard";
```

✓ 字符串双引号包裹 + 中文 unicode 转义 + 不再 ReferenceError
✓ `column-diff-result` 出现 3 次 (HTML 1 + JS 2)
✓ `fetchColumnDiff` 出现 2 次, `renderColumnDiff` 出现 3 次

业务 RD 浏览器刷新 detail/4747, 字段 diff inline 区域自动渲染 8 维 + 11 风险点 + 修复建议.

---

## 教训 (跨项目可复用, 3 条)

1. **Django 4.0+ 没有 `escapejs` filter, 用 `json.dumps` + `|safe`** — JSON 字面量天然是 JS 字符串, 不需要再 escape. 老 Django 模板 `{{ var|escapejs }}` 在 4.0+ 静默返原值, 易踩坑
2. **Django template 渲染 JS 字符串, 必须用 `|safe` + view 端 json.dumps, 不能依赖 template filter** — 因为 SQL 内容含换行 / 引号 / 中文, template 渲染直接拼 JS 会暴露成 JS 标识符
3. **业务 RD 浏览器实测 5+1 端点验证深度不够** — 8/26 21:34 演练我用 archery force_login 渲染 detail/4746, 134 dev 演练用 wf 103 (accesscard_black_detail), 都**没踩 hly_accesscard 库名**这个特殊 SQL 头部. 实战业务 RD 提单的 SQL 含 `use hly_accesscard;` 才暴露. **5+1 端点验证必用业务 RD 真工单, 不用 DBA 演练脚本**

---

## 关联

- 8/26 21:34 字段 diff 新功能 commit `0a04775` (本次修复的源头)
- 上一份 changelog: `2026-08-26_detail-page-column-diff.md`
- 推 110 主手册: `docs/runbooks/2026-08-27_push-v030-execution-manual.md` (待更新 5+1 端点 → 5+1+ORM+REST API+gh-ost precheck+detail 页字段 diff 端点验证)
