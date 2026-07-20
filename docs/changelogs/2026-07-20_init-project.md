# 项目初始化

**日期**：2026-07-20
**作者**：Mavis (辅助生成)
**影响范围**：整个仓库
**风险等级**：低

## 背景

基于 [hhyo/Archery](https://github.com/hhyo/Archery) v1.14.0 启动二次开发项目。
当前仓库只包含脚手架与文档，未合入上游代码。

## 改动内容

- 创建项目目录结构（archery/sql/common/sql_api/dashboard/extensions/...）
- 编写 `README.md`、`AGENTS.md`、`docs/customization.md`、`docs/architecture.md`、`docs/dev-setup.md`、`docs/release.md`
- 提供 `docker-compose.yml` + `Dockerfile` 本地开发编排
- 提供 `.env.example`、`requirements.txt` 模板
- 制定二次开发规范与 changelog 流程

## 涉及文件

- `README.md` —— 新建
- `AGENTS.md` —— 新建
- `docs/customization.md` —— 新建
- `docs/architecture.md` —— 新建
- `docs/dev-setup.md` —— 新建
- `docs/release.md` —— 新建
- `docs/changelogs/2026-07-20_init-project.md` —— 本文件
- `docker-compose.yml` —— 新建
- `Dockerfile` —— 新建
- `.env.example` —— 新建
- `requirements.txt` —— 新建
- `.gitignore` —— 新建
- 各模块占位 `__init__.py` —— 新建

## 后续步骤

- [ ] 合入 Archery 上游代码（见 `docs/dev-setup.md` 第 2 节）
- [ ] 启动 `docker-compose up -d --build` 验证基础栈
- [ ] 与用户确认二次开发的具体方向

## 回滚方案

`git reset --hard HEAD~1` 即可（尚未合入上游时）。
