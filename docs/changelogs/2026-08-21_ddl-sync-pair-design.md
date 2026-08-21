# 2026-08-21 DDL 跨库同步 · 业务库 ↔ 历史库 详细设计稿

## 摘要

Archery v0.5.0 解决"业务库 DDL 变更容易遗漏同步到历史库"的痛点 — DBA 配库对白名单, Archery 自动判断 + 自动建历史库 DDL 工单, 业务 RD 啥都不用管。

## 背景

- **真实痛点**: 业务库 (源) 跟历史库 (归档) 通过时间戳同步数据, 但 DDL 不同步。常见场景:
  - 业务库 `ADD COLUMN` → 历史库没加 → 同步任务报 `Unknown column 'xxx'`
  - 业务库 `MODIFY COLUMN` 改类型/长度 → 历史库没改 → 同步超长报错
  - 业务 RD 忘了同步 / 新人不知道有历史库 / 紧急修复跳过
- **历史库只同步部分表** (不是全量) — 8/21 用户明确的关键约束
- **业务 RD 不知道"本表要不要同步"** — 需要 DBA 在 Archery 后台配

## 设计稿内容

详细设计稿 10 章节, 跟之前 RaccoonX / gh-ost 风格一致 (HTML 60KB + Markdown 30KB):

1. **设计原则** - 跟 5 个二次开发项目一致, 走"扩展 + 复用 + 不重写"路线
2. **业务场景** - 4 个角色 + 2 个新角色 (DBA 业务库 / DBA 历史库)
3. **产品界面** - 5 个核心页面 (库对列表 / 详情 / 工单详情联动 / 历史库工单列表 / 巡检结果)
4. **权限模型** - 跟 8/12 gh-ost 任务管理一致, 4 个标准 perm + 业务 RD 默认不能 (8/13 教训)
5. **数据模型** - 3 张表 (ext_ddl_sync_pair / ext_ddl_sync_table / ext_ddl_sync_history)
6. **URL 路由** - 13 个核心路由 + 1 个 AJAX
7. **联动点** - v0.4.5 DDL 智能回滚 / v0.3.0 gh-ost / v0.3.x 大表防呆 / v0.2.0 钉钉 OA / audit_drivers 5 个联动
8. **实施阶段** - 短期 C (1 周巡检) → 中期 B (2 周工单联动) → 长期 A (评估)
9. **风险与验证** - 9 条风险点, 每条对应 8/19 教训
10. **跟 8/19 教训对照** - 12 条教训

## 关键拍板 (8/21 对话确认)

1. **同步模式: 白名单** - DBA 显式配要同步的表 (默认最小化)
2. **历史库 DDL 审批人: 同业务库 DDL 审批人** - 简化流程, 跟现有 3 级审批一致
3. **业务库失败兜底: 业务库失败 → 历史库工单不发起** - 跟现有 SQL 工单逻辑一致; 业务库成功 + 历史库失败 → 推钉钉 + 巡检兜底
4. **实施节奏: 短期 C (巡检兜底, 1 周) + 中期 B (工单联动, 2 周)** - 长期 A 评估 Archery 自动同步

## 实施路径

| 阶段 | 时间 | 内容 | 验证标准 |
|---|---|---|---|
| **短期 C** | 8/22~8/28 (1 周) | 3 张表 + 库对管理 + 巡检服务 + 钉钉通知 | DBA 配 1 个库对, 跑巡检拿到正确 diff 报告, 一键生成补 DDL 工单走完流程 |
| **中期 B** | 8/29~9/11 (2 周) | 自动建历史库 DDL 工单 + 智能回滚联动 + gh-ost 联动 + 大表防呆 | 业务 RD 提 DDL → 自动建历史库 DDL 工单 → DBA 审核 → 执行成功 → 业务库工单关闭 |
| **长期 A** | 后续 (评估) | Archery 直连历史库, 全自动同步 (0 人工介入) | 业务库/历史库 DDL 100% 一致时, 全自动同步 |

## 跟 8/19 教训对照

| 8/19 教训 | 本次设计应对 |
|---|---|
| SQLAdvisor 装上但跑不出 add index | 短期 C (巡检) 先验证 schema diff 报告内容, 真能找出漏同步才往下做 |
| SOAR 工具装到 /usr/local/bin/ 报 permission denied | 历史库实例用 `archery` user 连 (跟 Archery 一致), 避免 8/19 权限坑 |
| 8/12 gh-ost 任务管理 perm 细分 (commit c80c1ad) | 复用同一套机制, 4 个标准 perm + 业务 RD 默认不能 (8/13 教训) |
| 8/13 教训 默认权限最小化 | 业务 RD 不勾库对管理 perm, 仅 DBA 可见 |
| 8/19 教训 errno 7 (Argument list too long) | 历史库 DDL 也是 SQL 工单, 复用现有 sql_optimize.py / goinception |
| 8/17 教训 Dashboard 优雅降级 | 巡检结果页 (库对 diff) 跟 RaccoonX 巡检任务页风格一致, 失败时友好提示 |
| 8/17 教训 5 步必做 idempotent | 5 步必做补一条 `migrate_ext_ddl_sync`, 推 110 当天可重复跑 |
| 8/12 教训 gh-ost 任务管理菜单并列 | 新菜单 "🔗 DDL 同步管理" 跟 "gh-ost 任务" / "数据库巡检" 并列 |

## 核心设计亮点

1. **DBA 配库对, RD 零感知** - 业务 RD 提 DDL 时, Archery 自动查库对配置, 工单页有清晰提示
2. **复用现有 SqlWorkflow** - 历史库 DDL 工单直接走 `SqlWorkflow` 表, 跟业务库 DDL 共用 audit_drivers 审批, 0 业务代码改动
3. **跟 5 个二次开发全部联动** - v0.4.5 智能回滚 + v0.3.0 gh-ost + v0.3.x 大表防呆 + v0.2.0 钉钉 OA + audit_drivers 审批, 复用而非重建
4. **同审批人简化** - 8/21 拍板, 跟现有 3 级审批一致, 不增加 DBA 流程负担
5. **transform_rule 字段预留** - Phase 1 默认空, Phase 2 扩展处理"业务库/历史库 DDL 不一致"场景

## 文件清单

- `docs/designs/2026-08-21_ddl-sync-pair-design.html` (60KB, 10 章节)
- `docs/designs/2026-08-21_ddl-sync-pair-design.md` (30KB, 配套 Markdown)
- `docs/changelogs/2026-08-21_ddl-sync-pair-design.md` (本文件)

## 关联

- HTML 详设: [2026-08-21_ddl-sync-pair-design.html](../designs/2026-08-21_ddl-sync-pair-design.html)
- Markdown 详设: [2026-08-21_ddl-sync-pair-design.md](../designs/2026-08-21_ddl-sync-pair-design.md)
- 同源设计稿: RaccoonX 浣巡 70KB (commit `ddba8f9`, 8/21) / gh-ost 80KB / DDL 智能回滚 38KB / v0.4.0 归档 64KB / v0.4.5 rebuild 40KB / 钉钉 OA 102KB

## 下一步

等用户审完设计稿, 拍板后开干短期 C (1 周巡检兜底)。
