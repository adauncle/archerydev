# 推 110 范围瘦身: 只推 gh-ost + 字段 diff (用户 17:00 拍板, 17:02 拍板 detail.html 4 fix 跟着推)

> **拍板时间**: 2026-08-26 17:00 (瘦身) + 17:02 (detail.html 4 fix 跟着推)
> **执行人**: mavis
> **影响范围**: 推 110 主手册 §1.1 / §1.5 / §3.6
> **推 110 时间**: 不变, 8/26 周三 19:00 (今晚 7 点)

## 1. 拍板背景

用户 17:00 拍板: 推 110 范围瘦身, 只推 gh-ost + 字段 diff 相关代码。
原计划 35+ commit 推 110 范围 (v0.3.0-beta + v0.4.5 + 8/24 6 bug fix + 权限细分 + DDL 智能回滚 + 8/17 dashboard + W1+W2 摸头 + /dbaprinciples/ 修复 + v0.4.5 选表页面)
瘦身到 56 commit 强相关。

用户 17:02 拍板: detail.html 业务路径 4 个 fix 也要跟着推 (影响 gh-ost / 字段 diff 工单 detail 页稳定性), 范围扩到 61 commit (代码 55 + 物料 6)。

## 2. 范围变化对照

### 2.1 保留 61 commit (代码 55 + 物料 6)

**A. 推 110 代码 commit (55)**:

| 类别 | 数量 | 关键 commit |
|------|------|-------------|
| gh-ost v0.3.0-beta + 字段 diff 检测 | 21 commit | 4f34a81, c0f42b3, 2c5a0b7, 47728bb, f87e875, 1f32976, fba0564, 70fcf47, 8ddc59a, 04ae0aa, 664058c, 2129221, 853bf6a, 461152d, 281fbeb, 36eb885, 3eb63f7, 4376553, 9eb6c9e, 14fa9f4, 374d990 |
| gh-ost v0.4.5-alpha (rebuild service + 演练) | 6 commit | 6412da4, e8b2cf3, 52b875b, e4a3707, a982d62, 8e40d26 |
| gh-ost v0.4.5 (DDL 智能回滚 + 3 决策) | 2 commit | e54a663, 4bece6a |
| **gh-ost v0.4.5 选表页面 (方案 B)** | **8 commit** | 3c00e69, 36c554e, 03c223f, 24a2498, 81a5097, 14e3007, 78ed4bb, 24200bd |
| gh-ost 任务管理列表页 + 权限组细分 | 4 commit | c80c1ad, 727f046, 2d27a4a, eb5937b |
| gh-ost / 字段 diff bug fix (8/24 + 8/25) | 6 commit | 9d66064, e669567, 0b62856, 76d48cc, ac7e929, f76282e |
| 灰色保留 (gh-ost 业务路径) | 7 commit | 14e3007, 03c223f, 24a2498, 324a53a, eaf9853, a41c4d0, d5f88d1 |
| **detail.html 业务路径 4 fix (17:02 拍板跟着推)** | **4 commit** | 853cb71, d44632f, b8c0e6d, e78f758 |
| **代码小计** | **55 commit** | |

**B. 推 110 必走物料 commit (6)**:

| 类别 | 数量 | 关键 commit |
|------|------|-------------|
| 5 步必做脚本 (8/25 补到 13 步) | 1 | 7c2003c |
| 回滚演练 v2 DRY_RUN 模式 | 1 | 71e5b3b |
| 3 份备份 + 回滚 4 步脚本 | 1 | f1d7b49 |
| 推 110 必做补步骤 13 (8/24 教训) | 1 | ce6a364 |
| 推 110 完整执行手册 | 1 | f44c26e |
| goinception D+1 升级演练 + drill | 1 | a7ff19e |
| **物料小计** | **6 commit** | |

**总计 61 commit** (代码 55 + 物料 6)

### 2.2 砍掉 28 commit (代码 86 - 保留 58 = 28)

| 类别 | commit | 理由 |
|------|--------|------|
| dashboard 优雅降级 | a16b803 | 不在 gh-ost / 字段 diff 范围 |
| /dbaprinciples/ 修复 | 0c94576 | 不在 gh-ost / 字段 diff 范围 |
| 装 sqladvisor | 7106be3 | 工具, 不属于 gh-ost / 字段 diff |
| 钉钉 OA 全栈 | abe7f66, d9a5d3b, 3a850fb, 85d859e, cb5b0b5, edf7b26, 78158a3, 457590e, aaa9ecf | 框架未启用, 不在 gh-ost / 字段 diff 范围 |
| 通用 settings.py / static 修复 | 1a9aea0, 5eefa3a, f366066, 982e88d, 5f6b59b, dd2d9d1, 4273a3f | 不在 gh-ost / 字段 diff 范围 |
| goInception 装 + reencrypt + setup | 588c7d9, a5b7a14, 052893c, 913eb5d | 工具, 8/18 摸底已装好, 推 110 不重复 |
| 推 110 工具 | a5471b3, 09d3cc2 | 不在 gh-ost / 字段 diff 范围 |

> [注] 文档/计划/演示稿 (d99c7bf / 8d78389 / 7ab3c40 / f1699bb / 5d6390c / 9c7d4ee / 0dbf21e / 151dc64 / 6f2d922 / 286585b / 65234fd / 360e526 / a389d74 / 2ccf5ea / c34ffca) 跟推 110 物料分开, 不在 sql/common/archery/*.py 范围, 演示稿本地查不推 110, 主手册保留 (f44c26e)。

## 3. 关键决策 (3 个灰色判断, 已跟用户确认)

### 决策 1: `a41c4d0` ConfigurableAuditor 走上游 WorkflowAuditSetting — 保留
- gh-ost 工单 detail 页审批流必走, 8/24 重大 bug
- 不推 110 prod, gh-ost 工单 detail 页审批流 == 提交页审批流 不成立

### 决策 2: `d5f88d1` 审批流 3 级配置 v0.1.4 占位修复 — 保留
- 跟 a41c4d0 是一对, 不推 110 prod 审批流配置可能是占位 "3"
- 110 prod v0.2.0 8/05 推时可能已修, 但保险起见保留

### 决策 3: `a7ff19e` goinception D+1 升级工单 — 保留
- D+1 升级是 gh-ost 走 inception 路径必走, 8/19 实战 D+1 工单已跑通

## 4. 17:02 用户拍板 detail.html 4 fix 跟着推 (历史决策记录)

### 原风险 (8/26 17:00 拍板时引入)
- 用户 17:00 拍板"只推 gh-ost + 字段 diff"时, 砍掉 4 个 detail.html 业务路径 fix
- 影响: gh-ost / 字段 diff 工单 detail 页也走老 detail.html / workflow 路径, 4 个边缘 case 可能 500:
  1. review_content=空 dict 的工单 detail 页 detail_content rows 渲染错 (853cb71 修的)
  2. data-toggle=table auto-init 触发 for of undefined JS 错 (d44632f 修的)
  3. 审批流未配置 (空配置) 的工单 detail 页审批流区段 500 (b8c0e6d 修的)
  4. 老工单 detail_content KeyError 兜底缺失, 偶发 500 (e78f758 修的)

### 17:02 用户拍板
- detail.html 4 fix 跟着推, 风险解除
- 理由: gh-ost / 字段 diff 工单 detail 页稳定性 + 110 prod 业务 RD 量级比 134 dev 大, 4 个边缘 case 风险不能接受

### 现在
- 4 fix 全部进推 110 物料 (见 §1.1 范围表)
- §1.5 风险 5 标记"已解除" (保留作为历史决策记录)
- 5+1 端点验证不需要额外加端点, 端点 5 = /sqlsubmit/ 走业务 RD 账号 已经覆盖 detail 页路径

## 5. 5 步必做 13 步同步调整

### 调整 1: 步骤 11 验证目标改为"8/24 gh-ost / 字段 diff bug fix + detail.html 4 fix"
- 原: 8/24 6 bug fix verify
- 新: 8/24 10 bug fix verify (gh-ost / 字段 diff 6 + detail.html 4)
- 验证方式: `stat -c '%y %n' <file>` 看 mtime 是不是 8/24

### 调整 2: 步骤 13 configurable_auditor 8/24 修法不变
- 跟 a41c4d0 commit 对应, 110 prod 推完后走 Archery 上游 WorkflowAuditSetting 拿配置
- 不走 ext_approval_flow 旧配

## 6. 端点验证 5+1 调整

### 端点 5 (/sqlsubmit/) 增加验证目标
- 原: SQL 提交页 + 大表 DDL 防呆
- 新: SQL 提交页 + 大表 DDL 防呆 + **detail.html 4 fix 生效** (走业务 RD 账号, 提一条新工单看 detail 页 200)

### 端点 6 (/gh_ost/rebuild/select/) 不变
- v0.4.5 选表页面 + 3 筛选器 + FILE_SIZE 算法

## 7. 推 110 范围瘦身的优势

1. **风险更小**: 26 commit 无关代码不进 110 prod, 边缘 case 风险少
2. **业务价值更聚焦**: 业务 RD 推 110 后立即能用 gh-ost 无锁 DDL + 字段 diff 检测
3. **回滚更稳**: 回滚 SLA 5 分钟, 范围小了回滚验证更简单
4. **9 月 5.7→8.0 升级更顺**: gh-ost / 字段 diff 已经是稳定基线, 升级时只动 gh-ost 相关代码

## 8. 推 110 范围瘦身的劣势

1. **业务 RD 不能立即用**: 钉钉 OA / dashboard / /dbaprinciples/ 修复 / 通用 settings.py 修复 都没推, 业务 RD 用这些功能时还是老行为
2. **9 月再推一轮**: 钉钉 OA / dashboard / /dbaprinciples/ 修复 / 通用 settings.py 修复 9 月单独发版 (5.7→8.0 升级前后)

## 9. 教训 (跨项目可复用)

1. **推 prod 范围可以分批**: 不必把所有改动都塞到一次推 prod, 按业务价值 (gh-ost / 字段 diff) 拆批
2. **detail.html / workflow 业务路径通用 fix 跟着功能走**: 业务路径通用 fix 不在功能 commit message 里, 但影响功能业务路径稳定性, 应该跟着功能一起推
3. **用户拍板可以快速调整**: 用户 17:00 拍板 56 commit, 17:02 拍板 60 commit, 2 分钟内拍板回滚, 决策灵活
4. **5+1 端点验证能覆盖 detail 页**: 端点 5 = /sqlsubmit/ 走业务 RD 账号提新工单, detail 页路径就走过了, 不需要额外端点

## 10. 关联

- **推 110 主手册**: `docs/runbooks/2026-08-27_push-v030-execution-manual.md` (§1.1 + §1.5 风险 5 解除 + §3.6 5+1 端点)
- **commit (待)**: 修改后 commit + push
- **8/26 16:34 拍板**: 推 110 时间 8/27 21:00 → 8/26 19:00 (commit `204cea9`)
- **8/26 11:24 qcluster hang 修复**: 134 dev qcluster 重启, 推 110 前 110 prod qcluster 必重启 (跟 134 dev 一样 pkill + nohup)
- **8/26 11:42 workflow #102 is_backup 修复**: 业务 RD 现在重新点"立即执行"就能跑通
