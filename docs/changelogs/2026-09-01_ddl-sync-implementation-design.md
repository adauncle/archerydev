# 9/1 W1-D3 DDL 跨库同步 核心功能详细设计 (DBA 实施用) (9/1 14:15)

## 概要

W1 设计阶段 D3 (9/1 周二下午) 落地, 配合 W1-D2 数据模型定稿 (9/1 09:30) 跟 W1-D1 背景调研 (8/31), 完成 W1 阶段 3/5 任务. W1-D3 是 DBA 内部实施用详细设计稿 (20-25KB, 实际 46KB 含详细代码示例), 跟领导汇报的 refined (42KB) + D2 数据模型 (14.6KB) 形成 3 份文档梯度.

## 3 份设计稿梯度

| 文档 | 读者 | 篇幅 | 视角 |
|---|---|---|---|
| refined (`2026-08-31_ddl-sync-pair-design-refined.md`) | 领导汇报 | 42KB | 业务视角 (为什么做 / 痛点 / 影响 / 目标) |
| D2 数据模型 (`2026-09-01_ddl-sync-data-model.md`) | DBA 内部 | 14.6KB | 表结构视角 (3 张表 / ER 图 / migration) |
| **W1-D3 本次** (`2026-09-01_ddl-sync-implementation-design.md`) | DBA 实施 | 46KB | 代码视角 (API 契约 / 服务拆分 / 状态机 / 异常处理) |

## 10 章节结构

1. **概述** — 3 文档关系图 + 文档地图 + 核心目标
2. **后端服务拆分** (services/ 目录) — 9 service 文件 + 4 核心函数签名 (compute_diff / one_click_setup / create_target_workflow / bulk_import_tables)
3. **5 端点 URL 路由** — 5 AJAX + 3 view 端点契约 (compute_diff / one_click_setup / bulk_import / add_table / history_list)
4. **R1 批量导入 UX 流程** — 库对详情页 4 tab + R1 modal UX + 后端流程 + 异常处理
5. **R2 一键配 UX 流程** — R2 modal UX (主流程) + 后端流程 (compute_diff + one_click_setup) + 1589 张表性能预算 14.5s
6. **R3 走当前配置的实现** — 镜像工单生成逻辑 (sync_trigger.create_target_workflow) + 0 额外审批配置 + v0.4.5 智能回滚联动
7. **5 status 状态机** (DdlSyncHistory 业务流) — 状态机图 (pending/syncing/synced/skipped/failed) + 跟 gh-ost poller 状态机对照
8. **4 perm 4 判定** — 4 perm 命名 (view/add/change/delete) + 4 角色 4 判定 (业务 RD/DBA 组长/DBA 执行/副总) + AJAX 守卫 (8/13 教训应用) + 前端守卫
9. **联动点** (4 个) — v0.4.5 智能回滚 + v0.2.0 钉钉 OA + 8/12 字段 diff + 9/1 gh-ost 端口探测
10. **异常处理 + 性能预算** — 5 类异常 + 9 性能指标 (1589 张表场景) + 8/27 gh-ost 5 踩坑复用 + 监控指标

附录 A: 9/1 W1-D3 拍板记录
附录 B: 跟 W2 实施的接口契约 (9/7-9/11 按本文 §1-§10 落地)

## 关键拍板 (9/1 14:09)

- ✅ 命名/路径 `docs/designs/2026-09-01_ddl-sync-implementation-design.md`
- ✅ 10 章节结构 (跟 D2/refined 形成梯度)
- ✅ 跟 refined 互相引用不覆盖 (DBA 实施版 + 领导汇报版并存)

## 8/27 gh-ost 实战 5 踩坑复用

W1-D3 §6 §9 显式复用 8/27 gh-ost 实战经验:
1. **Zombie 检测**: 镜像工单 qcluster worker zombie 检测, 复用 poller `/proc/<pid>/status` State 字段判断
2. **端口探测**: target_instance 走 `_detect_actual_mysql_port`, 探测失败 fallback config port (8/31 commit 0036597)
3. **rollback 语义**: 镜像工单 failed 时 v0.4.5 rollback IF EXISTS 走 no-op, 不要"撤销 DDL" 误区 (8/27 17:30 修正)
4. **poller staleness**: 镜像工单执行超过 1h 没 update, 视为卡死, 自动标 failed
5. **signal handler 异常兜底**: workflow_passed_handler 整个 try/except, 异常不能阻塞业务库 DDL 主流程

## 8/26 推 110 实战 3 P0 教训应用

W1-D3 §10 推 110 checklist 必避 8/26 实战 3 P0:
- K1 SECRET_KEY (推前比对 .env)
- K2 CACHE_URL (推前加 .env)
- K3 dev-only 变量 (推前 review CUSTOM_*)

## W1 / W2 / W3 节奏 (8/28 17:58 拍板)

- **W1 设计 (8/31-9/4)**: D1 ✓ (背景) / D2 ✓ (数据模型) / **D3 ✓ (本次核心功能)** / D4 / D5
- **W2 开发 (9/7-9/11)**: 按本文 §1-§10 落地
- **W3 提测上线 (9/14-9/18)**: 按本文 §10 checklist 走 5 步必做 + 134 dev 端到端演练 + 业务 RD mkq 浏览器实测

## 改动文件

- `docs/designs/2026-09-01_ddl-sync-implementation-design.md` (新文件, 46KB)
- `docs/changelogs/2026-09-01_ddl-sync-implementation-design.md` (本 changelog, 3.8KB)

## 下一步

- W1-D4 (9/2 周三): 4 perm 4 角色 在 admin 后台配置实战 (DBA 团队 perm 分配演练)
- W1-D5 (9/3 周四): 端到端演练 checklist 定稿 + 134 dev 演练环境准备
- W2 开发 (9/7-9/11): 按 W1-D3 §1-§10 落地代码

## 提交

待 commit + push origin main
