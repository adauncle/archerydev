# DDL 跨库同步 W2 D35-Pending: 操作日志规划（待 D36 实战）

> 日期: 2026-09-04 17:28
> 阶段: W2 实施阶段 D35-Pending (推 110 prod 之前, 用户拍板)
> 关联: 9/3 D32 4 大步演练 + 9/4 D33 view 改动 + 9/4 D34 9 步 dry-run 演练

## 背景

业务方实战看 pair_detail.html "操作日志" tab 时发现：tab 内容是 W1 D8 阶段 2 写模板时留的占位符，从来没真实现。

D35-Pending 实战: 拍板 3 方案 + 等 D35 推 110 prod 完成后做 D36。

## 现状 (D9 阶段 2 没真做的根因)

- **W1 D8 阶段 2 写 pair_detail.html** 时, 4 个 tab 都有占位 (基本信息/同步表清单/同步历史/操作日志)
- "操作日志" tab 内容是占位: "D9 阶段 2 上线, 操作日志审计 (创建/编辑/启用/禁用/一键配/批量导入 6 类操作)"
- **W1 D9 阶段 2 实战** 精力在 5 AJAX + signal + perm guard, **没真做操作日志功能**
- **W2 D22-D34 期间** 也没补, 一直挂着

设计文档 (`docs/designs/2026-09-01_ddl-sync-implementation-design.md` line 323) 4 个 tab 列表只列了 tab 名称, 没具体字段设计。

## 3 种实现方案 (D35-Pending 拍板候选)

### 方案 A: 完整独立 DdlSyncAuditLog 模型 (推荐, 干净)

- 新增 `DdlSyncAuditLog` 表 (pair / action / operator / detail_json / created_at)
- 6 类 action enum: create / edit / enable / disable / one_click / bulk_import
- 在 5 个 view 加埋点:
  - `pair_create` (D7) — action=create
  - `pair_edit` (D7) — action=edit, detail_json=diff
  - `pair_toggle` (D7) — action=enable/disable
  - `one_click_setup` (D8) — action=one_click, detail_json=tables
  - `bulk_import` (D8) — action=bulk_import, detail_json=count
- 1 个 migration + 模板渲染 (按时间倒序, 每页 20 条, 跟 D33 同步历史一致)
- **优点**: 6 类全覆盖, 独立审计, 干净
- **缺点**: 改 5 view + 1 model + 1 migration + 1 模板, 工作量 ~150 行

### 方案 B: 复用 Archery 上游 LogEntry (轻量)

- 复用 `django.contrib.admin.models.LogEntry` (Archery 上游记 admin 操作)
- 4 类 admin 操作能自动覆盖 (创建/编辑/启用/禁用走 admin 也能记)
- 一键配/批量导入 走 view 调 admin, **也能被 LogEntry 记到**
- **优点**: 0 新代码, 模板查 LogEntry
- **缺点**: LogEntry 不太细 (只记 object_repr + change_message), 无 JSON detail 字段

### 方案 C: MVP — 先 4 类 (创建/编辑/启用/禁用)

- 一键配/批量导入 暂不埋点 (手动 1 条占位 "审计 TODO")
- 用 LogEntry 渲染, **0 新代码**
- **优点**: 立刻能上线, 0 风险
- **缺点**: 后 2 类缺失, DBA 实战时会发现

## 用户拍板 (D35-Pending 2026-09-04 17:28)

- **决定**: 等 D35 推 110 prod 完成后, 做 D36 实战
- **倾向方案**: A (推荐, 干净, 符合 D33 一贯风格)
- **理由**: 操作日志是 "加分项" 不是 "主功能", 不影响 110 prod 上线效果
- **D36 计划**: 用户拍板 A 之后, 1 model + 1 migration + 5 view 埋点 + 1 模板 + commit

## 待办

1. **D35 = 推 110 prod 实战** (9/4 17:28 后, 待启动)
2. **D36 = 操作日志功能** (D35 推完后, 1 model + 5 view 埋点 + 1 模板)
3. **D37 = 推 110 prod 增 D36 操作日志** (D36 完成后)
