# 134 dev 验证发现 — detail.html `data-toggle="table"` 自动初始化冲突

**日期**: 2026-08-10
**作者**: mavis
**类型**: fix（前端模板 / bootstrap-table 初始化冲突）

## 背景

上一轮修了 `detail` 视图的 500 错误（`b8c0e6d`），DBA 浏览器点开 `/detail/19/` 页面正常渲染 200，
但浏览器控制台报 `Uncaught TypeError: undefined is not iterable (cannot read property Symbol(Symbol.iterator))`，
且 "操作" 列按钮没显示出来（bootstrap-table 渲染中断）。

## 根因

`detail.html` 用了 `data-toggle="table"` 让 bootstrap-table **自动初始化** `<table>` 标签。
但同一文件里这些 `<table>` 之后又**显式**调 `.bootstrapTable('destroy').bootstrapTable({...})` 重新初始化。

- **line 32** "其他信息"表（纯静态 HTML，无 data / AJAX）→ data=undefined → bootstrap-table 内部 `for...of undefined` 抛错
- **line 136 / 163 / 323** 动态表（tb-detail / tb-logs / osc_percent_list）也有 `data-toggle="table"`，自动 init 后又被显式 destroy 重新 init，**双初始化** 也会炸

console 报 2 次相同错 = line 32 + line 136 各炸一次。

## 修复（4 处去掉 `data-toggle="table"`，加 CUSTOM-MODIFIED 注释）

| 行 | 表格 | 替换 |
|----|------|------|
| 32 | "其他信息"（静态） | `<table class="...">` 不带 data-toggle |
| 136 | tb-detail | `<table id="tb-detail" class="...">` 不带 data-toggle，走 line 555 显式 init |
| 163 | tb-logs | `<table id="tb-logs" class="...">` 不带 data-toggle，走 line 713 显式 init |
| 323 | osc_percent_list | `<table id="osc_percent_list" class="...">` 不带 data-toggle，走 line 762 显式 init（点击 _osc 按钮时） |

```html
<!-- CUSTOM-MODIFIED: 去掉 data-toggle="table" 自动初始化，避免对纯静态表 for...of undefined 抛错。
     走普通 HTML table 渲染。@ 2026-08-10 @ mavis -->
<table class="table table-striped table-hover" ...>
```

## 验证

| wf_id | 改前 (控制台) | 改后 |
|-------|---------------|------|
| 4 | 假设 2 个 error | ✅ 200, 控制台干净 |
| 5 | 同上 | ✅ 200 |
| 6 | 同上 | ✅ 200 |
| 10 | 同上 | ✅ 200 |
| 11~18 | 同上 | ✅ 200 |
| **19** | 2 个 `for...of undefined` 错 + 操作列没渲染 | ✅ 200, 控制台干净, 操作列正常 |

DBA 浏览器强刷 `/detail/19/` 后：
- 页面正常渲染
- DevTools Console **无 `for...of undefined` 错**
- "工单日志" tab 切到能看到操作/操作人/操作时间/操作信息列表

## 110 PROD 影响

| 修复 | 推 110？ |
|------|----------|
| detail.html 4 处去 data-toggle | ✅ 推 |

**注意**：110 prod v0.2.0 也是同一份 detail.html 模板（上游 Archery 1.14.0 base），同样有这 bug。
但只有当 DBA 在 110 浏览器点过 wf 详情页 + 控制台开着才会看到。**影响程度低（仅控制台噪音 + 操作列按钮没渲染）**，
但既然 134 dev 修了就一起推 110。

## 134 dev 操作

- [x] scp detail.html + chown + restart gunicorn
- [x] 13 个工单 detail 视图 200 + 模板渲染正常
- [ ] commit + push（待做）

## 相关 commit

- `b8c0e6d` fix(workflow_audit): detail 视图无审批流兜底
- `e78f758` fix(workflow): detail_content 老工单容错 + KeyError 兜底
- **本轮** — detail.html 去掉 data-toggle="table" 4 处
