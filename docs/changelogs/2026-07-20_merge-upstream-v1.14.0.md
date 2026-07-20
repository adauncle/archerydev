# 合入 Archery 上游 v1.14.0 源码

**日期**：2026-07-20
**作者**：Mavis（辅助）+ 项目 owner
**影响范围**：整个仓库
**风险等级**：低（脚手架已就绪，源码原样合入）

## 背景

`AGENTS.md` 与 `README.md` 阶段建好的脚手架是空壳，需要把上游 Archery v1.14.0 源码
合入才能作为可运行项目继续开发。

## 改动内容

### 合入的上游内容

- `manage.py` —— Django 入口
- `archery/` —— Django 项目配置（`settings.py` 514 行、`urls.py`、`wsgi.py`、`asgi.py`）
- `sql/` —— SQL 审核/查询/工单核心模块
  - `models.py` 1387 行（含 Workflow/Instance/Audit/User 等）
  - `engines/` 16 个数据库引擎：mysql、pgsql、oracle、mssql、mongo、redis、clickhouse、doris、elasticsearch、odps、tdengine、phoenix、cassandra、memcached、goinception、cloud
  - `services/`、`plugins/`、`utils/`、`templates/` 等子模块
  - `test_*.py` 完整测试集
- `common/` —— 公共组件（auth、authenticate/、middleware/、twofa/、templates/、utils/）
- `sql_api/` —— 内部 REST API（api_instance / api_sqlquery / api_user / api_workflow）
- `src/` —— 前端源码（charts/、plugins/、init_sql/、script/、docker-compose 等）
- `dashboard/` —— 仪表板（上游版本）
- `downloads/` —— 离线下载
- `specs/` —— 规格
- `logs/` —— 日志占位
- `.github/` —— 上游 CI（black.yml / ci.yml / codeql-analysis.yml / django.yml / docker-image.yml 等）+ agents/ + prompts/
- `pyproject.toml`、`dev-requirements.txt`、`.gitattributes`、`.dockerignore`、`.env.list`
- `admin.sh`、`debug.sh`、`startup.sh`、`masking.sh`、`supervisord.conf`、LICENSE、CODE_OF_CONDUCT.md、CONTRIBUTING.md、conftest.py

### 二次开发脚手架（保留）

- `AGENTS.md`、`README.md`
- `docker-compose.yml`、`Dockerfile`、`docker/nginx/nginx.conf`
- `.env.example`、`pytest.ini`、`.editorconfig`
- `docs/architecture.md`、`docs/customization.md`、`docs/dev-setup.md`、`docs/release.md`
- `docs/changelogs/` 与首个 changelog
- `scripts/init.sh`、`scripts/pull-upstream.sh`、`scripts/mysql/init/`
- `sql/extensions/README.md`（内部扩展隔离区说明）
- `.github/workflows/ci.yml`（我们自己的 CI，测试 Django + pytest）
- `tests/conftest.py`（pytest 基础）

### 合并处理

- `requirements.txt` —— 合并上游全部依赖 + 开发/测试/内部定制补充
- `.gitignore` —— 合并上游 + 二次开发项目通用项
- 上游 `docs/` 内容移到 `docs/upstream/`（保护我的开发规范不被覆盖）
- 上游 `scripts/` 内容移到 `scripts/upstream/`
- `archery/settings.py` **暂未改动** —— 仍跑上游默认；后续按需改造以读 `.env`

## 涉及文件（数量）

- 新增 554+ 个目录/文件
- 合并修改 2 个（requirements.txt、.gitignore）
- 移动 2 个目录（docs/upstream/、scripts/upstream/）

## 后续步骤

- [ ] 验证 `archery/settings.py` 跑得起来（跑 `python manage.py check`）
- [ ] 根据需要改造 `settings.py` 读 `.env`
- [ ] 跑 `docker-compose build` 验证镜像能构建
- [ ] 启动开发栈，初始化数据
- [ ] 在 `sql/extensions/` 下建第一个内部 app 的占位
- [ ] 与 owner 确认首个定制 feature

## 回滚方案

```bash
git revert HEAD  # 或
git reset --hard <上一个 commit>
```

## 同步上游约定

后续要同步上游新版本时：

```bash
git remote add upstream https://github.com/hhyo/Archery.git  # 首次
git fetch upstream
bash scripts/pull-upstream.sh
```

冲突重点关注：

- 标记 `## CUSTOM-MODIFIED:` 的文件
- `archery/settings.py`（一旦二次开发改过）
- `requirements.txt`（合并依赖）
- `migrations/`（数据库迁移）
