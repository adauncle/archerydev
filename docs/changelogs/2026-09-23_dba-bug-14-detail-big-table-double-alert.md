# 9/23 DBA-bug-14: detail 页大表 DDL alert 重复块修复

**日期**: 2026-09-23 13:50 阿达叔叔反馈
**症状**: wf#4885 (`accesscard_attachfeeaudit` 大表 DDL) 详情页显示两个相同的粉色大表 alert 块
**根因**: 后端模板 `detail.html:557-614` `{% if big_table_alert %}` 已稳定渲染 (8/26 + 9/11 DBA-bug-1 设计), 含字段 diff 按钮 + DBA 兜底启用 gh-ost 按钮 + 立即执行双层 confirm; 8/26 又加了 JS `bigTableAlertHtml` 拼装到 `#column-diff-result` 容器, 文案跟后端模板块一样但没按钮 → UX 重复 (纯文案噪音)
**修法** (1 文件 1 处, `detail.html:1877-1899`): 删除 JS 拼装 `bigTableAlertHtml` 整段 (18 行) + 改 `var html = bigTableAlertHtml + '...'` → `var html = '...'`
**保留**: 后端模板 `line 557-614` 块不动 (字段 diff 按钮 + DBA 兜底启用 gh-ost + 立即执行双层 confirm 全在这, 不能删)

---

## 实战新发现 (跨项目可复用)

**"页面有两块静态 + JS 拼同一 UI 内容时, 优先保留功能完整的后端模板块, 删 JS 拼的纯文案块"**:
- 跨项目写前端页面时, 如果发现同一 UI 内容**有两个块都渲染** (后端模板 + JS 拼装), 不要两边都留
- 判断保留哪个的优先级:
  1. **含按钮 / 可交互元素**: 优先保留 (业务方/DBA 需要点)
  2. **纯文案 / 静态信息**: 删掉 (重复信息纯噪音, UX 杂乱)
- 实战踩坑: 9/23 wf#4885 阿达叔叔反馈 detail 页显示两个粉色大表 alert 块, 一查发现后端 line 557-614 渲染了 (有按钮) + 8/26 JS `bigTableAlertHtml` 又渲染了一份 (纯文案) → 删除 JS 那份, 保留后端那份
- 实战教训: 后端模板块的"功能完整性"是它的价值, JS 拼装那块常是 8/26/9/2 早期补的"安全网", 当后端模板已经稳定后, JS 拼装那份就成冗余

---

## 演练 (scripts/_w3_dba_bug14_verify.py 13/13 PASS)

### 静态 (13/13)
- [1] 后端模板大表 alert 块还在 (6 项)
    - 模板条件 `{% if big_table_alert %}` 还在 (line 557)
    - 容器 id="big-table-alert" 还在
    - 字段 diff 按钮 id="btn-big-table-column-diff" 还在
    - 立即执行按钮 id="btn-big-table-execute" 还在 (DBA 兜底双层 confirm)
    - 启用 gh-ost 按钮 id="btn-big-table-enable-ghost" 还在 (DBA 兜底)
    - can_enable_ghost 守卫 `{% if can_enable_ghost %}` 还在 (DBA-bug-13 第一波)
- [2] 9/23 DBA-bug-14 JS 拼装删除 (4 项)
    - `var html =` 直接拼 div (无 `bigTableAlertHtml` 前缀)
    - `var bigTableAlertHtml = "";` 变量声明已删除
    - `bigTableAlertHtml +` 字符串拼接已删除
    - 留有删除说明注释 (跨项目复用 + 实战新发现)
- [3] 字段 diff inline 区域还在 (2 项)
    - `<div id="column-diff-result">` 容器 div 还在 (line 908)
    - detail 页加载时自动触发 `fetchColumnDiff`
- [4] 改动的代码位置 line 范围 (1 项)
    - line 1997 `var html =` (不含 bigTableAlertHtml)

### 逻辑验证 (覆盖)
- 后端大表 alert 块有 5 个按钮 (字段 diff / 立即执行 / 启用 gh-ost / etc), JS 那块只是纯文案 → 删除 JS 不丢任何功能
- 字段 diff inline 区域 (`#column-diff-result`) 仍自动触发 AJAX `/gh_ost/column_diff/`, 但只渲染字段 diff 数据 (不带大表 alert 文案)
- 审批人登录 detail 页第一眼看到大表 alert (line 557 后端模板渲染, 含字段 diff 按钮自查)

---

## 部署 (DBA 一条龙)

1. **134 dev (9/23 13:55)**:
   - scp detail.html → `/opt/archery/prod/sql/templates/detail.html`
   - `systemctl restart archery-prod-gunicorn.service`
   - HTTP 200 ✅
   - grep `bigTableAlertHtml` 残留 = 2 (都在删除说明注释里, 正常)
   - grep `DBA-bug-14 删除 JS 拼装` = 1 ✅
2. **110 prod (9/23 14:00)**:
   - scp detail.html → `/dbdata/archery_v114_c9236a0/sql/templates/detail.html`
   - gunicorn HUP reload (master pid=109396)
   - HTTP 200 ✅
   - grep 验证同上 ✅

---

## 实战测 (阿达叔叔)

wf#4885 (`accesscard_attachfeeaudit` 大表 DDL) 详情页硬刷新:
- ✅ 只显示 1 个大表 alert 块 (含字段 diff 按钮 + DBA 兜底启用 gh-ost + 立即执行双层 confirm)
- ✅ 不再有下方重复的纯文案块
- ✅ 字段 diff inline 区域仍正常工作 (AJAX 加载 + 字段风险汇总)

---

## 关联

- 9/11 DBA-bug-1 大表 alert 移到审核按钮上面 (`detail.html:557-614` 设计源头)
- 8/26 大表 DDL alert (JS `bigTableAlertHtml` 设计源头, 当时 detail 页"页面加载就显示"补的)
- 9/16 DBA-bug-9.5 多张大表 banner (`{% if big_tables|length > 1 %}` 多表块, 不重复)
- 9/22 DBA-bug-13 第一波 can_enable_ghost 守卫 (`{% if can_enable_ghost %}` line 588 渲染按钮守卫)
- 9/23 (本 commit) 重复块清理

---

## commit

待提交: `fix(detail): 大表 DDL alert 重复块修复 (删除 8/9 JS 拼装 bigTableAlertHtml)`

CHANGELOG: docs/changelogs/2026-09-23_dba-bug-14-detail-big-table-double-alert.md