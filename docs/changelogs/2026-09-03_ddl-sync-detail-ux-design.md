# 9/3 W1-D4 DDL 跨库同步 库对详情 + 字段 diff 设计 (前端 UX) (9/3 14:30)

## 概要

W1 设计阶段 D4 (9/3 周四) 落地, 配合 W1-D3 (9/1 后端) + W1-D2 (9/1 数据模型) + W1-D1 (8/31 背景) 完成 W1 阶段 4/5 任务. W1-D4 是 DBA 前端 UX 实施用详细设计稿 (15-20KB, 实际 40KB 含详细 mockup + code), 跟 W1-D3 后端 + 领导汇报 refined + D2 数据模型形成 4 份文档梯度.

## 4 份设计稿梯度

| 文档 | 读者 | 篇幅 | 视角 |
|---|---|---|---|
| refined (`2026-08-31_ddl-sync-pair-design-refined.md`) | 领导汇报 | 42KB | 业务视角 (为什么做 / 痛点 / 影响 / 目标) |
| D2 数据模型 (`2026-09-01_ddl-sync-data-model.md`) | DBA 内部 | 14.6KB | 表结构视角 (3 张表 / ER 图 / migration) |
| W1-D3 实施 (`2026-09-01_ddl-sync-implementation-design.md`) | DBA 实施 (后端) | 46KB | API 契约 (service 拆分 / 5 端点 / 状态机 / perm) |
| **W1-D4 本次** (`2026-09-03_ddl-sync-detail-ux-design.md`) | DBA 实施 (前端) | 40KB | 前端 UX (5 按钮 modal / 工单详情页 / 字段 diff 联动) |

## 5 章节结构

1. **库对详情页 5 按钮 UX** — 一键配 / 批量导入 / 添加 / schema 差集 / 过滤规则 5 个 modal ASCII mockup
2. **业务库 DDL 工单详情页"本表已配置同步" 提示** — detail.html 新增 alert + 跳转链接到同步历史 + view 端 sync_pair_alert context
3. **字段 diff 端点复用** (跟 8/12 v0.3.x 联动) — 复用 column_diff 端点 + W1-D4 加 batch_schema_diff() 批量优化, 1589 张表 11.6s
4. **异常处理 (前端 perm 守卫 + modal 错误 UX)** — 复用 8/13 AJAX 守卫 + 前端守卫 2 教训, 5 按钮 + 4 角色全覆盖
5. **性能预算 + 134 dev 演练 5 Case** — 6 性能指标 + 5 Case 端到端 + 业务 RD mkq 浏览器实测

附录 A: 9/3 W1-D4 拍板记录 (4 拍板)
附录 B: 跟 W2 实施的接口契约 (9/7-9/11 按本文 §1-§5 落地)

## 关键拍板 (9/3 14:30, 假设)

- ✅ 命名/路径 `docs/designs/2026-09-03_ddl-sync-detail-ux-design.md`
- ✅ 5 章节结构 (跟 D3/refined/D2 形成梯度)
- ✅ 跟 W1-D3 互相引用不覆盖 (D3 后端 / D4 前端)
- ✅ 复用 8/12 字段 diff 端点 + W1-D4 加 batch_schema_diff() 批量优化

## 8/12 + 8/13 + 8/26 + 8/27 实战 4 教训应用

W1-D4 §3 §4 显式复用实战经验:
1. **8/12 字段 diff 联动**: 复用 column_diff 端点, 避免重复造轮子, 11 风险规则 + 8 维对比 都复用
2. **8/13 AJAX 守卫**: perm 守卫 JsonResponse(403) 不 raise PermissionDenied, 前端守卫覆盖全 5 按钮
3. **8/26 21:57 JS ReferenceError**: 复用时前端 JS 变量要 json.dumps + |safe (Django 4.0+ 没 escapejs filter)
4. **8/27 gh-ost 实战**: rollback 端点 + 端口探测 + poller staleness, 跟 W1-D3 §8 联动点 4 个一致

## 5 按钮 UX mockup

| 按钮 | 触发 | 后端端点 (W1-D3 §2) | 前端 modal (W1-D4 §1) |
|------|------|----------------------|------------------------|
| 🎯 一键配 | compute_diff + one_click_setup | POST /pair/<id>/one_click_setup/ | §1.2 ASCII mockup |
| 📥 批量导入 | bulk_import | POST /pair/<id>/bulk_import/ | §1.1 ASCII mockup |
| + 添加同步表 | add_table | POST /pair/<id>/add_table/ | §1.3 ASCII mockup |
| 🔍 schema 差集 | batch_schema_diff (新加) | GET /pair/<id>/schema_diff/ | §1.5 ASCII mockup |
| ⚙️ 过滤规则 | filter_rule (Phase 3) | POST /pair/<id>/filter_rule/ | §1.4 ASCII mockup |

## 业务库 DDL 工单详情页 alert 块

**入口**: detail.html 业务库 DDL 工单详情 (DBA 跟业务 RD 都能看到)
**新增 alert 块**: "本表已配置跨库同步" + 库对名 + 同步模式 + 同步状态 + 2 跳转链接
**联动**: v0.4.5 智能回滚 (失败时自动 drop 残留 _gho/_del) + 字段 diff 联动 (8/12 复用)

## 改动文件

- `docs/designs/2026-09-03_ddl-sync-detail-ux-design.md` (新文件, 40KB)
- `docs/changelogs/2026-09-03_ddl-sync-detail-ux-design.md` (本 changelog, 4.3KB)

## W1 进度

- W1 设计 (8/31-9/4): D1 ✓ (8/31 背景) / D2 ✓ (9/1 上午 数据模型) / D3 ✓ (9/1 下午 核心功能) / **D4 ✓ (本次 前端 UX)** / D5 待启动 (9/4)
- W1 进度 4/5 任务完成

## 下一步

- W1-D5 (9/4 周五): 134 dev 演练设计 + 推 110 主手册更新 (按 8/28 17:58 3 阶段 3 周 实施计划)
- W2 开发 (9/7-9/11): 按 W1-D3 + W1-D4 §1-§5 落地
- W3 提测上线 (9/14-9/18): 按 W1-D4 §5 端到端演练 + 业务 RD 实测

## 提交

待 commit + push origin main
