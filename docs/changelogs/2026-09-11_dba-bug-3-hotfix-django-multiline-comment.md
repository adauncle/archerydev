# DBA-bug-3 hotfix: Django 跨行 `{# #}` 模板注释不识别 → 改用 `//` JS 注释

> **DBA 实战 (9/11 19:35 阿达叔叔反馈)**: 9/11 19:30 推完 DBA-bug-3 (commit `bac9e4f`) 后, 业务方访问 `/submitsql/` 报 **`Uncaught SyntaxError: Invalid or unexpected token`** 整页 JS 都不能跑。
>
> 9/11 19:40 调研根因: 我新加的 `{# ... #}` Django 模板注释**跨 4 行**, Django 4.2.30 模板引擎**不识别多行 `{# #}` 注释, 完整保留字符串在 HTML 输出**, `{#` 字符被 JS parser 当 block statement 开始, 抛 `Invalid or unexpected token`。
>
> 9/11 19:55 hotfix: 把跨行 `{# #}` 注释改用 `//` JS 注释 (单行), Django 不再处理, JS parser 看到 `//` 自动忽略, 整页 JS 恢复。

## 现象

- **触发工单**: 任何业务方在 9/11 19:30 - 19:55 之间访问 `/submitsql/`, 整页 JS 报错, 字段 diff modal + 大表 alert banner 都失效
- **现状 (DBA-bug-3 推后, 9/11 19:30 - 19:55)**:
  - 浏览器 Console 报 `Uncaught SyntaxError: Invalid or unexpected token` 红色错误
  - `submitSql` 之后的所有 JS 不能跑 (renderColumnDiff / fetchColumnDiff / 大表 alert banner 全部失效)
  - Archery 110 prod 业务方实战首次反馈: **"大表 alert + 字段 diff 仍完全没弹窗"**

## 根因

**位置**: `sql/templates/sqlsubmit.html:702-706` (DBA-bug-3 修法)

```html
{# CUSTOM-MODIFIED: 9/11 DBA-bug-3 大表 alert 渲染 helper @ 2026-09-11 @ mavis
 业务: ok=False 但 big_table_alert 不为 None 时 (ADD INDEX/DROP INDEX/RENAME 等非字段变更),
       单独渲染大表 alert 到 modal (没字段 diff) + 主页面 banner
 关联: docs/changelogs/2026-09-11_dba-bug-3-big-table-alert-add-index-drop-index.md #}
```

我**跨 4 行**用 `{# ... #}` Django 模板注释包裹新加的 helper 函数说明。

### Django 4.2.30 模板引擎 `{# #}` 注释处理行为

**134 dev 用 Django 4.2 模板引擎测试** (`scripts/_dba_bug3_django_test_134.sh`):

| Test | 输入 | Django 输出 | 结论 |
|------|------|-------------|------|
| 1 | `{# multi\nline\ncomment #}\n<script>...</script>` | **完整保留字符串** | ❌ Django 4.2 不支持多行 `{# #}` 注释 |
| 2 | `{# comment with } brace #}\n<script>...</script>` | `\n<script>...</script>` | ✅ 单行 `{# #}` (含 `}`) Django 正确移除 |
| 3 | 实际业务场景 (中文多行 + 圆括号 + 反引号 schema) | **完整保留字符串** | ❌ 跨行 `{# #}` Django 失败 |

**根因**: Django 4.2 模板 `{# #}` 注释的 lexer 处理**只支持单行**, 跨行 `{# #}` 注释 Django 不会移除, 完整字符串保留在 HTML 输出。

如果这段字符串在 `<script>` 块内, JS parser 看到 `{#` 字符 (Django 移除 `{# #}` 时漏掉), 把 `{#` 当作 block statement 开始, `{` 后跟 `#` 是 invalid token, 抛 `Uncaught SyntaxError: Invalid or unexpected token`。

## 修法

**位置**: `sql/templates/sqlsubmit.html:702-708` (DBA-bug-3 hotfix)

```javascript
// CUSTOM-MODIFIED: 9/11 DBA-bug-3 大表 alert 渲染 helper @ 2026-09-11 @ mavis
// 业务: ok=False 但 big_table_alert 不为 None 时 (ADD INDEX/DROP INDEX/RENAME 等非字段变更),
//       单独渲染大表 alert 到 modal (没字段 diff) + 主页面 banner
// 关联: docs/changelogs/2026-09-11_dba-bug-3-big-table-alert-add-index-drop-index.md
// 注意: 之前用 Django 模板注释 {# #} 包裹, 但里面 JS 字符串含 } 字符
//       Django 解析器可能误识别 #}, 导致 {# ... 留在 JS 输出, JS 报 SyntaxError
//       改成 // 单行注释, Django 不解析, JS 安全
function renderBigTableAlertOnly(bta) {
    ...
}
```

把 `{# ... #}` 跨行注释改成 `//` 单行 JS 注释:
- Django 模板 lexer 不处理 `//` (因为不在 `{%` / `{#` tag 语法里)
- JS parser 看到 `//` 自动忽略到行尾
- 即使 `//` 注释里含 `{` `}` `{#` 字符也不会被 Django 误处理

## 验证

### 110 prod 渲染后 HTML 检查 (`scripts/_dba_bug3_check_110_v2.py`)

- 访问 `/submitsql/` 拿渲染后 HTML
- 找所有 `{` + `#` 出现位置
- 精确判断每个 `{#` 是不是在 JS 可执行代码里 (用 `//` 单行注释前缀检查)

```
[1/2] 登录成功
[2/2] HTML size: 106322 bytes

=== 精确检查 {# 出现位置 ===
  line 1570: in_script=True  in_js_comment=True
    line before: '        //       Django 解析器可能误识别 #}, 导致 '

=== renderBigTableAlertOnly 函数定义 ===
  found at offset 70212
  content: 'function renderBigTableAlertOnly(bta) {\n            return ...'
```

**唯一 1 个 `{#` 出现在 line 1570, `in_js_comment=True`** — 字符串在我新加的 `//` JS 注释里, JS parser 自动忽略, **不会报 SyntaxError**。
**`function renderBigTableAlertOnly` 出现在 offset 70212** — hotfix 生效, helper 函数被正确加载。

### 110 prod 端点演练 (`scripts/_dba_bug2_drill_110.py` 加测, 9/11 19:55 hotfix 后)

- 图1 consume_flow ADD INDEX: `ok=True, big_table_alert={rows: 5238005, size_mb: 3482.4}` ✅
- 图2 consume_flow modify column: `ok=True, big_table_alert + high_risk=1, mid_risk=1` ✅
- consume_flow DROP INDEX: `ok=False, big_table_alert={rows: 5238005, size_mb: 3482.4}` ✅

### 110 prod 老工单回归 (9/11 19:55 hotfix 后)

- wf#4803: HTTP 200, 大表 alert 完整渲染 ✅
- wf#4791 / wf#4792 / wf#4783: HTTP 200 0 个 500 ✅

## 推 110 prod

- 134 dev 演练通过 → 推 sqlsubmit.html (hotfix 注释) → md5 完全一致
- kill -TERM 老 workers (19:19 启动的 52537-52545) → master 8694 自动拉新 workers 19:55 启动
- 真 HTTP 演练 + 老工单回归 → 0 个 500

## 实战新发现 (跨项目可复用, 1 条)

- **Django 模板 `{# #}` 注释只支持单行** (DBA-bug-3 hotfix 实战新发现) - 跨项目用 Django 模板, **跨行注释用 `{% comment %}{% endcomment %}` 块注释** (明确闭合), 或者直接用 `//` JS 注释 (Django 不处理). 实战踩坑: 9/11 19:30 推的 sqlsubmit.html 用了 4 行 `{# #}` Django 模板注释, Django 4.2.30 模板引擎不识别, 完整字符串留在 HTML 输出, 在 `<script>` 块内被 JS parser 当 block statement 开始, 抛 `Uncaught SyntaxError: Invalid or unexpected token`. 修法: 跨行注释用 `//` JS 注释, Django 不解析, JS parser 看到 `//` 自动忽略. 跨项目推 Django HTML 模板必演练真 HTTP 用 `assert "Uncaught" not in response.text` 验证无 JS 错误, 别只检查 HTTP 200
