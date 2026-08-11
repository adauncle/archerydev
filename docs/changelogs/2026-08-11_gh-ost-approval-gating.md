# 2026-08-11 · v0.3.0-beta gh-ost 审批守卫

> **作者**: mavis  · **面向 DBA 验收 + 后续 110 PROD 推 v0.3.0 参考**

## 一句话

修一个真 bug：用户提交工单勾选"启用 gh-ost"后，**审批前就能在详情页点启用按钮，绕过审批流程**。
本次让 gh-ost 启用必须等审批通过，同时把提交人勾选语义改清晰（"申请" vs "立即启用"）。

## 问题

8/11 用户浏览器验证发现：

1. RD 提交工单，勾选"启用 gh-ost"（提交页底部蓝色 checkbox）
2. 工单进入 `workflow_manreviewing` 状态
3. **DBA 还没点"通过"，RD 在自己工单详情页就能点"启用 gh-ost"按钮**
4. 详情页的"启用 gh-ost"按钮状态守卫太宽：`status in ("workflow_manreviewing", "workflow_review_pass", "workflow_timingtask")`

业务上冲突：gh-ost 启用应该等审批通过才能开跑，否则提交人能"自审批"。

## 修法（B 干净版）

| 改动 | 位置 | 干什么 |
|------|------|--------|
| 1. 加 `enable_gh_ost` 字段 | `sql/models.py` SqlWorkflow | 标记"提交人申请启用 gh-ost"（保留事实，不写 task）|
| 2. 收紧按钮守卫 | `sql/views.py` detail | `can_enable_ghost` 去掉 `workflow_manreviewing`，仅 `review_pass` + `timingtask` |
| 3. submit 改存标记 | `sql_api/api_workflow.py` | 勾了 → `wf.enable_gh_ost = True`，**不**调 `_enable_ghost_for_workflow` |
| 4. lazy auto-enable | `sql/views.py` detail | 渲染前检测 `enable_gh_ost=True` + `status=review_pass` + 没 task → 自动调 enable |
| 5. 拒绝清理脏数据 | `sql/sql_workflow.py` | 拒绝/abort 时把所有非终态 DdlGhostTask 标 cancelled |
| 6. 审批前提示 | `sql/templates/detail.html` | 显示"已申请 gh-ost 等待审批"黄色 alert，替代按钮 |

## 关键决策

1. **"申请"vs"启用"语义分离**：
   - 提交时勾 = "我打算用 gh-ost"（声明意图）
   - 详情页点"启用"= "确认要用 gh-ost，跑起来"（真正启用）
   - 拆开后：申请早，启用晚
2. **lazy auto-enable 在 detail 视图**：
   - 不用 audit pass 后立刻调（要在 db commit 之后才安全）
   - 简单方案：访问 detail 时检测，触发 enable，下次访问看到 task
3. **拒绝时标记保留，task 清理**：
   - 标记是"申请事实"，业务上保留可审计
   - 任何挂的 DdlGhostTask 是"未跑完的活"，拒绝时必须清
4. **schema 用 SQL 直管**：
   - `sql_workflow` 表不走 Django migration（项目约定，上游 SQL 管 schema）
   - 手写 `ALTER TABLE sql_workflow ADD COLUMN enable_gh_ost TINYINT(1) NOT NULL DEFAULT 0;`
   - 已部署 134 dev

## 端到端验证（134 dev 演练）

演练表：`archery_dev.accesscard_black_detail`（433k 行）

| Case | 验证 | 结果 |
|------|------|------|
| A | 提交勾 gh-ost + 审批前 → 详情页显示"已申请"提示，**没**启用按钮 | ✅ |
| B | 提交勾 gh-ost + 审批通过 → 详情页 lazy auto-enable 创建 DdlGhostTask | ✅ |
| C | 审批通过 + 启动 → cut-over success → wf.status 自动切 workflow_finish | ✅ |
| D | 提交勾 gh-ost + 审批拒绝 → DdlGhostTask 清理 + `enable_gh_ost` 标记保留 | ✅ |
| E | 未勾 gh-ost + 审批通过 → 不 auto-enable，详情页有启用按钮（保持原状）| ✅ |

5 Case 全部通过。

## 变更文件清单

| 文件 | 变更 |
|------|------|
| `sql/models.py` | SqlWorkflow 加 `enable_gh_ost: BooleanField(default=False)` |
| `sql/views.py` | detail 视图：can_enable_ghost 守卫去 manreviewing + lazy auto-enable + 新增 context 字段 |
| `sql/sql_workflow.py` | 拒绝/abort 路径：清理非终态 DdlGhostTask + import settings/timezone |
| `sql_api/api_workflow.py` | submit 接口：勾选只存标记，不调 enable |
| `sql/templates/detail.html` | 审批前显示"已申请 gh-ost"黄色 alert |
| `docs/changelogs/2026-08-11_gh-ost-approval-gating.md` | 本 changelog |
| `scripts/drill_v030b_approval_gating.py` | 5 Case 端到端演练 |
| `scripts/pack_v030b_approval.py` | 打包脚本 |

## 110 PROD 推 v0.3.0 前必做

1. ✅ `chown -R archery:archery /var/log/archery/gh_ost`
2. ✅ `rm -f /tmp/gh-ost.*.sock`
3. ✅ drop 残留 `_gho/_del/_ghc` 影子表
4. ✅ DBA 手动从 admin 后台重新保存 instance user/password + sql_config SysConfig
5. ⚠️ **新增**：`mysql -h... -e "ALTER TABLE sql_workflow ADD COLUMN enable_gh_ost TINYINT(1) NOT NULL DEFAULT 0;"`（同步 schema）

## 关联设计

- `docs/designs/2026-08-10_gh-ost-detail-design.html` §7.3 状态机
- `docs/designs/2026-08-05_gh-ost-product-design.html` §启用 gh-ost
