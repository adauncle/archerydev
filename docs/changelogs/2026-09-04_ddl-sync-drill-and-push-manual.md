# 9/4 W1-D5 DDL 跨库同步 134 dev 演练设计 + 推 110 主手册 + W1→W2 衔接 (9/4 14:30)

## 概要

W1 设计阶段 D5 (9/4 周五) 落地, 配合 W1-D1+D2+D3+D4 完成 W1 阶段 5/5 任务 (W1 设计 100% 完成). W1-D5 是 W2 实施 + W3 提测的"前置准备文档", 含 134 dev 端到端演练 5 Case 详细步骤 + 推 110 主手册更新 (基于 8/25 f44c26e 23KB 结构加 DDL 同步新内容) + W1→W2 衔接 (5 天日程 D6-D10 + 19 文件清单).

## 5 份设计稿 + 1 份主手册 完整体系

| 文档 | 读者 | 篇幅 | 视角 |
|---|---|---|---|
| refined (`2026-08-31_ddl-sync-pair-design-refined.md`) | 领导汇报 | 42KB | 业务视角 |
| D2 数据模型 (`2026-09-01_ddl-sync-data-model.md`) | DBA 内部 | 14.6KB | 表结构视角 |
| W1-D3 实施 (`2026-09-01_ddl-sync-implementation-design.md`) | DBA 实施 (后端) | 46KB | API 契约 |
| W1-D4 前端 (`2026-09-03_ddl-sync-detail-ux-design.md`) | DBA 实施 (前端) | 40KB | 前端 UX |
| **W1-D5 本次** (`2026-09-04_ddl-sync-drill-and-push-manual.md`) | W2 实施 + W3 提测 | 25.5KB | 演练 + 推 110 + 衔接 |
| 8/25 推 110 主手册 (`commit f44c26e`) | 推 110 执行 | 23KB | 5 步必做 + 11+1 端点 verify |

## 3 章节结构

1. **134 dev 端到端演练设计** — 5 Case 详细步骤 (A 配库对 5min / B 一键配 6min / C 真实 DDL 15min / D rollback 10min / E perm 10min = 46 min 总演练) + 跟 gh-ost 演练对比 (1.5x 时间, DDL 同步涉及双库 + 镜像工单 + 联动点) + 失败回退预案
2. **推 110 主手册更新** — 5 步必做 (备份 / 比对 SECRET_KEY / .env 完整 review / 推 4 文件 / migration + perm + restart + smoke test) + 11+1 端点 verify (5 旧 + 5 DDL 同步 + 1 登录) + K1/K2/K3/K4 避坑 (8/26 实战 3 P0 + 9/1 新加 K4 sql_config 3 key) + 业务 RD mkq 浏览器实测
3. **W1 → W2 衔接** — 5 天日程 D6-D10 实施步骤 + 19 文件清单 (后端 10 + 前端 9) + 8/26 实战 10 P0 教训应用 (K1/K2/K3/K4 + 端点深度 + gh-ost alter 1064 + poller zombie + rollback import + gh-ost 端口探测 + JS ReferenceError) + 5 步必做 步骤 14 (systemd 清理 + qcluster stale conn)

## 关键拍板 (9/4 14:30, 假设)

- ✅ 命名/路径 `docs/plans/2026-09-04_ddl-sync-drill-and-push-manual.md`
- ✅ 3 章节结构 (134 dev 演练 + 推 110 主手册 + W1→W2 衔接)
- ✅ 134 dev 演练 5 Case 详细步骤 (A/B/C/D/E)
- ✅ 推 110 主手册基于 8/25 f44c26e 23KB 结构, 加 DDL 同步新内容

## 134 dev 演练 5 Case 验收标准

- **Case A** (5 min): 配 1 个真实库对 hly_accesscard (业务库 1589 ↔ 历史库 1289), admin 列表显示 1 行, 5 按钮可点击
- **Case B** (6 min): 一键配 1-click 接受 1589 张 < 30s, bulk_create 成功, 0 失败, 同步表清单显示 1589 张
- **Case C** (15 min): 业务 RD mkq 浏览器触发 1 条 ALTER TABLE, 业务库 DDL PASSED → 历史库镜像工单自动生成 → DBA 1 级审批 → 执行 → DdlSyncHistory 标 synced
- **Case D** (10 min): 故意失败 DDL (VARCHAR(5) 数据截断), 镜像工单 failed → v0.4.5 智能回滚自动触发 → 钉钉通知 → DdlSyncHistory 标 failed → DBA 主动点回滚 → 标 rolled_back
- **Case E** (10 min): 4 perm 4 角色验证 (业务 RD 隐藏 / DBA 组长 全 / DBA 执行 4 / superuser 全), AJAX 端点 perm 守卫返 JsonResponse(403) 不 raise PermissionDenied

## 推 110 主手册 4 避坑 (K1/K2/K3/K4)

| 避坑 | 教训 | 步骤 |
|------|------|------|
| **K1 SECRET_KEY** | 8/26 推 110 漏检 .env SECRET_KEY, 业务 RD 登录 500 | 步骤 2 比对 SECRET_KEY 必保留 prod 原值 |
| **K2 CACHE_URL** | 8/26 推 110 .env 没 CACHE_URL, 业务 RD 选 database 500 | 步骤 3 必加 CACHE_URL=redis://:password@127.0.0.1:6379/0 |
| **K3 dev-only 变量** | 8/26 推 110 CUSTOM_GH_OST_PRECHECK_* 没清, gh-ost precheck 1045 | 步骤 3 必清空 CUSTOM_* 变量 |
| **K4 sql_config 3 key** (9/1 新加) | 9/1 推 110 漏检 sql_config 3 key, 业务 RD 用 SQL 优化工具报错 | 步骤 3 必 SELECT 检 3 个 key, 缺一个 UPDATE 一个 |

## W1 完整周报 (8/31-9/4)

- D1 8/31 ✓ 14 次精修 + refined
- D2 9/1 上午 ✓ 3 张表 + 5 migration + 4 拍板
- D3 9/1 下午 ✓ 4 service 函数 + 5 AJAX 端点
- D4 9/1 下午 ✓ 5 按钮 modal + alert + batch_schema_diff
- **D5 9/1 下午 ✓ (本次) 134 dev 5 Case + 推 110 主手册 + 衔接**

**W1 5 文档产出 157-162KB**: refined 42KB + D2 14.6KB + D3 46KB + D4 40KB + D5 25.5KB

**提前 3 天**完成 W1 5 任务 (按计划是 8/31-9/4 5 天, 实际 9/1 下午 2 天半完成)

## W2 5 天日程 (9/7-9/11)

| 天 | 日期 | 主要工作 | 引用 |
|----|------|----------|------|
| D6 | 9/7 (周一) | 数据模型 migration | W1-D2 §5 |
| D7 | 9/8 (周二) | 库对管理 CRUD + admin | W1-D3 §2 + W1-D4 §1 |
| D8 | 9/9 (周三) | 5 按钮 + R1 批量导入 | W1-D3 §3 + W1-D4 §1.1-§1.3 |
| D9 | 9/10 (周四) | R2 一键配 + R3 走当前配置 | W1-D3 §4 §5 + W1-D4 §1.2 |
| D10 | 9/11 (周五) | 134 dev 端到端演练 5 Case | W1-D5 §1 |

## 19 文件清单 (W2 实施物料)

**后端 10 文件** (W1-D3 §1.1):
- sql/extensions/ddl_sync/ 整个目录 (models + admin + migrations/5 + services/8 + views/3 + forms/2 + urls.py + management/commands/2)
- 配合 archery/urls.py +1 行 include

**前端 9 文件** (W1-D4 §5.4):
- sql/extensions/ddl_sync/templates/ 6 文件 (pair_list/detail/form + 5 modal)
- sql/extensions/ddl_sync/static/ddl_sync/ 3 文件 (list/detail/column_diff_reuse)
- 联动修改 2 文件 (common/templates/base.html 侧边栏 + sql/templates/sql/detail.html alert)

**总物料 19 文件**, 缺一个推 110 必然 500

## 改动文件

- `docs/plans/2026-09-04_ddl-sync-drill-and-push-manual.md` (新文件, 25.5KB)
- `docs/changelogs/2026-09-04_ddl-sync-drill-and-push-manual.md` (本 changelog, 5.4KB)

## 下一步

- **W1 收尾**: W1 周报 9/4 周五提交 (按 8/17 拍板 3 周周报格式)
- **W2 启动准备** (9/2-9/6): 准备 19 文件物料 + 134 dev 演练环境
- **W2 开发** (9/7-9/11): 按 W1-D5 §3.1 5 天日程落地
- **W3 提测上线** (9/14-9/18): 按 W1-D5 §2 推 110 主手册

## 提交

待 commit + push origin main
