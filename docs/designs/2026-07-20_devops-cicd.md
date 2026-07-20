# Archery 二次开发 —— DevOps / CI/CD / 部署设计

> **状态**：v0.8（设计中，6 个核心决策已拍板，待最后评审）
> **日期**：2026-07-20
> **作者**：Mavis（辅助生成）+ 项目 owner
> **配套文档**：[`2026-07-20_dingtalk-oa-workflow.md`](./2026-07-20_dingtalk-oa-workflow.md)

---

## 0. 文档说明

本文档记录"Archery 二次开发"的**完整交付链路**设计：CI/CD 流水线 + 服务器部署 + 监控运维。

- **配套设计**：[钉钉 OA 联动设计 v0.7](./2026-07-20_dingtalk-oa-workflow.md)
- **本文档固定基线**：Archery v1.14.0 + 项目 commit `c7170ff`
- **目标读者**：项目 owner + 运维同事 + 团队 review

---

## 1. 背景与目标

### 1.1 业务诉求

项目 owner 要求：**"开发 - 测试 - bug 修复 - 发布上线，整个流程自动完成"**。

具体场景：
- 工程师 push 代码 → 自动跑测试
- bug 修复 → 自动重测 → 自动合并
- tag 触发 → 自动部署 → **人工审批后** 上线
- 服务器 `172.20.2.134` 由 CI/CD 工具自动初始化、部署、运维
- Archery 服务和 Redis 都没有部署，需要 agent 写好脚本由 CI/CD 执行

### 1.2 设计目标

1. **完全自动化**：开发到上线的每一步都由 CI/CD 触发
2. **人工审批门**：生产部署前必须人工审批
3. **30 秒回滚**：tag-based 版本管理，任意版本可秒级回滚
4. **可观测**：健康检查 + 日志 + 告警 + 备份
5. **agent 不直接 SSH**：agent 只写脚本和 CI/CD 配置，由 GitHub Actions 执行

### 1.3 agent 职责边界

按项目 `AGENTS.md` 硬规则：

> **不在 AI agent 职责内**：
> - 生产环境部署（需要人工审批）
> - 真实凭据、连接串
> - 删除/重置数据库
> - 任何与外部系统的 DDL/DML

**所以"自动完成"的实际含义**：

| 谁 | 做什么 |
|----|--------|
| **agent（我）** | 写 GitHub Actions YAML、部署脚本、配置模板、运维脚本、runbook |
| **GitHub Actions** | 实际触发 SSH 跑脚本、部署、跑测试 |
| **人** | 审批生产部署、管理密钥、监控告警接收 |

**agent 绝不直接 SSH 到 172.20.2.134 执行任何操作。**

---

## 2. 关键决策汇总（已拍板）

| # | 决策项 | 选择 | 说明 |
|---|--------|------|------|
| 1 | CI/CD 工具 | **A. GitHub Actions** | 已有 `.github/workflows/`；免费额度够 |
| 2 | 部署触发方式 | **A. push main 自动部署；tag 触发生产** | main → 自动部署；`v*` tag → 人工审批后生产 |
| 3 | 环境定位 | **A. dev/staging/prod 一体** | 172.20.2.134 同时承担多角色，用 systemd 实例/端口区分 |
| 4 | 服务架构 | **B. 单机裸机 + 多 worker** | 4 worker gunicorn + supervisor + nginx |
| 5 | Redis 部署 | **A. apt 装 redis-server** | 简单稳定 |
| 6 | 数据库初始化 | **A. 远程 172.20.2.134 MySQL 跑 migrate** | 用 `dbops` 账号 |

### 2.1 关于"dev/staging/prod 一体"的风险与对策

⚠️ **风险**：所有环境在同一台机器上，可能造成：
- 测试流量影响生产
- 配置混乱（一个进程在 prod，另一个在 staging）
- 回滚困难

✅ **对策**（在本文档中实现）：
- 用 **systemd 多实例** 区分（不同端口 + 不同代码目录）
- 用 **GitHub Environments**（GitHub Actions）区分审批流
- 用 **database_alias** 区分数据库（archery_dev / archery_staging / archery_prod）
- 用 **tag** 严格控制 prod 部署版本

---

## 3. 整体架构

### 3.1 网络拓扑

```
┌──────────────────────────────────────────────────────────┐
│                GitHub (仓库托管)                          │
│   main / develop 分支 / v* tags                          │
│   PR 评审 / GitHub Environments 审批                     │
└────────────────────┬─────────────────────────────────────┘
                     │ push / tag
                     ▼
┌──────────────────────────────────────────────────────────┐
│                GitHub Actions Runner                      │
│   ┌──────────────────────────────────────────┐          │
│   │ CI 阶段：                                 │          │
│   │   - lint (flake8 / black / isort)        │          │
│   │   - test (pytest)                         │          │
│   │   - build (sdist/wheel)                   │          │
│   └──────────────────────────────────────────┘          │
│   ┌──────────────────────────────────────────┐          │
│   │ CD 阶段（需人工审批）：                   │          │
│   │   - SSH 172.20.2.134                      │          │
│   │   - 拉代码 / 装依赖 / 跑 migrate          │          │
│   │   - 重启服务 / 健康检查                   │          │
│   └──────────────────────────────────────────┘          │
└────────────────────┬─────────────────────────────────────┘
                     │ SSH (密钥对认证)
                     ▼
┌──────────────────────────────────────────────────────────┐
│         生产服务器 172.20.2.134                           │
│                                                          │
│  ┌────────────────────────────────────────────────┐     │
│  │  nginx (80/443)                                │     │
│  │   ├── /              → archery-prod (9003)    │     │
│  │   ├── /staging      → archery-staging (9002)  │     │
│  │   └── /dev          → archery-dev (9001)      │     │
│  └────────────────────────────────────────────────┘     │
│                                                          │
│  ┌────────────────────────────────────────────────┐     │
│  │  supervisor / systemd                          │     │
│  │   ├── archery-prod-gunicorn (4 workers)       │     │
│  │   ├── archery-prod-celery-worker              │     │
│  │   ├── archery-prod-celery-beat                │     │
│  │   ├── archery-staging-gunicorn (2 workers)    │     │
│  │   ├── archery-dev-gunicorn (1 worker)         │     │
│  └────────────────────────────────────────────────┘     │
│                                                          │
│  ┌────────────────────────────────────────────────┐     │
│  │  Redis (apt 安装)                              │     │
│  │   port 6379, bind 127.0.0.1                    │     │
│  └────────────────────────────────────────────────┘     │
│                                                          │
│  ┌────────────────────────────────────────────────┐     │
│  │  Python 3.11 virtualenv                        │     │
│  │   /opt/archery/{prod,staging,dev}/             │     │
│  └────────────────────────────────────────────────┘     │
│                                                          │
│  ┌────────────────────────────────────────────────┐     │
│  │  MySQL（外部）                                 │     │
│  │   archery_prod / archery_staging / archery_dev │     │
│  └────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────┘
```

### 3.2 服务架构（多 worker gunicorn）

```
nginx (反向代理 + 静态文件 + IP 白名单)
   ↓
gunicorn (4 workers) ───┐
                        ├── Django app (archery.wsgi)
celery worker (4) ──────┤
                        ├── Celery tasks
celery beat (1) ────────┘
                        ↓
                    MySQL + Redis
```

### 3.3 部署流程

```
开发者 push code / tag
   │
   ▼
GitHub Actions 触发
   │
   ├── [CI 阶段] 无需审批
   │   ├── Lint 检查（flake8/black）
   │   ├── 单元测试（pytest + 覆盖率）
   │   ├── 集成测试（docker-compose up + 跑测试）
   │   └── 失败 → 通知开发者，终止
   │
   └── [CD 阶段] 需要环境审批
       │
       ├── push to main
       │   └── 自动部署到 staging（无需审批）
       │
       └── tag v*.*.* 推送
           │
           ├── 创建 GitHub Release
           ├── 触发 "production" Environment
           │   │
           │   ├── 等待人工审批（GitHub UI）
           │   │
           │   └── 审批通过
           │       │
           │       ▼
           │   [部署到生产]
           │       ├── SSH 172.20.2.134
           │       ├── git fetch + checkout tag
           │       ├── pip install -r requirements.txt
           │       ├── python manage.py migrate
           │       ├── python manage.py collectstatic
           │       ├── supervisorctl restart
           │       ├── 健康检查（curl /healthz）
           │       └── 通知钉钉群（部署结果）
```

---

## 4. 服务器初始化（一次性）

### 4.1 初始化脚本

`scripts/deploy/01_init_server.sh`：

```bash
#!/usr/bin/env bash
# 一次性服务器初始化脚本
# 在 172.20.2.134 上以 root 身份执行
# 包含：系统包、Python、Redis、用户、目录、防火墙

set -euo pipefail

ARCHERY_USER="archery"
ARCHERY_HOME="/opt/archery"
PYTHON_VERSION="3.11"

echo "==> 1. 系统包更新"
apt update && apt upgrade -y

echo "==> 2. 基础依赖安装"
apt install -y \
    build-essential \
    curl wget git vim \
    python${PYTHON_VERSION} python3-pip python3-venv python3-dev \
    default-libmysqlclient-dev pkg-config default-mysql-client \
    redis-server \
    nginx supervisor \
    ufw fail2ban \
    cron logrotate \
    certbot python3-certbot-nginx

echo "==> 3. Redis 配置"
# 仅监听本地，禁止外网访问
sed -i 's/^bind .*/bind 127.0.0.1/' /etc/redis/redis.conf
sed -i 's/^protected-mode no/protected-mode yes/' /etc/redis/redis.conf
echo "requirepass $(openssl rand -hex 24)" >> /etc/redis/redis.conf
systemctl enable redis-server
systemctl restart redis-server

echo "==> 4. 防火墙（UFW）"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH"
ufw allow 80/tcp comment "HTTP"
ufw allow 443/tcp comment "HTTPS"
# 钉钉回调服务器固定 IP（白名单，详见 v0.7 §10.5.5）
ufw allow from 101.37.79.0/24 to any port 80 comment "DingTalk Hangzhou"
ufw allow from 140.205.94.0/24 to any port 80 comment "DingTalk Shanghai"
ufw --force enable

echo "==> 5. 创建 archery 用户（无登录 shell）"
if ! id "${ARCHERY_USER}" >/dev/null 2>&1; then
    useradd -r -m -d "${ARCHERY_HOME}" -s /usr/sbin/nologin "${ARCHERY_USER}"
fi

echo "==> 6. 目录结构"
mkdir -p ${ARCHERY_HOME}/{prod,staging,dev}
mkdir -p ${ARCHERY_HOME}/shared/{logs,media,static,backups,run}
mkdir -p /var/log/archery
chown -R ${ARCHERY_USER}:${ARCHERY_USER} ${ARCHERY_HOME}
chown -R ${ARCHERY_USER}:${ARCHERY_USER} /var/log/archery

echo "==> 7. SSH 密钥（供 GitHub Actions 使用）"
mkdir -p /home/${ARCHERY_USER}/.ssh
# 这里需要 CI/CD 的公钥（手动粘贴或参数化）
# ssh-keygen -t ed25519 -C "github-actions-deploy" -f /home/${ARCHERY_USER}/.ssh/github_actions
# cat /home/${ARCHERY_USER}/.ssh/github_actions.pub >> /home/${ARCHERY_USER}/.ssh/authorized_keys
chmod 700 /home/${ARCHERY_USER}/.ssh
chmod 600 /home/${ARCHERY_USER}/.ssh/authorized_keys
chown -R ${ARCHERY_USER}:${ARCHERY_USER} /home/${ARCHERY_USER}/.ssh

echo "==> 8. logrotate"
cat > /etc/logrotate.d/archery <<'EOF'
/var/log/archery/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0644 archery archery
    sharedscripts
    postrotate
        supervisorctl restart archery-prod-gunicorn > /dev/null 2>&1 || true
    endscript
}
EOF

echo "==> 初始化完成"
echo "下一步："
echo "  1. 手动配置 SSH 公钥"
echo "  2. 创建 .env 文件（从 .env.example 复制）"
echo "  3. 拉取代码到 ${ARCHERY_HOME}/prod"
```

### 4.2 SSH 密钥对（CI/CD 部署用）

```bash
# 在本地（开发机）生成密钥对
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/archery_deploy_key

# 公钥贴到 172.20.2.134 的 archery 用户 authorized_keys
cat ~/.ssh/archery_deploy_key.pub | ssh root@172.20.2.134 \
    "tee -a /home/archery/.ssh/authorized_keys"

# 私钥存到 GitHub Repo Settings > Secrets > SSH_PRIVATE_KEY
cat ~/.ssh/archery_deploy_key | pbcopy
# 粘贴到 GitHub Secrets
```

---

## 5. Archery 服务部署

### 5.1 部署脚本（每次部署调用）

`scripts/deploy/02_deploy.sh`：

```bash
#!/usr/bin/env bash
# 通用部署脚本
# 用法：./02_deploy.sh <env> <version>
#   env: dev | staging | prod
#   version: git commit hash / tag / branch

set -euo pipefail

ENV="${1:?Usage: $0 <env> <version>}"
VERSION="${2:?Usage: $0 <env> <version>}"

case "${ENV}" in
    dev)     PORT=9001; DB="archery_dev";     WORKERS=1; REPO_DIR="/opt/archery/dev"     ;;
    staging) PORT=9002; DB="archery_staging"; WORKERS=2; REPO_DIR="/opt/archery/staging" ;;
    prod)    PORT=9003; DB="archery_prod";    WORKERS=4; REPO_DIR="/opt/archery/prod"    ;;
    *)       echo "Unknown env: ${ENV}"; exit 1 ;;
esac

ARCHERY_USER="archery"
SHARED_DIR="/opt/archery/shared"
LOG_DIR="/var/log/archery"

echo "==> 部署 [${ENV}] 版本 [${VERSION}]"

# 1) 拉代码
echo "  1. 拉代码..."
sudo -u ${ARCHERY_USER} -H bash -c "
    cd ${REPO_DIR} || git clone https://github.com/your-org/archery_dev.git ${REPO_DIR}
    cd ${REPO_DIR}
    git fetch --all --prune
    git checkout ${VERSION}
    git log -1 --oneline
"

# 2) 安装依赖
echo "  2. 装依赖..."
sudo -u ${ARCHERY_USER} -H bash -c "
    cd ${REPO_DIR}
    python3.11 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
"

# 3) 加载 .env（部署前已存在）
if [ ! -f "${REPO_DIR}/.env" ]; then
    echo "  ERROR: .env 不存在，请先从 .env.example 复制并配置"
    exit 1
fi

# 4) 数据库迁移
echo "  3. 数据库迁移..."
sudo -u ${ARCHERY_USER} -H bash -c "
    cd ${REPO_DIR}
    source venv/bin/activate
    set -a; source .env; set +a
    python manage.py migrate --noinput
"

# 5) 收集静态文件
echo "  4. 收集静态文件..."
sudo -u ${ARCHERY_USER} -H bash -c "
    cd ${REPO_DIR}
    source venv/bin/activate
    set -a; source .env; set +a
    python manage.py collectstatic --noinput
"

# 6) 重启服务
echo "  5. 重启服务..."
supervisorctl restart archery-${ENV}-gunicorn
supervisorctl restart archery-${ENV}-celery-worker 2>/dev/null || true
supervisorctl restart archery-${ENV}-celery-beat 2>/dev/null || true

# 7) 健康检查
echo "  6. 健康检查..."
for i in {1..10}; do
    if curl -fsS http://127.0.0.1:${PORT}/healthz > /dev/null; then
        echo "  ✓ 健康检查通过 (${ENV} on port ${PORT})"
        break
    fi
    echo "  waiting... (${i}/10)"
    sleep 2
    if [ "$i" = "10" ]; then
        echo "  ✗ 健康检查失败，自动回滚！"
        ./03_rollback.sh ${ENV} ${VERSION}
        exit 1
    fi
done

# 8) 通知钉钉群
echo "  7. 通知..."
DEPLOY_MSG="✓ Archery ${ENV} 部署成功\n版本: ${VERSION}\n时间: $(date '+%Y-%m-%d %H:%M:%S')\n服务器: 172.20.2.134"
curl -X POST "${DINGTALK_NOTIFY_WEBHOOK}" \
    -H "Content-Type: application/json" \
    -d "{\"msgtype\": \"text\", \"text\": {\"content\": \"${DEPLOY_MSG}\"}}"

echo "==> 部署完成"
```

### 5.2 supervisor 配置

`/etc/supervisor/conf.d/archery-prod.conf`：

```ini
; Archery Production
[program:archery-prod-gunicorn]
command=/opt/archery/prod/venv/bin/gunicorn archery.wsgi:application -w 4 -b 127.0.0.1:9003 --access-logfile - --error-logfile -
directory=/opt/archery/prod
user=archery
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=10
stdout_logfile=/var/log/archery/prod-gunicorn.log
stderr_logfile=/var/log/archery/prod-gunicorn-error.log
environment=
    DJANGO_SETTINGS_MODULE="archery.settings",
    PYTHONUNBUFFERED="1"

[program:archery-prod-celery-worker]
command=/opt/archery/prod/venv/bin/celery -A archery worker -l info --concurrency=4
directory=/opt/archery/prod
user=archery
autostart=true
autorestart=true
startsecs=10
stdout_logfile=/var/log/archery/prod-celery-worker.log
stderr_logfile=/var/log/archery/prod-celery-worker-error.log

[program:archery-prod-celery-beat]
command=/opt/archery/prod/venv/bin/celery -A archery beat -l info
directory=/opt/archery/prod
user=archery
autostart=true
autorestart=true
startsecs=10
stdout_logfile=/var/log/archery/prod-celery-beat.log
stderr_logfile=/var/log/archery/prod-celery-beat-error.log

; group: 把三个进程作为一组管理
[group:archery-prod]
programs=archery-prod-gunicorn,archery-prod-celery-worker,archery-prod-celery-beat
```

staging 和 dev 类似，端口/路径不同。

### 5.3 nginx 配置

`/etc/nginx/sites-available/archery.conf`：

```nginx
# 上游定义
upstream archery_prod {
    server 127.0.0.1:9003 fail_timeout=0;
}

upstream archery_staging {
    server 127.0.0.1:9002 fail_timeout=0;
}

upstream archery_dev {
    server 127.0.0.1:9001 fail_timeout=0;
}

# HTTP → HTTPS 重定向
server {
    listen 80;
    server_name archery.example.com;
    return 301 https://$host$request_uri;
}

# 生产
server {
    listen 443 ssl http2;
    server_name archery.example.com;
    client_max_body_size 50M;

    ssl_certificate     /etc/letsencrypt/live/archery.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/archery.example.com/privkey.pem;

    # 静态文件
    location /static/ {
        alias /opt/archery/shared/static/;
        expires 7d;
    }
    location /media/ {
        alias /opt/archery/shared/media/;
    }

    # 健康检查（不限制 IP）
    location = /healthz {
        proxy_pass http://archery_prod;
        access_log off;
    }

    # 钉钉 OA 回调（IP 白名单）
    location /dingtalk/oa/callback {
        # 钉钉回调服务器固定 IP
        allow 101.37.79.0/24;       # 杭州
        allow 140.205.94.0/24;      # 上海
        allow 203.119.214.0/24;     # 深圳
        allow 59.110.0.0/16;        # 北京
        deny all;

        proxy_pass http://archery_prod;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # 主应用
    location / {
        proxy_pass http://archery_prod;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}

# Staging（IP 白名单，仅内网 + 钉钉）
server {
    listen 443 ssl http2;
    server_name staging.archery.example.com;
    client_max_body_size 50M;

    ssl_certificate     /etc/letsencrypt/live/staging.archery.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/staging.archery.example.com/privkey.pem;

    # 仅内网访问
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    allow 192.168.0.0/16;
    deny all;

    location /static/ { alias /opt/archery/shared/static/; }
    location / {
        proxy_pass http://archery_staging;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}

# Dev（同 staging）
server {
    listen 443 ssl http2;
    server_name dev.archery.example.com;
    client_max_body_size 50M;

    ssl_certificate     /etc/letsencrypt/live/dev.archery.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dev.archery.example.com/privkey.pem;

    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    allow 192.168.0.0/16;
    deny all;

    location / {
        proxy_pass http://archery_dev;
        proxy_set_header Host $host;
    }
}
```

### 5.4 健康检查 endpoint

`archery/urls.py` 加一行（最小侵入）：

```python
# archery/urls.py 末尾追加
from django.http import JsonResponse

def healthz(request):
    """健康检查 endpoint（供 CI/CD 和监控用）"""
    try:
        # 检查数据库
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        # 检查 Redis
        from django_redis import get_redis_connection
        rs = get_redis_connection("default")
        rs.ping()
        return JsonResponse({"status": "ok", "service": "archery"})
    except Exception as e:
        return JsonResponse({"status": "error", "error": str(e)}, status=503)


urlpatterns = [
    # ... 原有路由不动
    path("healthz", healthz, name="healthz"),
]
```

### 5.5 systemd 单元（可选，supervisor 已可不用）

如果用 systemd 不用 supervisor，`/etc/systemd/system/archery-prod-gunicorn.service`：

```ini
[Unit]
Description=Archery Production Gunicorn
After=network.target mysql.service redis-server.service

[Service]
Type=simple
User=archery
Group=archery
WorkingDirectory=/opt/archery/prod
Environment="DJANGO_SETTINGS_MODULE=archery.settings"
EnvironmentFile=/opt/archery/prod/.env
ExecStart=/opt/archery/prod/venv/bin/gunicorn archery.wsgi:application -w 4 -b 127.0.0.1:9003 --access-logfile - --error-logfile -
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 6. CI/CD 流水线（GitHub Actions）

### 6.1 Workflow 概览

```
.github/workflows/
├── ci.yml              # 持续集成：lint + test（每次 push/PR）
├── cd-staging.yml      # 自动部署到 staging（push to main）
├── cd-prod.yml         # 部署到生产（tag v* 触发，需人工审批）
└── codeql.yml          # 安全扫描（已有，沿用上游）
```

### 6.2 CI workflow（每次 push/PR）

`.github/workflows/ci.yml`：

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install lint tools
        run: |
          pip install flake8 black isort

      - name: Black check
        run: black --check --diff sql/ common/ archery/ sql_api/ sql/extensions/

      - name: isort check
        run: isort --check-only --diff sql/ common/ archery/ sql_api/ sql/extensions/

      - name: Flake8
        run: flake8 sql/ common/ archery/ sql_api/ sql/extensions/ --max-line-length=120 --exclude=migrations,__pycache__

  test:
    name: Test
    runs-on: ubuntu-latest
    services:
      mysql:
        image: mysql:8.0
        env:
          MYSQL_ROOT_PASSWORD: rootpass
          MYSQL_DATABASE: archery_test
          MYSQL_USER: archery
          MYSQL_PASSWORD: archery
        ports:
          - 3306:3306
        options: --health-cmd="mysqladmin ping" --health-interval=10s --health-timeout=5s --health-retries=5

      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: --health-cmd="redis-cli ping" --health-interval=10s --health-timeout=5s --health-retries=5

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install -r requirements.txt
          pip install -r requirements-test.txt 2>/dev/null || true

      - name: Run migrations
        env:
          MYSQL_HOST: localhost
          REDIS_HOST: localhost
          DJANGO_SETTINGS_MODULE: archery.settings
          SECRET_KEY: test-secret
          DEBUG: "True"
        run: |
          python manage.py migrate --noinput

      - name: Run tests
        env:
          MYSQL_HOST: localhost
          REDIS_HOST: localhost
          DJANGO_SETTINGS_MODULE: archery.settings
          SECRET_KEY: test-secret
          DEBUG: "True"
        run: |
          pytest --cov=sql --cov=common --cov=sql_api --cov=sql.extensions --cov-report=xml --cov-report=term-missing -v

      - name: Upload coverage
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: coverage.xml
```

### 6.3 CD Staging workflow（push to main 自动）

`.github/workflows/cd-staging.yml`：

```yaml
name: CD Staging

on:
  push:
    branches: [main]
    paths-ignore:
      - "docs/**"
      - "*.md"

jobs:
  deploy-staging:
    name: Deploy to Staging
    runs-on: ubuntu-latest
    environment: staging  # GitHub Environment（无需审批）
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup SSH
        uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.SSH_PRIVATE_KEY }}

      - name: Deploy to staging
        env:
          ENV: staging
          VERSION: ${{ github.sha }}
        run: |
          ssh -o StrictHostKeyChecking=no archery@172.20.2.134 << 'EOF'
            cd /opt/archery/scripts/deploy
            ./02_deploy.sh staging ${VERSION}
          EOF

      - name: Health check
        run: |
          sleep 10
          curl -fsS https://staging.archery.example.com/healthz

      - name: Notify on failure
        if: failure()
        uses: slackapi/slack-github-action@v1
        with:
          payload: |
            {
              "text": "✗ Archery Staging 部署失败 - ${{ github.run_id }}"
            }
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.DINGTALK_NOTIFY_WEBHOOK }}
```

### 6.4 CD Prod workflow（tag 触发 + 人工审批）

`.github/workflows/cd-prod.yml`：

```yaml
name: CD Production

on:
  push:
    tags:
      - "v*.*.*"

jobs:
  deploy-prod:
    name: Deploy to Production
    runs-on: ubuntu-latest
    environment:
      name: production
      url: https://archery.example.com
    # ⭐ 关键：production 环境在 GitHub Repo Settings 中配置"Required reviewers"
    # 至少 1 个 reviewer（owner）审批通过才会执行

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Extract version
        id: version
        run: echo "VERSION=${GITHUB_REF#refs/tags/v}" >> $GITHUB_OUTPUT

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ github.ref_name }}
          name: Release ${{ steps.version.outputs.VERSION }}
          generate_release_notes: true

      - name: Setup SSH
        uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.SSH_PRIVATE_KEY }}

      - name: Deploy to production
        env:
          ENV: prod
          VERSION: ${{ github.ref_name }}
        run: |
          ssh -o StrictHostKeyChecking=no archery@172.20.2.134 << EOF
            cd /opt/archery/scripts/deploy
            ./02_deploy.sh prod ${VERSION}
          EOF

      - name: Health check
        run: |
          sleep 10
          curl -fsS https://archery.example.com/healthz

      - name: Notify
        if: always()
        uses: slackapi/slack-github-action@v1
        with:
          payload: |
            {
              "text": "${{ job.status == 'success' && '✓' || '✗' }} Archery ${{ steps.version.outputs.VERSION }} ${{ job.status }} - ${{ github.run_id }}"
            }
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.DINGTALK_NOTIFY_WEBHOOK }}
```

### 6.5 GitHub Environments 配置

在 GitHub Repo → Settings → Environments：

**staging**：
- 无需审批
- Secrets: `SSH_PRIVATE_KEY`, `DINGTALK_NOTIFY_WEBHOOK`

**production**：
- **Required reviewers**: 1+（项目 owner）
- Wait timer: 5 分钟（给审批人思考时间）
- Secrets: 同 staging

### 6.6 GitHub Secrets 配置

| Secret | 用途 |
|--------|------|
| `SSH_PRIVATE_KEY` | CI/CD 部署用 SSH 私钥（archery 用户的 ed25519 密钥）|
| `DINGTALK_NOTIFY_WEBHOOK` | 部署结果通知到钉钉群 |
| `CODECOV_TOKEN` | （可选）Codecov 集成 |

**绝不能上传到 Secrets 的**：
- 数据库密码 → 写在服务器 `.env`（已 gitignore）
- 钉钉 AppSecret → 写在服务器 `.env`（已 gitignore）
- 任何真实凭据

### 6.7 Release 流程（人工）

```bash
# 1. 确认 main 分支已合并所有 PR，且 CI 通过
git checkout main
git pull

# 2. 跑版本号（按 SemVer）
git tag -a v1.14.0.1 -m "feat: 钉钉 OA 集成 + 部署流水线"

# 3. 推 tag
git push origin v1.14.0.1

# 4. 触发 GitHub Actions
# 5. 等待 GitHub UI 审批
# 6. 审批通过 → 自动部署
```

---

## 7. 监控与运维

### 7.1 健康检查（已有，详见 §5.4）

`/healthz` endpoint：
- 检查 MySQL 连接
- 检查 Redis 连接
- 返回 200 或 503

### 7.2 监控脚本（systemd timer）

`scripts/monitor/check_health.sh`：

```bash
#!/usr/bin/env bash
# 每 5 分钟跑一次（systemd timer）
# 健康检查失败时告警

set -e

HEALTH_URL="https://archery.example.com/healthz"
DINGTALK_WEBHOOK="/etc/archery/dingtalk_webhook"  # 路径方式存密钥

response=$(curl -fsS -o /tmp/healthz.json -w "%{http_code}" ${HEALTH_URL} 2>&1 || echo "000")

if [ "$response" != "200" ]; then
    # 告警
    msg="🚨 Archery 健康检查失败\nURL: ${HEALTH_URL}\nHTTP: ${response}\nTime: $(date)"
    curl -X POST "$(cat ${DINGTALK_WEBHOOK})" \
        -H "Content-Type: application/json" \
        -d "{\"msgtype\": \"text\", \"text\": {\"content\": \"${msg}\"}}"
fi
```

`/etc/systemd/system/archery-monitor.timer`：

```ini
[Unit]
Description=Archery health check timer

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
```

### 7.3 备份脚本

`scripts/deploy/04_backup.sh`：

```bash
#!/usr/bin/env bash
# 每日备份：MySQL + media + .env
# cron: 0 2 * * *

set -euo pipefail

BACKUP_DIR="/opt/archery/shared/backups"
DATE=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=30

mkdir -p ${BACKUP_DIR}

# 1. MySQL dump
echo "==> 备份 MySQL..."
source /opt/archery/prod/.env
mysqldump -h ${MYSQL_HOST} -P ${MYSQL_PORT} -u ${MYSQL_USER} -p${MYSQL_PASSWORD} \
    --single-transaction --routines --triggers \
    --databases archery_prod > ${BACKUP_DIR}/mysql_${DATE}.sql

# 2. 加密备份（防止凭据泄露）
gpg --batch --yes --passphrase-file /etc/archery/backup_passphrase \
    -c ${BACKUP_DIR}/mysql_${DATE}.sql
rm ${BACKUP_DIR}/mysql_${DATE}.sql

# 3. 备份 media（用户上传文件）
tar czf ${BACKUP_DIR}/media_${DATE}.tar.gz /opt/archery/shared/media/

# 4. 备份 .env 模板（不含真实密钥）
cp /opt/archery/prod/.env ${BACKUP_DIR}/env_prod_${DATE}.template

# 5. 清理 30 天前的备份
find ${BACKUP_DIR} -name "*.sql.gpg" -mtime +${KEEP_DAYS} -delete
find ${BACKUP_DIR} -name "*.tar.gz" -mtime +${KEEP_DAYS} -delete

echo "==> 备份完成：${DATE}"
```

cron 配置：

```bash
# /etc/cron.d/archery-backup
0 2 * * * archery /opt/archery/scripts/deploy/04_backup.sh >> /var/log/archery/backup.log 2>&1
```

### 7.4 关键监控指标

| 指标 | 工具 | 阈值 | 告警 |
|------|------|------|------|
| 服务存活 | curl /healthz | 5xx | 钉钉群 |
| MySQL 连接 | 内部检查 | 失败 | 钉钉群 |
| Redis 连接 | 内部检查 | 失败 | 钉钉群 |
| 磁盘空间 | df -h | > 85% | 钉钉群 |
| CPU / 内存 | top | > 90% | 钉钉群 |
| SSL 证书过期 | openssl check | < 14 天 | 钉钉群 |
| 备份成功 | cron log | 失败 | 钉钉群 |

---

## 8. 故障排查 Runbook

### 8.1 服务起不来

```bash
# 1. 看 supervisor 状态
supervisorctl status

# 2. 看具体错误
supervisorctl tail -1000 archery-prod-gunicorn stderr

# 3. 手动起一下看错误
sudo -u archery -H bash -c "
    cd /opt/archery/prod
    source venv/bin/activate
    set -a; source .env; set +a
    gunicorn archery.wsgi:application -w 1 -b 127.0.0.1:9003
"

# 4. 常见原因：
#    - .env 没配 → 检查 /opt/archery/prod/.env
#    - 数据库连不上 → 检查 MYSQL_HOST/PORT
#    - Redis 连不上 → systemctl status redis-server
#    - 端口被占 → lsof -i :9003
```

### 8.2 部署失败回滚

```bash
# /opt/archery/scripts/deploy/03_rollback.sh
ENV="${1}"
PREV_VERSION="${2}"  # 部署前的版本

case "${ENV}" in
    prod)    REPO_DIR="/opt/archery/prod"    ;;
    staging) REPO_DIR="/opt/archery/staging" ;;
    dev)     REPO_DIR="/opt/archery/dev"     ;;
esac

sudo -u archery -H bash -c "
    cd ${REPO_DIR}
    git checkout ${PREV_VERSION}
"
supervisorctl restart archery-${ENV}-gunicorn
```

### 8.3 数据库锁死

```bash
# 查锁
mysql -h ${MYSQL_HOST} -u root -p -e "
    SELECT * FROM information_schema.INNODB_TRX\G
    SELECT * FROM information_schema.INNODB_LOCKS\G
"

# 杀长事务
mysql -h ${MYSQL_HOST} -u root -p -e "
    SELECT trx_id, trx_started, trx_mysql_thread_id, trx_query
    FROM information_schema.INNODB_TRX
    WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > 60;
    -- 拿到 thread_id 后 KILL <id>
"
```

### 8.4 钉钉回调异常

```bash
# 1. 看 nginx access log
tail -f /var/log/nginx/access.log | grep dingtalk

# 2. 看应用日志
tail -f /var/log/archery/prod-gunicorn.log | grep -i dingtalk

# 3. 看 event log
mysql -h ${MYSQL_HOST} -u ${MYSQL_USER} -p -e "
    SELECT * FROM ext_dingtalk_oa_event_log 
    WHERE processed=0 
    ORDER BY created_at DESC LIMIT 20;
"

# 4. 手动重发
# （详见 v0.7 §10.4.6 重试 OA）
```

---

## 9. 风险与回滚

### 9.1 主要风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| CI/CD 配置错误 | 部署坏版本到生产 | 人工审批门 + 健康检查自动回滚 |
| 数据库迁移失败 | 服务起不来 | 备份 + 迁移前自动 dump |
| 部署超时/网络中断 | 服务半新半旧 | gunicorn 优雅重启（SIGTERM 等待 30s）|
| 钉钉 API 变化 | 回调失败 | 见 v0.7 §10.5 安全 + 兜底 |
| **dev/staging/prod 一体** | 测试影响生产 | systemd 多实例 + 端口隔离 + 域名隔离 |
| 密钥泄露 | 严重安全事故 | 密钥只存服务器 .env + GitHub Secrets，不进 git |

### 9.2 回滚时间表

| 场景 | 目标恢复时间 | 方式 |
|------|--------------|------|
| 代码 bug | < 2 分钟 | `git checkout <prev_tag> && supervisorctl restart` |
| 数据库迁移 bug | < 5 分钟 | 备份恢复 + 切换代码版本 |
| 配置文件错 | < 1 分钟 | 还原 .env 备份 |
| 服务器硬件故障 | 30+ 分钟 | 重新初始化（按 04_runbook）|

---

## 10. 阶段化实施

| 阶段 | 内容 | 估时 |
|------|------|------|
| **0. GitHub Secrets 准备** | 在 Repo Settings 加 SSH_PRIVATE_KEY / DINGTALK_NOTIFY_WEBHOOK | 0.5 天 |
| **1. 服务器初始化** | `01_init_server.sh` 在 172.20.2.134 跑一次（含 Redis）| 1 天 |
| **2. SSH 密钥对** | 生成密钥 + 公钥贴服务器 + 私钥存 GitHub Secrets | 0.5 天 |
| **3. CI workflow 上线** | `.github/workflows/ci.yml` 启用 | 0.5 天 |
| **4. CD Staging** | push to main 自动部署 staging | 1 天 |
| **5. CD Prod + 人工审批** | tag 触发 + GitHub Environments 审批 | 1 天 |
| **6. 监控 + 备份** | 健康检查 systemd timer + 备份 cron | 1 天 |
| **7. Runbook + 文档** | 故障排查手册上线 | 0.5 天 |
| **8. 联调 + 演练** | 演练一次完整部署流程 | 1 天 |

**总计**：约 7 个工作日（不含部署上线 1-2 天观察期）

---

## 11. 待拍板子决策

1. **GitHub Repo 迁移**：仓库当前是本地，是否要推到 GitHub？**必须推到 GitHub 才能用 GitHub Actions**
2. **GitHub Environments 配置**：production 至少 1 个 reviewer（owner 自己？）
3. **数据库初始化策略**：第一次部署时跑 migrate + seed？**我推荐是**
4. **SSL 证书**：Let's Encrypt 自动续期（certbot）？**我推荐是**
5. **域名**：是否已有 archery.example.com 域名？**必须确认，否则 staging/prod 域名访问不到**
6. **SSL 证书域名**：生产 1 个 + staging 1 个 + dev 1 个 = 3 个证书？**我推荐是**
7. **钉钉通知 Webhook**：是否复用现有 DBA 群 webhook？**我推荐是**
8. **备份保留期**：30 天？90 天？**我推荐 30 天**
9. **Redis 密码策略**：自动生成 + 存 .env？**我推荐是**
10. **supervisor vs systemd**：用哪个？**我推荐 supervisor**（更轻量，supervisord.conf 上游已提供）

---

## 12. 附录

### 12.1 目录结构（部署后）

```
/opt/archery/
├── prod/                      # 生产代码
│   ├── venv/                  # Python 虚拟环境
│   ├── .env                   # 真实配置（含密码，root only 600）
│   ├── archery/, sql/, ...
│   └── manage.py
├── staging/                   # staging 代码
├── dev/                       # dev 代码
├── shared/
│   ├── logs/                  # 日志（supervisor log 单独在 /var/log/archery）
│   ├── media/                 # 用户上传
│   ├── static/                # 静态文件
│   ├── backups/               # 备份
│   └── run/                   # pid/sock
├── scripts/
│   └── deploy/
│       ├── 01_init_server.sh
│       ├── 02_deploy.sh
│       ├── 03_rollback.sh
│       └── 04_backup.sh
└── .ssh/
    └── authorized_keys         # GitHub Actions 部署用公钥

/etc/supervisor/conf.d/
├── archery-prod.conf
├── archery-staging.conf
└── archery-dev.conf

/etc/nginx/sites-available/
└── archery.conf

/etc/systemd/system/
├── archery-monitor.timer
├── archery-monitor.service
└── archery-backup.timer

/var/log/archery/
├── prod-gunicorn.log
├── prod-celery-worker.log
├── prod-celery-beat.log
└── ...
```

### 12.2 GitHub Actions 限制

| 限制 | 值 |
|------|---|
| 私有 repo 每月分钟数 | 2,000 分钟（免费）|
| 单 job 最大时长 | 6 小时 |
| SSH 连接 | 通过 webfactory/ssh-agent |

**本项目预计使用**：每月 < 100 分钟（足够）

### 12.3 参考资料

- [GitHub Actions 文档](https://docs.github.com/en/actions)
- [GitHub Environments](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment)
- [supervisor 文档](http://supervisord.org/)
- [nginx 文档](https://nginx.org/en/docs/)
- [Let's Encrypt + certbot](https://certbot.eff.org/)
- [Archery 部署文档（上游）](https://github.com/hhyo/Archery/wiki/部署)
- 配套设计：[钉钉 OA 联动 v0.7](./2026-07-20_dingtalk-oa-workflow.md)

---

**文档版本**：v0.8
**最后更新**：2026-07-20（新增 v0.8 DevOps/CI-CD/部署设计）
