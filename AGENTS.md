# AGENTS.md

> 给 AI 编码 agent（Mavis / Claude Code / Cursor / Codex 等）看的项目工作手册。
> 必读 —— 在改任何代码前先看一遍。

## 项目一句话

基于 [Archery](https://github.com/hhyo/Archery)（SQL 审核平台）v1.14.0 的**二次开发项目**。
所有定制需求都服务于内部业务场景，不要尝试替换或重写上游核心。

## 技术栈速查

- **后端**：Python 3.11 / Django 4.x / DRF
- **前端**：Vue 2 + Element UI（上游默认）
- **数据库**：MySQL 8.0（应用库 + 业务库元数据）
- **缓存与队列**：Redis 7 + Celery
- **关键第三方库**：`sqlparse`、`mysql-connector-python`、`pyjwt`、`djangorestframework`

## 目录与模块映射

| 路径 | 用途 | 改动建议 |
|------|------|----------|
| `archery/settings.py` | Django 配置 | 极慎重，优先用环境变量 |
| `sql/` | SQL 审核/执行/查询/工单 | 二次开发最常改的模块 |
| `common/` | 用户/权限/菜单/认证 | 改动会全局影响 |
| `sql_api/` | 内部 REST API | 增加端点优先放这里 |
| `dashboard/` | 仪表板/统计 | 改动相对独立 |
| `docs/changelogs/` | 变更日志 | **每次提交都要新增一个** |
| `patches/` | 上游补丁（如用 patch 模式） | 同步上游时需要重放 |

## 二次开发硬规则

1. **不改上游文件，除非必要** —— 必须改时：
   - 在文件顶部加 `## CUSTOM-MODIFIED: <reason> @ <date> @ <author>` 注释
   - 在 `docs/changelogs/` 写明
2. **新功能优先用 Django app 隔离** —— 在 `sql/extensions/` 或新增 `custom_xxx/` app
3. **配置走环境变量** —— 不在 settings.py 硬编码
4. **变更必带 changelog** —— 路径 `docs/changelogs/YYYY-MM-DD_<short-name>.md`
5. **不要往仓库提交** —— 凭据、`.env`、`*.sql` 数据、真实的 SQL 审核日志
6. **前端改动优先复用** Element UI 组件，不要引入新框架
7. **每个 bug / 踩坑 / 解决方式都要记录** —— **核心原则 (用户 2026-08-11 固化)**:
   - 修一个 bug：先写 `docs/changelogs/YYYY-MM-DD_<bug-name>.md`（含症状 / 根因 / 修法 / 验证），再写代码，最后 commit
   - 踩一个坑（不用修代码）：写进 agent memory（`MEMORY.md` 或 topic file），含触发场景 / 解决方式 / 同源 entry
   - 修架构 / 改 API 之类大改：既要 changelog 也要 memory
   - **不允许**"修完代码直接 commit，文档后补"——文档必须跟代码同 commit（或更早）

## 关键约定速记

- Python 包用 `pip-tools` 锁版本，新加依赖要写进 `requirements.in` 并 `pip-compile`
- 数据库迁移用 Django 标准 `makemigrations` + `migrate`
- **定时任务用 `django-q2`**（项目用 `django_q.tasks.schedule` + `django_q.models.Schedule`，**没有 Celery**）—— 写定时函数放 `tasks.py`，但不要 `from celery import shared_task`；要兼容 Celery 风格就 try/except 装饰器
- API 视图用 DRF 的 `APIView` 或 `ViewSet`，不要混用 FBV
- 测试用 `pytest-django`，关键业务逻辑必须有覆盖
- `archery/settings.py` 用 `django-environ 14`，`env()` 第二个位置参数是 **cast 不是 default**——必须用关键字 `env("X", default=...)`，否则 `'bool' object is not callable` 启动崩溃（**真实踩坑：2026-07-20 钉钉 OA settings 段**）

## 常用命令

```bash
# 启动开发栈
docker-compose up -d

# 查看日志
docker-compose logs -f archery

# 进入容器
docker-compose exec archery bash

# Django 命令
docker-compose exec archery python manage.py <command>

# 运行测试
docker-compose exec archery pytest tests/

# 同步上游（rebase 模式）
git fetch upstream && git rebase upstream/master
```

## 提交规范

```
<type>(<scope>): <subject>

<body>

<footer>
```

- `type`: `feat` / `fix` / `refactor` / `docs` / `chore` / `test`
- `scope`: 涉及模块，如 `sql`、`auth`、`frontend`、`docs`
- `subject`: 中文或英文，简短说明改动
- `footer`: 关联 `CHANGELOG: docs/changelogs/xxx.md`

## 遇到问题先看

1. `docs/customization.md` —— 二次开发规范
2. `docs/architecture.md` —— 模块结构
3. `docs/troubleshooting.md` —— **踩坑速查表（按现象反查 changelog / memory）**
4. `docs/changelogs/` —— 历次变更历史
5. 上游 [Archery 官方文档](https://github.com/hhyo/Archery/wiki)

## 不在 AI agent 职责内

- 生产环境部署（需要人工审批）
- 真实凭据、连接串
- 删除/重置数据库
- 任何与外部系统的 DDL/DML
