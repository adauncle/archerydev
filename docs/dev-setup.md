# 本地开发环境搭建

## 前置条件

- Docker >= 24 + Docker Compose v2
- Git
- 4GB+ 可用内存
- 端口可用：80（nginx）、3306（mysql）、6379（redis）、9123（archery）

> 团队开发机推荐 16GB 内存，Archery 启动后比较吃内存。

## 1. 初始化

```bash
# 克隆（已初始化过的跳过）
git clone <你的仓库地址> archery_dev
cd archery_dev

# 复制环境变量
cp .env.example .env
# 编辑 .env，至少改 SECRET_KEY、MYSQL_PASSWORD
```

## 2. 合入 Archery 上游代码

> 当前仓库只包含二次开发的脚手架，需要把上游源码拉下来。

```bash
# 添加上游 remote
git remote add upstream https://github.com/hhyo/Archery.git
git fetch upstream

# 选择要基于的版本
git checkout -b feat/init v1.14.0   # 以 tag 形式
# 或
git checkout -b feat/init upstream/master  # 最新 master

# 把上游代码 merge 进来
git merge upstream/master --allow-unrelated-histories

# 解决冲突后提交
```

> 也可以直接 `git clone` 上游到临时目录，复制 `archery/`、`sql/`、`common/`、`sql_api/`、`dashboard/`、`requirements.txt` 等核心文件到本仓库。

## 3. 启动开发栈

```bash
# 构建镜像并启动
docker-compose up -d --build

# 查看日志
docker-compose logs -f archery
```

## 4. 初始化数据

```bash
# 跑迁移
docker-compose exec archery python manage.py migrate

# 加载初始数据（用户、菜单、资源组）
docker-compose exec archery python manage.py loaddata initial_data

# 创建超级用户
docker-compose exec archery python manage.py createsuperuser
```

## 5. 访问

- Web UI：http://localhost
- 直连 gunicorn：http://localhost:9123
- Django admin：http://localhost/admin/

## 6. 日常开发命令

```bash
# 进入容器
docker-compose exec archery bash

# 跑测试
docker-compose exec archery pytest

# 单独跑某个测试
docker-compose exec archery pytest tests/test_workflow.py -k test_submit

# 收集静态文件
docker-compose exec archery python manage.py collectstatic --noinput

# 跑迁移
docker-compose exec archery python manage.py makemigrations
docker-compose exec archery python manage.py migrate

# 重启单个服务
docker-compose restart archery

# 查看 Celery 日志
docker-compose logs -f celery_worker
```

## 7. 调试

### PyCharm / VSCode 远程调试

1. 在 `.env` 加 `DEBUG=True`
2. 用 docker-compose 启动，但 `command` 改成开发模式：

```bash
docker-compose run --rm --service-ports archery python manage.py runserver 0.0.0.0:9123
```

3. IDE 配置 `docker-compose exec` 作为远程 Python 解释器，或 attach 到容器内 Python 进程。

### 数据库连接

- Host: `localhost`（端口 3306）
- User/Pass: 见 `.env`
- DB: `archery`

> 也可以用 Docker 内网 `mysql` 当 host。

## 8. 常见问题

### Q: Celery 任务不执行
A: 检查 `celery_worker` 容器日志，确认 broker 连得上 Redis。

### Q: 静态文件 404
A: 跑 `collectstatic`，或者开发模式下由 Django 处理。

### Q: 迁移冲突
A: 不要直接改上游迁移文件。在自己的 app 下新增迁移。

## 9. 清理

```bash
# 停服务
docker-compose down

# 完全清理（删数据）
docker-compose down -v
```
