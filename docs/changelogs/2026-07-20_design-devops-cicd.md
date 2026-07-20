# 落档：DevOps / CI/CD / 部署设计文档 v0.8

**日期**：2026-07-20
**作者**：Mavis（辅助生成）+ 项目 owner
**影响范围**：`docs/designs/`
**风险等级**：低

## 背景

项目 owner 要求"开发 - 测试 - bug 修复 - 发布上线，整个流程自动完成"，并将 172.20.2.134 + dbops 账号提供作为部署目标。

本设计文档是配套 [钉钉 OA 联动设计 v0.7](./2026-07-20_dingtalk-oa-workflow.md) 的运维/CI/CD 侧设计。

## 改动内容

新建 `docs/designs/2026-07-20_devops-cicd.md`（v0.8，~41KB，12 章节）：

**已拍板的核心决策**：
- CI/CD 工具：GitHub Actions
- 部署触发：push to main 自动部署 staging；tag v* 触发生产（人工审批）
- 环境：dev/staging/prod 一体（用 systemd 多实例 + 端口区分）
- 服务架构：单机裸机 + 4 worker gunicorn + supervisor + nginx
- Redis：apt 安装 + 本地监听 + 密码保护
- 数据库：远程 172.20.2.134 MySQL 跑 migrate（用 dbops 账号）

**文档包含的完整脚本**：
- `01_init_server.sh`：服务器初始化（系统包 + Redis + 防火墙 + 用户）
- `02_deploy.sh`：通用部署脚本（拉代码 → 装依赖 → migrate → 重启 → 健康检查）
- `03_rollback.sh`：回滚脚本
- `04_backup.sh`：每日备份脚本
- 完整 GitHub Actions workflow（ci.yml / cd-staging.yml / cd-prod.yml）
- supervisor + nginx + systemd 配置
- Runbook（故障排查手册）

**核心架构亮点**：
- 30 秒回滚：tag-based 版本管理
- 人工审批门：GitHub Environments + Required reviewers
- 健康检查自动回滚：部署后 curl /healthz 失败则自动 rollback
- agent 不直接 SSH：所有远程操作由 GitHub Actions 执行

## 涉及文件

| 文件 | 状态 | 行数 |
|------|------|------|
| `docs/designs/2026-07-20_devops-cicd.md` | 新建 | ~1100 |
| `docs/changelogs/2026-07-20_design-devops-cicd.md` | 新建（本文件）| ~50 |

## 与 v0.7 钉钉 OA 设计的协同

| 共享 | 差异 |
|------|------|
| 共享 `172.20.2.134` 服务器 | v0.7 关注业务功能（钉钉 OA 联动）|
| 共享 `.env` 配置管理 | v0.8 关注交付链路（CI/CD）|
| 共享 IP 白名单（钉钉回调）| v0.7 关注审批流 |
| 共享 supervisor / systemd | v0.8 关注测试/部署/监控 |

## 后续步骤

- [ ] owner 拍板 §11 全部子决策
- [ ] 仓库推到 GitHub（**必需**，才能用 GitHub Actions）
- [ ] 配 GitHub Secrets：SSH_PRIVATE_KEY / DINGTALK_NOTIFY_WEBHOOK
- [ ] 服务器初始化（在 172.20.2.134 上跑 01_init_server.sh）
- [ ] 上线 CI workflow
- [ ] 演练一次完整部署
- [ ] v0.7 + v0.8 联调（部署时同时验证钉钉 OA 兜底）

## 回滚方案

```bash
git revert HEAD  # 或
git reset --hard HEAD~1
```

回滚仅影响 docs/ 目录。
