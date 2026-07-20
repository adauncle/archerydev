# 落档：钉钉 OA 联动变更工单设计文档

**日期**：2026-07-20
**作者**：Mavis（辅助生成）+ 项目 owner
**影响范围**：`docs/designs/`
**风险等级**：低

## 背景

落档"Archery 变更工单联动钉钉 OA 审批"二次开发需求的完整设计方案。

业务诉求是让 SQL 变更工单按风险等级走两套审批流（普通/重大），通过钉钉 OA 智能工作流承接审批，审批路由由 SQL 类型 + 业务表 + 影响行数三维度判定。

## 改动内容

- 新建 `docs/designs/2026-07-20_dingtalk-oa-workflow.md`（v0.7，~73KB，13+ 章节）
- 设计经过 6 次迭代：

| # | 主题 | 决策 |
|---|------|------|
| 1 | 钉钉 OA 地位 | driver 完全可配置（替代 A/B/C 三选一）|
| 2 | SQL 判定粒度 | 细粒度到 SQL 类型（INSERT/UPDATE/ALTER/DROP/...）|
| 3 | 业务表判定 | CoreBusinessTable + 等级 L1/L2/L3 |
| 4 | 影响行数 | DML 类按行数区间判定 |
| 5 | 流程独立化 | ApprovalFlow 独立模型，用户可任意定义 |
| 6 | 兜底 + 安全 | §10.4 自动降级 + §10.5 钉钉安全设计 |

**核心架构**：
- `ConfigurableAuditor` 替换上游 `AuditV2`（继承方式，零侵入）
- `DRIVER_REGISTRY` 注册制，未来加飞书/企微 OA 改 1 行
- 三维策略匹配：SQL 类型 ∩ 业务表 ∩ 影响行数，priority 决出胜负
- 钉钉 OA 为主审批 + 本地 Group 审批为镜像
- 钉钉异常时自动降级到本地 Group 审批，30 秒可全局回滚
- 钉钉回调完整签名校验 + AES 解密 + 幂等 + IP 白名单 + 限流

**改动范围（实施后预计）**：
- 新增：`sql/extensions/dingtalk_oa/` 约 25 个 .py 文件
- 修改：`archery/settings.py` 7 行（env 注入）
- 修改：`archery/urls.py` 4 行（include 新路由）
- **不动**：`sql/`、`common/` 核心代码

## 涉及文件

| 文件 | 状态 | 行数 |
|------|------|------|
| `docs/designs/2026-07-20_dingtalk-oa-workflow.md` | 新建 | ~2000 |
| `docs/changelogs/2026-07-20_design-dingtalk-oa.md` | 新建（本文件）| ~50 |

## 后续步骤

- [ ] owner 拍板 §11 全部子决策
- [ ] 输出最终版设计 + 第一阶段任务清单
- [ ] 拍板后开始动代码（第一阶段：基础架构 + 7 个模型 + migration）
- [ ] 钉钉后台准备 OA 应用、模板、回调 URL（阶段 0）
- [ ] 团队 review 设计文档

## 回滚方案

```bash
git revert HEAD  # 或
git reset --hard HEAD~1
```

回滚仅影响 docs/ 目录，不影响任何代码。
