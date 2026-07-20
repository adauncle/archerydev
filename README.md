# Archery 二次开发平台

> 基于 [hhyo/Archery](https://github.com/hhyo/Archery) v1.14.0 的二次开发项目

## 项目简介

本项目在开源 SQL 审核平台 [Archery](https://github.com/hhyo/Archery) 基础上做二次开发，
用于满足内部特定的 SQL 审核、查询、权限管理、数据脱敏等场景需求。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11 + Django + Django REST Framework |
| 前端 | Vue + Element UI |
| 数据库 | MySQL 8.0 |
| 缓存/队列 | Redis 7 |
| 任务调度 | Celery |
| 部署 | Docker / Docker Compose |
| 反向代理 | Nginx |

## 目录结构

```
archery_dev/
├── archery/                  # Django 主项目配置
├── sql/                      # SQL 审核/查询核心模块
├── dashboard/                # 仪表板模块
├── common/                   # 公共组件（认证、菜单、权限等）
├── sql_api/                  # 内部 API
├── src/                      # 前端 Vue 源码（如有定制）
├── docs/                     # 项目文档
│   ├── changelogs/           # 变更日志（按 feature/bugfix 拆文件）
│   ├── architecture.md       # 架构与模块说明
│   ├── dev-setup.md          # 本地开发环境搭建
│   ├── customization.md      # 二次开发规范与约定
│   └── release.md            # 发布/升级流程
├── scripts/                  # 运维、初始化脚本
├── patches/                  # 上游 patch（如以 patch 方式管理定制）
├── tests/                    # 测试代码
├── .github/workflows/        # CI/CD
├── docker/                   # Docker 相关文件
├── docker-compose.yml        # 本地开发编排
├── Dockerfile                # 应用镜像
├── requirements.txt          # Python 依赖
├── .env.example              # 环境变量模板
└── AGENTS.md                 # 给 AI 编码 agent 看的项目说明
```

## 快速开始

```bash
# 1. 复制环境变量
cp .env.example .env
# 编辑 .env，填入数据库/Redis 等配置

# 2. 启动开发栈
docker-compose up -d

# 3. 初始化数据库
docker-compose exec archery python manage.py migrate
docker-compose exec archery python manage.py loaddata initial_data
```

详细步骤见 [docs/dev-setup.md](docs/dev-setup.md)。

## 二次开发约定

请先阅读 [docs/customization.md](docs/customization.md) 再开始改代码。

核心约定：

1. **变更记录** —— 每次提交要在 `docs/changelogs/` 下加一个说明文件
2. **避免改上游核心** —— 优先通过配置、插件、子模块扩展，而非直接改 `sql/`、`common/` 等核心文件
3. **保持可升级** —— 写清楚变更影响范围，方便后续与上游版本同步
4. **写测试** —— 涉及业务逻辑的改动要附带单元测试

## 同步上游

```bash
git remote add upstream https://github.com/hhyo/Archery.git
git fetch upstream
git merge upstream/master  # 或 rebase，视团队策略
```

## 许可证

本项目遵循 Apache 2.0（与上游一致）。内部定制代码版权归本组织所有。
