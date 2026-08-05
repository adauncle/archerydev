# v0.3.0 gh-ost · 4 件事拍板

**日期**: 2026-08-05
**关联**: `docs/designs/2026-08-05_gh-ost-product-design.html` (12 章节产品设计)

---

## 拍板

| # | 问题 | 拍板 |
|---|---|---|
| 1 | gh-ost 二进制装在哪？ | **先 134 dev**，dev 验证通过后再装 110 prod（不并行）|
| 2 | 演练大表选哪个？ | **用户先迁移一张大表到 134 dev**（用户做这步）|
| 3 | 前端 UI 谁做？ | **我（Mavis）做**（Vue + Element UI 现有栈）|
| 4 | 排期位置？ | **v0.3.0**（排在 v0.2.3 OA 对账之后）|

## 当前状态

- v0.2.0 切到 110 完成（20:13）
- v0.2.1 OA 框架发布（不启用，8 个 ext_ 表已建）
- v0.2.2 OA callback + tunnel 待做
- v0.2.3 OA 对账 + runbook 待做
- **v0.3.0 gh-ost 等待**：用户先把演练大表迁到 134 dev

## 启动 v0.3.0-alpha 的前置

1. 用户迁移一张大表到 134 dev（用户动作）
2. 134 dev 装 gh-ost 二进制（我动作）
3. 新建 `ext_ddl_ghost_task` 表 model + migration（我动作）
4. 预检查 5 道 + 工单详情页 checkbox + 进度面板（我动作）

## 不动什么

- 110 prod 不动（dev 验证通过才推）
- 不真跑 gh-ost（alpha 阶段只生成 task 记录 + 标记 "would use gh-ost"）
- UI 组件不写（alpha 阶段后做）
