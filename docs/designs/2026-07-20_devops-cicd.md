# Archery 二次开发 —— DevOps / CI/CD / 部署设计

> **状态**：v0.9（设计中，10 个核心决策已拍板，钉钉回调走 Cloudflare Tunnel）
> **日期**：2026-07-20
> **作者**：Mavis（辅助生成）+ 项目 owner
> **配套文档**：[`2026-07-20_dingtalk-oa-workflow.md`](./2026-07-20_dingtalk-oa-workflow.md)
> **GitHub Repo**：`https://github.com/adauncle/archerydev.git`

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

## 2. 关键决策汇总（全部已拍板 ✅）

| # | 决策项 | 选择 | 说明 |
|---|--------|------|------|
| 1 | CI/CD 工具 | **A. GitHub Actions** | Repo: `https://github.com/adauncle/archerydev.git` |
| 2 | 部署触发方式 | **A. push main 自动部署；tag 触发生产** | main → staging；`v*` tag → 人工审批后生产 |
| 3 | 环境定位 | **A. dev/staging/prod 一体** | 172.20.2.134 同时承担多角色，systemd 多实例 + 端口区分 |
| 4 | 主服务 SSL | **❌ 不要 SSL** | Archery 主服务走 HTTP |
| 5 | 域名 | **❌ 不用域名，用 IP** | `http://172.20.2.134` 直连 |
| 6 | 钉钉回调 SSL | **✅ Cloudflare Tunnel** | 钉钉回调必须 HTTPS，走 Cloudflare Tunnel 转发 |
| 7 | 钉钉通知 Webhook | **✅ 复用现有 DBA 群 webhook** | |
| 8 | 备份保留期 | **30 天** | |
| 9 | Redis 密码策略 | **✅ 自动生成** | 启动脚本生成 24 字节随机密码，存 .env |
| 10 | 服务管理 | **B. systemd** | 不是 supervisor |
| 11 | 第一次部署初始化 | **✅ 跑 migrate + seed** | |
| 12 | GitHub Environments reviewer | **✅ 项目 owner** | 即你自己 |

### 2.1 钉钉回调必须 HTTPS 的解决方案

**问题**：钉钉平台硬要求回调 URL 必须 HTTPS，HTTP 会被拒绝。

**方案 1（已采纳）**：Cloudflare Tunnel

- 钉钉后台配置回调 URL：`https://archery-oa.your-domain.com/dingtalk/oa/callback`
- Cloudflare Tunnel 在 172.20.2.134 上跑 `cloudflared` 客户端
- 钉钉 → Cloudflare 边缘（自动 HTTPS）→ Tunnel → 172.20.2.134:80/dingtalk/oa/callback
- **不需要本地 SSL 证书**（Cloudflare 帮签）
- **不需要公网 IP**（Cloudflare 主动建立 outbound 连接）
- **不影响主服务**（Archery 主服务仍走 HTTP）

详见 §5.6 钉钉回调 Cloudflare Tunnel 配置。

---

## 3. 整体架构

### 3.1 网络拓扑

```
┌──────────────────────────────────────────────────────────┐
│                GitHub (仓库托管)                          │
│   Repo: https://github.com/adauncle/archerydev.git       │
│   main / develop 分支 / v* tags                          │
│   PR 评审 / GitHub Environments 审批                     │
└────────────────────┬─────────────────────────────────────┘
                     │ push / tag
                     ▼
┌──────────────────────────────────────────────────────────┐
│                GitHub Actions Runner                      │
│   ┌──────────────────────────────────────────┐          │
│   │ CI 阶段：                                 │          │
│   │   - lint / test / build                  │          │
│   └──────────────────────────────────────────┘          │
│   ┌──────────────────────────────────────────┐          │
│   │ CD 阶段（需人工审批）：                   │          │
│   │   - SSH 172.20.2.134                      │          │
│   │   - 拉代码 / 装依赖 / 跑 migrate          │          │
│   │   - 重启服务 / 健康检查                   │          │
│   └──────────────────────────────────────────┘          │
└────────────────────┬─────────────────────────────────────┘
                     │ SSH (ed25519 密钥对认证)
                     ▼
┌──────────────────────────────────────────────────────────┐
│         服务器 172.20.2.134（HTTP，无 SSL）              │
│                                                          │
│  ┌────────────────────────────────────────────────┐     │
│  │  nginx (80)                                    │     │
│  │   ├── /              → archery-prod (9003)    │     │
│  │   ├── /staging      → archery-staging (9002)  │     │
│  │   ├── /dev          → archery-dev (9001)      │     │
│  │   └── /dingtalk/oa/callback                   │     │
│  │         (走 Cloudflare Tunnel，不直接暴露)      │     │
│  └────────────────────────────────────────────────┘     │
│                                                          │
│  ┌────────────────────────────────────────────────┐     │
│  │  systemd                                       │     │
│  │   ├── archery-prod-gunicorn.service (4 workers)│    │
│  │   ├── archery-prod-celery-worker.service       │    │
│  │   ├── archery-prod-celery-beat.service         │    │
│  │   ├── archery-staging-gunicorn.service         │    │
│  │   ├── archery-dev-gunicorn.service             │    │
│  │   ├── cloudflared.service (钉钉回调隧道)       │    │
│  │   └── archery-monitor.timer (健康检查)         │    │
│  └────────────────────────────────────────────────┘     │
│                                                          │
│  ┌────────────────────────────────────────────────┐     │
│  │  Redis (apt 安装)                              │     │
│  │   port 6379, bind 127.0.0.1, 密码保护           │     │
│  └────────────────────────────────────────────────┘     │
│                                                          │
│  ┌────────────────────────────────────────────────┐     │
│  │  Python 3.11 virtualenv                        │     │
│  │   /opt/archery/{prod,staging,dev}/             │     │
│  └────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│         Cloudflare 边缘节点（公网）                       │
│   - 钉钉回调 https://archery-oa.your-domain.com/...     │
│   - 自动 HTTPS（Cloudflare 证书）                        │
│   - 转发到 Tunnel ID（出口连接）                        │
└────────────────────┬─────────────────────────────────────┘
                     │ outbound tunnel
                     ▼
                172.20.2.134:cloudflared
                     │
                     ▼
                nginx → /dingtalk/oa/callback

┌──────────────────────────────────────────────────────────┐
│         钉钉 OA 平台                                      │
│   - 审批人收到钉钉通知                                    │
│   - 在钉钉 App 审批                                      │
│   - 回调 Cloudflare 边缘 URL                              │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│         MySQL（外部，172.20.2.134:3306）                  │
│   archery_prod / archery_staging / archery_dev            │
└──────────────────────────────────────────────────────────┘
```

### 3.2 服务架构（systemd + 多 worker gunicorn）

```
nginx (HTTP 反向代理 + 静态文件 + 钉钉回调)
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
           │       ├── systemctl restart
           │       ├── 健康检查（curl http://172.20.2.134:9003/healthz）
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
SERVER_IP="172.20.2.134"

echo "==> 1. 系统包更新"
apt update && apt upgrade -y

echo "==> 2. 基础依赖安装"
apt install -y \
    build-essential \
    curl wget git vim \
    python${PYTHON_VERSION} python3-pip python3-venv python3-dev \
    default-libmysqlclient-dev pkg-config default-mysql-client \
    redis-server \
    nginx \
    ufw fail2ban \
    cron logrotate

echo "==> 3. Redis 配置"
# 自动生成 24 字节密码
REDIS_PASSWORD=$(openssl rand -hex 24)
echo "  生成 Redis 密码，存到 /etc/archery/redis_password"
mkdir -p /etc/archery
echo "${REDIS_PASSWORD}" > /etc/archery/redis_password
chmod 600 /etc/archery/redis_password

# 配置 Redis
cat > /etc/redis/redis.conf.patch <<EOF
bind 127.0.0.1
protected-mode yes
requirepass ${REDIS_PASSWORD}
maxmemory 256mb
maxmemory-policy allkeys-lru
EOF
cp /etc/redis/redis.conf /etc/redis/redis.conf.bak
cat /etc/redis/redis.conf.bak /etc/redis/redis.conf.patch > /etc/redis/redis.conf
rm /etc/redis/redis.conf.patch
systemctl enable redis-server
systemctl restart redis-server

# 验证
echo "  验证 Redis 密码..."
redis-cli -a "${REDIS_PASSWORD}" ping 2>&1 | grep -q PONG && echo "  ✓ Redis 密码生效" || (echo "  ✗ Redis 密码失败" && exit 1)

echo "==> 4. 防火墙（UFW）"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH"
ufw allow 80/tcp comment "HTTP"
# 钉钉回调走 Cloudflare Tunnel，不需要开放公网
# Cloudflare 边缘 IP 段（2024 年，参考 Cloudflare 官方维护）
# ufw allow from <cloudflare-ip> to any port 80 comment "Cloudflare Tunnel"
# 实际配置中通过 cloudflared 主动建立 outbound 连接，不需要开放入站
ufw --force enable

echo "==> 5. 创建 archery 用户"
if ! id "${ARCHERY_USER}" >/dev/null 2>&1; then
    useradd -r -m -d "${ARCHERY_HOME}" -s /usr/sbin/nologin "${ARCHERY_USER}"
fi

echo "==> 6. 目录结构"
mkdir -p ${ARCHERY_HOME}/{prod,staging,dev}
mkdir -p ${ARCHERY_HOME}/shared/{logs,media,static,backups,run}
mkdir -p /var/log/archery
mkdir -p /etc/archery
chown -R ${ARCHERY_USER}:${ARCHERY_USER} ${ARCHERY_HOME}
chown -R ${ARCHERY_USER}:${ARCHERY_USER} /var/log/archery
chown -R ${ARCHERY_USER}:${ARCHERY_USER} /etc/archery
chmod 700 /etc/archery

echo "==> 7. SSH 密钥对（供 GitHub Actions 部署用）"
mkdir -p /home/${ARCHERY_USER}/.ssh
# 私钥从环境变量或参数传入，示例：
#   SSH_PUBLIC_KEY="$(cat ~/.ssh/archery_deploy.pub)" ./01_init_server.sh
if [ -n "${SSH_PUBLIC_KEY:-}" ]; then
    echo "${SSH_PUBLIC_KEY}" >> /home/${ARCHERY_USER}/.ssh/authorized_keys
    chmod 700 /home/${ARCHERY_USER}/.ssh
    chmod 600 /home/${ARCHERY_USER}/.ssh/authorized_keys
    chown -R ${ARCHERY_USER}:${ARCHERY_USER} /home/${ARCHERY_USER}/.ssh
    echo "  ✓ SSH 公钥已写入"
else
    echo "  ⚠ SSH_PUBLIC_KEY 未提供，跳过。请手动："
    echo "     ssh-copy-id -i ~/.ssh/archery_deploy.pub archery@${SERVER_IP}"
fi

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
        systemctl reload-or-restart archery-prod-gunicorn > /dev/null 2>&1 || true
    endscript
}
EOF

echo "==> 9. MySQL 客户端验证（不创建库，由 CI/CD 跑 migrate）"
echo "  请确认 dbops 账号能登录："
echo "  mysql -h ${SERVER_IP} -P 3306 -u dbops -p"

echo "==> 10. cloudflared 安装（钉钉回调隧道用）"
ARCH=$(uname -m)
case "${ARCH}" in
    x86_64) DEB_ARCH="amd64" ;;
    aarch64) DEB_ARCH="arm64" ;;
    *) echo "不支持的架构: ${ARCH}"; exit 1 ;;
esac
curl -L "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${DEB_ARCH}.deb" -o /tmp/cloudflared.deb
dpkg -i /tmp/cloudflared.deb
rm /tmp/cloudflared.deb
cloudflared --version

echo "==> 11. 备份 GPG 密钥（用于加密 MySQL dump）"
GPG_PASSPHRASE=$(openssl rand -hex 32)
echo "${GPG_PASSPHRASE}" > /etc/archery/backup_passphrase
chmod 600 /etc/archery/backup_passphrase
echo "  备份密钥已存 /etc/archery/backup_passphrase（root only）"
echo "  ⚠ 务必备份这个文件到密码管理器，丢失将无法解密备份"

echo "==> 初始化完成"
echo ""
echo "下一步："
echo "  1. 在 GitHub Repo Settings > Secrets 添加 SSH_PRIVATE_KEY / DINGTALK_NOTIFY_WEBHOOK"
echo "  2. 手动验证 SSH：ssh archery@${SERVER_IP}"
echo "  3. 配置 Cloudflare Tunnel（详见 §5.6）"
echo "  4. 创建 .env 文件（从 .env.example 复制并填入）"
echo "  5. 第一次部署由 CI/CD 自动完成"
```

### 4.2 SSH 密钥对（CI/CD 部署用）

```bash
# 在本地（开发机）生成密钥对
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/archery_deploy_key

# 公钥传到服务器（运行时作为环境变量）
export SSH_PUBLIC_KEY="$(cat ~/.ssh/archery_deploy_key.pub)"
ssh root@172.20.2.134 "SSH_PUBLIC_KEY='${SSH_PUBLIC_KEY}' bash -s" < scripts/deploy/01_init_server.sh

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
# 通用部署脚本（systemd 版本）
# 用法：./02_deploy.sh <env> <version>
#   env: dev | staging | prod
#   version: git commit hash / tag / branch

set -euo pipefail

ENV="${1:?Usage: $0 <env> <version>}"
VERSION="${2:?Usage: $0 <env> <version>}"
REPO="https://github.com/adauncle/archerydev.git"

case "${ENV}" in
    dev)     PORT=9001; DB="archery_dev";     WORKERS=1; REPO_DIR="/opt/archery/dev"     ;;
    staging) PORT=9002; DB="archery_staging"; WORKERS=2; REPO_DIR="/opt/archery/staging" ;;
    prod)    PORT=9003; DB="archery_prod";    WORKERS=4; REPO_DIR="/opt/archery/prod"    ;;
    *)       echo "Unknown env: ${ENV}"; exit 1 ;;
esac

ARCHERY_USER="archery"
SHARED_DIR="/opt/archery/shared"
LOG_DIR="/var/log/archery"

echo "==> 部署 [${ENV}] 版本 [${VERSION}] 端口 [${PORT}]"

# 1) 拉代码
echo "  1. 拉代码..."
sudo -u ${ARCHERY_USER} -H bash -c "
    cd ${REPO_DIR} 2>/dev/null || git clone ${REPO} ${REPO_DIR}
    cd ${REPO_DIR}
    git fetch --all --prune
    git checkout ${VERSION}
    git log -1 --oneline
"

# 2) 装依赖
echo "  2. 装依赖..."
sudo -u ${ARCHERY_USER} -H bash -c "
    cd ${REPO_DIR}
    python3.11 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
"

# 3) 加载 .env
if [ ! -f "${REPO_DIR}/.env" ]; then
    echo "  ERROR: .env 不存在"
    echo "  cp .env.example .env && 编辑填入真实配置"
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
systemctl restart archery-${ENV}-gunicorn.service
systemctl restart archery-${ENV}-celery-worker.service 2>/dev/null || true
systemctl restart archery-${ENV}-celery-beat.service 2>/dev/null || true

# 7) 健康检查
echo "  6. 健康检查..."
HEALTH_URL="http://127.0.0.1:${PORT}/healthz"
for i in {1..10}; do
    if curl -fsS "${HEALTH_URL}" > /dev/null; then
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

# 8) 通知
echo "  7. 通知钉钉群..."
DEPLOY_MSG="✓ Archery ${ENV} 部署成功\n版本: ${VERSION}\n时间: $(date '+%Y-%m-%d %H:%M:%S')\n服务器: 172.20.2.134"
DINGTALK_WEBHOOK=$(cat /etc/archery/dingtalk_webhook 2>/dev/null || echo "")
if [ -n "${DINGTALK_WEBHOOK}" ]; then
    curl -X POST "${DINGTALK_WEBHOOK}" \
        -H "Content-Type: application/json" \
        -d "{\"msgtype\": \"text\", \"text\": {\"content\": \"${DEPLOY_MSG}\"}}"
fi

echo "==> 部署完成"
```

### 5.2 systemd 单元文件

`/etc/systemd/system/archery-prod-gunicorn.service`：

```ini
[Unit]
Description=Archery Production Gunicorn
After=network.target mysql.service redis-server.service
Requires=redis-server.service

[Service]
Type=simple
User=archery
Group=archery
WorkingDirectory=/opt/archery/prod
EnvironmentFile=/opt/archery/prod/.env
ExecStart=/opt/archery/prod/venv/bin/gunicorn archery.wsgi:application \
    -w 4 \
    -b 127.0.0.1:9003 \
    --access-logfile - \
    --error-logfile - \
    --timeout 120 \
    --graceful-timeout 30 \
    --keep-alive 5
Restart=always
RestartSec=5
StartLimitBurst=3
StartLimitInterval=300

# 安全加固
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/archery /var/log/archery

# 资源限制
LimitNOFILE=65536
MemoryMax=2G

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/archery-prod-celery-worker.service`：

```ini
[Unit]
Description=Archery Production Celery Worker
After=network.target mysql.service redis-server.service
Requires=redis-server.service

[Service]
Type=simple
User=archery
Group=archery
WorkingDirectory=/opt/archery/prod
EnvironmentFile=/opt/archery/prod/.env
ExecStart=/opt/archery/prod/venv/bin/celery \
    -A archery worker \
    -l info \
    --concurrency=4
Restart=always
RestartSec=5

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/archery /var/log/archery

LimitNOFILE=65536
MemoryMax=2G

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/archery-prod-celery-beat.service`：

```ini
[Unit]
Description=Archery Production Celery Beat
After=network.target mysql.service redis-server.service
Requires=redis-server.service

[Service]
Type=simple
User=archery
Group=archery
WorkingDirectory=/opt/archery/prod
EnvironmentFile=/opt/archery/prod/.env
ExecStart=/opt/archery/prod/venv/bin/celery \
    -A archery beat \
    -l info
Restart=always
RestartSec=5

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/archery /var/log/archery

[Install]
WantedBy=multi-user.target
```

`staging` 和 `dev` 的 .service 文件类似，端口/路径/工作目录不同。

### 5.3 nginx 配置（HTTP，无 SSL）

`/etc/nginx/sites-available/archery.conf`：

```nginx
# upstream 定义
upstream archery_prod {
    server 127.0.0.1:9003 fail_timeout=0;
}

upstream archery_staging {
    server 127.0.0.1:9002 fail_timeout=0;
}

upstream archery_dev {
    server 127.0.0.1:9001 fail_timeout=0;
}

# 主服务器：HTTP 80 端口
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name 172.20.2.134 _;
    client_max_body_size 50M;

    # 访问控制：限制为内网 IP
    set $allowed 0;
    if ($remote_addr ~* "^10\.") { set $allowed 1; }
    if ($remote_addr ~* "^172\.16\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.17\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.18\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.19\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.20\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.21\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.22\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.23\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.24\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.25\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.26\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.27\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.28\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.29\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.30\." ) { set $allowed 1; }
    if ($remote_addr ~* "^172\.31\." ) { set $allowed 1; }
    if ($remote_addr ~* "^192\.168\.") { set $allowed 1; }
    if ($remote_addr = 127.0.0.1) { set $allowed 1; }

    # 默认 403（白名单外的访问）
    if ($allowed = 0) { return 403; }

    # 静态文件
    location /static/ {
        alias /opt/archery/shared/static/;
        expires 7d;
    }
    location /media/ {
        alias /opt/archery/shared/media/;
    }

    # 健康检查（不限 IP，给 CI/CD 用）
    location = /healthz {
        proxy_pass http://archery_prod;
        access_log off;
    }

    # 钉钉 OA 回调（仅允许 cloudflared 访问 → 127.0.0.1）
    location /dingtalk/oa/callback {
        # 仅允许本地访问（Cloudflare Tunnel 通过 127.0.0.1 转发）
        allow 127.0.0.1;
        deny all;

        proxy_pass http://archery_prod;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # 路径分流：/staging / /dev
    location /staging/ {
        rewrite ^/staging/(.*)$ /$1 break;
        proxy_pass http://archery_staging;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location /dev/ {
        rewrite ^/dev/(.*)$ /$1 break;
        proxy_pass http://archery_dev;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # 主应用
    location / {
        proxy_pass http://archery_prod;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }
}
```

**关键安全点**：
- HTTP 但用 IP 白名单（10.x / 172.16-31.x / 192.168.x / 127.0.0.1）
- 外网直接访问 `http://172.20.2.134` 会被 403
- 仅内网（办公网/VPN）能访问
- 钉钉回调额外限制只允许 127.0.0.1（Cloudflare Tunnel 转发来的）

### 5.4 健康检查 endpoint

`archery/urls.py` 加一行（最小侵入）：

```python
# archery/urls.py 末尾追加
from django.http import JsonResponse

def healthz(request):
    """健康检查 endpoint（供 CI/CD 和监控用）"""
    try:
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
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

---

## 5.6 钉钉回调 Cloudflare Tunnel 配置

### 5.6.1 为什么需要 Tunnel

**问题**：钉钉 OA 回调 URL 必须 HTTPS，172.20.2.134 没有 SSL 证书，也没公网 443。

**方案**：Cloudflare Tunnel

- Cloudflare 提供**自动 HTTPS 证书**
- `cloudflared` 客户端在 172.20.2.134 上**主动建立 outbound 连接**到 Cloudflare 边缘
- 不需要在服务器上开 443 端口，不需要公网 IP
- 钉钉后台配置回调 URL：`https://archery-oa.your-domain.com/dingtalk/oa/callback`
- 数据流：钉钉 → Cloudflare 边缘（HTTPS） → Tunnel（加密） → cloudflared → nginx → Archery

### 5.6.2 前置条件

1. **域名**：你必须有可控的域名（如 `your-company.com`）
2. **Cloudflare 账号**：免费版即可
3. **域名 NS**：已切到 Cloudflare（必须的，否则 Cloudflare 不能管理该域名）

### 5.6.3 配置步骤

#### 步骤 1：登录 Cloudflare 创建 Tunnel

```bash
# 在 172.20.2.134 上（root）
cloudflared tunnel login
# 浏览器会打开 Cloudflare 授权页面，选择你的域名
```

#### 步骤 2：创建 Tunnel

```bash
cloudflared tunnel create archery-oa
# 输出：Tunnel credentials written to /root/.cloudflared/<TUNNEL_ID>.json
# 记下 TUNNEL_ID，类似：a1b2c3d4-e5f6-...
```

#### 步骤 3：配置 Tunnel

`/etc/cloudflared/config.yml`：

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /etc/cloudflared/<TUNNEL_ID>.json

ingress:
  # 钉钉 OA 回调：所有路径转发到 80 端口
  - hostname: archery-oa.your-domain.com
    service: http://127.0.0.1:80
    originRequest:
      noTLSVerify: false
      connectTimeout: 30s
      keepAliveConnections: 100
  # 兜底：未匹配的主机名返回 404
  - service: http_status:404
```

#### 步骤 4：DNS 解析

```bash
cloudflared tunnel route dns archery-oa archery-oa.your-domain.com
# 自动在 Cloudflare DNS 添加 CNAME 记录
```

#### 步骤 5：systemd 管理 cloudflared

`/etc/systemd/system/cloudflared.service`：

```ini
[Unit]
Description=Cloudflare Tunnel for Archery DingTalk Callback
After=network.target

[Service]
Type=notify
User=root
ExecStart=/usr/local/bin/cloudflared tunnel run archery-oa
Restart=always
RestartSec=5

# 安全加固
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=false
PrivateTmp=true

# 资源
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable cloudflared
systemctl start cloudflared
systemctl status cloudflared
```

#### 步骤 6：验证 Tunnel 工作

```bash
# 在 172.20.2.134 上
curl -fsS http://127.0.0.1:80/dingtalk/oa/callback -X POST -d "{}"
# 应该返回 403（因为没有签名）而不是 404

# 测 Cloudflare 边缘
curl -fsS https://archery-oa.your-domain.com/dingtalk/oa/callback -X POST -d "{}"
# 应该走 Tunnel 回到 172.20.2.134，返回 403
```

#### 步骤 7：钉钉后台配置

1. 钉钉开放平台 → 应用 → **事件订阅**
2. 回调 URL 填：`https://archery-oa.your-domain.com/dingtalk/oa/callback`
3. 加密方式选 **AES 加密 + SHA1 签名**
4. Token 和 AES Key 复制到服务器 `.env`：
   ```
   DINGTALK_OA_CALLBACK_TOKEN=...
   DINGTALK_OA_CALLBACK_AES_KEY=...
   ```

### 5.6.4 Tunnel 故障排查

```bash
# 1. 看 cloudflared 状态
systemctl status cloudflared
journalctl -u cloudflared -f

# 2. 测试连接
cloudflared tunnel info archery-oa

# 3. 重新安装
systemctl restart cloudflared
cloudflared tunnel run archery-oa  # 手动跑，看日志

# 4. 删除重建
cloudflared tunnel delete archery-oa
cloudflared tunnel create archery-oa
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
    environment: staging
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
          curl -fsS http://172.20.2.134:9002/healthz

      - name: Notify on failure
        if: failure()
        run: |
          curl -X POST "${{ secrets.DINGTALK_NOTIFY_WEBHOOK }}" \
            -H "Content-Type: application/json" \
            -d "{\"msgtype\": \"text\", \"text\": {\"content\": \"✗ Archery Staging 部署失败 - ${{ github.run_id }}\"}}"
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
      url: http://172.20.2.134
    # production 环境在 GitHub Repo Settings 中配置 Required reviewers（项目 owner）

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
          curl -fsS http://172.20.2.134:9003/healthz

      - name: Notify
        if: always()
        run: |
          STATUS="${{ job.status == 'success' && '✓ 部署成功' || '✗ 部署失败' }}"
          curl -X POST "${{ secrets.DINGTALK_NOTIFY_WEBHOOK }}" \
            -H "Content-Type: application/json" \
            -d "{\"msgtype\": \"text\", \"text\": {\"content\": \"${STATUS}: Archery ${{ steps.version.outputs.VERSION }} - ${{ github.run_id }}\"}}"
```

### 6.5 GitHub Environments 配置

在 GitHub Repo → Settings → Environments：

**staging**：
- 无需审批
- Secrets: `SSH_PRIVATE_KEY`, `DINGTALK_NOTIFY_WEBHOOK`

**production**：
- **Required reviewers**: 1+（项目 owner，即你自己）
- Wait timer: 5 分钟（给审批人思考时间）
- Secrets: 同 staging

### 6.6 GitHub Secrets 配置

| Secret | 用途 |
|--------|------|
| `SSH_PRIVATE_KEY` | CI/CD 部署用 SSH 私钥（archery 用户的 ed25519 密钥）|
| `DINGTALK_NOTIFY_WEBHOOK` | 部署结果通知到钉钉群（复用以有的 DBA 群）|

**绝不能上传到 Secrets 的**：
- 数据库密码 → 写在服务器 `.env`（已 gitignore）
- 钉钉 AppSecret → 写在服务器 `.env`（已 gitignore）
- Redis 密码 → 自动生成，存服务器 `/etc/archery/redis_password`
- 任何真实凭据

### 6.7 Release 流程（人工）

```bash
# 1. 确认 main 分支已合并所有 PR，且 CI 通过
git checkout main
git pull

# 2. 打 tag（按 SemVer）
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

`/opt/archery/scripts/monitor/check_health.sh`：

```bash
#!/usr/bin/env bash
# 每 5 分钟跑一次（systemd timer）
# 健康检查失败时告警

set -e

HEALTH_URL="http://172.20.2.134:9003/healthz"
DINGTALK_WEBHOOK=$(cat /etc/archery/dingtalk_webhook 2>/dev/null || echo "")

response=$(curl -fsS -o /tmp/healthz.json -w "%{http_code}" --max-time 10 ${HEALTH_URL} 2>&1 || echo "000")

if [ "$response" != "200" ]; then
    msg="🚨 Archery 健康检查失败\nURL: ${HEALTH_URL}\nHTTP: ${response}\nTime: $(date)"
    if [ -n "${DINGTALK_WEBHOOK}" ]; then
        curl -X POST "${DINGTALK_WEBHOOK}" \
            -H "Content-Type: application/json" \
            -d "{\"msgtype\": \"text\", \"text\": {\"content\": \"${msg}\"}}"
    fi
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

`/etc/systemd/system/archery-monitor.service`：

```ini
[Unit]
Description=Archery health check

[Service]
Type=oneshot
ExecStart=/opt/archery/scripts/monitor/check_health.sh
User=root
```

```bash
systemctl daemon-reload
systemctl enable archery-monitor.timer
systemctl start archery-monitor.timer
```

### 7.3 备份脚本

`scripts/deploy/04_backup.sh`：

```bash
#!/usr/bin/env bash
# 每日备份：MySQL + media + .env 模板
# cron: 0 2 * * *

set -euo pipefail

BACKUP_DIR="/opt/archery/shared/backups"
DATE=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=30

mkdir -p ${BACKUP_DIR}

# 1. 加载 .env
source /opt/archery/prod/.env

# 2. MySQL dump
echo "==> 备份 MySQL..."
mysqldump -h ${MYSQL_HOST} -P ${MYSQL_PORT} -u ${MYSQL_USER} -p${MYSQL_PASSWORD} \
    --single-transaction --routines --triggers \
    --databases archery_prod archery_staging archery_dev > ${BACKUP_DIR}/mysql_${DATE}.sql

# 3. 加密备份
GPG_PASSPHRASE=$(cat /etc/archery/backup_passphrase)
gpg --batch --yes --passphrase "${GPG_PASSPHRASE}" \
    -c ${BACKUP_DIR}/mysql_${DATE}.sql
rm ${BACKUP_DIR}/mysql_${DATE}.sql

# 4. 备份 media
tar czf ${BACKUP_DIR}/media_${DATE}.tar.gz /opt/archery/shared/media/

# 5. 清理 30 天前的备份
find ${BACKUP_DIR} -name "*.sql.gpg" -mtime +${KEEP_DAYS} -delete
find ${BACKUP_DIR} -name "*.tar.gz" -mtime +${KEEP_DAYS} -delete

echo "==> 备份完成：${DATE}"
```

cron 配置：

```bash
# /etc/cron.d/archery-backup
0 2 * * * root /opt/archery/scripts/deploy/04_backup.sh >> /var/log/archery/backup.log 2>&1
```

### 7.4 关键监控指标

| 指标 | 工具 | 阈值 | 告警 |
|------|------|------|------|
| 服务存活 | curl /healthz | 5xx | 钉钉群 |
| MySQL 连接 | 内部检查 | 失败 | 钉钉群 |
| Redis 连接 | 内部检查 | 失败 | 钉钉群 |
| 磁盘空间 | df -h | > 85% | 钉钉群 |
| CPU / 内存 | top | > 90% | 钉钉群 |
| 备份成功 | cron log | 失败 | 钉钉群 |
| Cloudflare Tunnel | cloudflared status | 异常 | 钉钉群 |

---

## 8. 故障排查 Runbook

### 8.1 服务起不来

```bash
# 1. 看 systemd 状态
systemctl status archery-prod-gunicorn.service

# 2. 看具体错误
journalctl -u archery-prod-gunicorn.service -n 100

# 3. 手动起一下看错误
sudo -u archery -H bash -c "
    cd /opt/archery/prod
    source venv/bin/activate
    set -a; source .env; set +a
    gunicorn archery.wsgi:application -w 1 -b 127.0.0.1:9003
"

# 4. 常见原因：
#    - .env 没配 → 检查 /opt/archery/prod/.env
#    - 数据库连不上 → mysql -h 172.20.2.134 -u dbops -p
#    - Redis 连不上 → systemctl status redis-server
#    - 端口被占 → lsof -i :9003
```

### 8.2 部署失败回滚

`scripts/deploy/03_rollback.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

ENV="${1}"
PREV_VERSION="${2}"

case "${ENV}" in
    prod)    REPO_DIR="/opt/archery/prod"    ;;
    staging) REPO_DIR="/opt/archery/staging" ;;
    dev)     REPO_DIR="/opt/archery/dev"     ;;
esac

sudo -u archery -H bash -c "
    cd ${REPO_DIR}
    git checkout ${PREV_VERSION}
"
systemctl restart archery-${ENV}-gunicorn.service
```

### 8.3 数据库锁死

```bash
mysql -h 172.20.2.134 -u root -p -e "
    SELECT * FROM information_schema.INNODB_TRX\G
"
# 杀长事务
mysql -h 172.20.2.134 -u root -p -e "
    SELECT trx_mysql_thread_id FROM information_schema.INNODB_TRX
    WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > 60;
    -- 拿到 thread_id 后 KILL <id>
"
```

### 8.4 钉钉回调异常

```bash
# 1. 看 nginx access log
tail -f /var/log/nginx/access.log | grep dingtalk

# 2. 看应用日志
journalctl -u archery-prod-gunicorn.service -f | grep -i dingtalk

# 3. 看 cloudflared 状态
systemctl status cloudflared
journalctl -u cloudflared -f

# 4. 看 event log
mysql -h 172.20.2.134 -u ${MYSQL_USER} -p -e "
    SELECT * FROM ext_dingtalk_oa_event_log 
    WHERE processed=0 
    ORDER BY created_at DESC LIMIT 20;
"
```

### 8.5 Cloudflare Tunnel 不通

```bash
# 1. 看 cloudflared 日志
journalctl -u cloudflared -n 100

# 2. 测试 tunnel
cloudflared tunnel info archery-oa

# 3. 测试 nginx 是否监听 80
curl -fsS http://127.0.0.1:80/dingtalk/oa/callback -X POST -d "{}"

# 4. 重启 tunnel
systemctl restart cloudflared

# 5. 完全重建
cloudflared tunnel delete archery-oa
cloudflared tunnel create archery-oa
# 重新配置 ingress
systemctl restart cloudflared
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
| **HTTP 无 SSL** | 中间人攻击、数据明文 | nginx IP 白名单（内网/VPN 访问）+ 钉钉走 Cloudflare HTTPS |
| **dev/staging/prod 一体** | 测试影响生产 | systemd 多实例 + 端口隔离（9001/9002/9003）+ 域名路径分流 |
| **Cloudflare Tunnel 中断** | 钉钉 OA 不可用 | 见 v0.7 §10.4 降级策略（自动回退 archery 审批）|
| 密钥泄露 | 严重安全事故 | 密钥只存服务器 `/etc/archery/` (600 权限) + GitHub Secrets，不进 git |

### 9.2 回滚时间表

| 场景 | 目标恢复时间 | 方式 |
|------|--------------|------|
| 代码 bug | < 2 分钟 | `git checkout <prev_tag> && systemctl restart` |
| 数据库迁移 bug | < 5 分钟 | 备份恢复 + 切换代码版本 |
| 配置文件错 | < 1 分钟 | 还原 .env 备份 |
| 服务器硬件故障 | 30+ 分钟 | 重新初始化（按 §4）|
| Cloudflare Tunnel 故障 | < 1 分钟 | 自动降级到本地 Group 审批（v0.7 §10.4）|

---

## 10. 阶段化实施

| 阶段 | 内容 | 估时 | 依赖 |
|------|------|------|------|
| **0. 仓库推送** | 推 `archery_dev` 到 GitHub `adauncle/archerydev` | 0.5 天 | - |
| **1. 服务器初始化** | `01_init_server.sh` 在 172.20.2.134 跑一次（含 Redis + cloudflared）| 1 天 | 0 |
| **2. SSH 密钥对 + GitHub Secrets** | 生成密钥 + 公钥贴服务器 + 私钥存 GitHub Secrets | 0.5 天 | 1 |
| **3. .env 文件** | 手动创建 .env（含 dbops 密码、Redis 密码等）| 0.5 天 | 1 |
| **4. CI workflow 上线** | `.github/workflows/ci.yml` 启用 | 0.5 天 | 0 |
| **5. CD Staging** | push to main 自动部署 staging + 健康检查 | 1 天 | 1, 2, 3, 4 |
| **6. CD Prod + 人工审批** | tag 触发 + GitHub Environments 审批 | 1 天 | 5 |
| **7. Cloudflare Tunnel** | 配置 Tunnel + 钉钉后台配置回调 URL | 1 天 | 1 |
| **8. 监控 + 备份** | 健康检查 systemd timer + 备份 cron | 1 天 | 1 |
| **9. Runbook + 演练** | 演练一次完整部署 + 钉钉回调 | 1 天 | 5, 6, 7 |

**总计**：约 8 个工作日（不含首次部署后 1-2 天观察期）

---

## 11. 已拍板决策（全部 ✅）

| # | 决策项 | 选择 |
|---|--------|------|
| 1 | CI/CD 工具 | GitHub Actions |
| 2 | 部署触发 | push main + tag v* |
| 3 | 环境定位 | dev/staging/prod 一体 |
| 4 | 主服务 SSL | ❌ 不需要 |
| 5 | 域名 | ❌ 用 IP `172.20.2.134` |
| 6 | 钉钉回调 SSL | ✅ Cloudflare Tunnel |
| 7 | 钉钉通知 webhook | ✅ 复用 DBA 群 |
| 8 | 备份保留期 | 30 天 |
| 9 | Redis 密码 | ✅ 自动生成 |
| 10 | 服务管理 | systemd（不是 supervisor）|
| 11 | 初始化策略 | migrate + seed |
| 12 | GitHub reviewer | 项目 owner（你自己）|

---

## 12. 附录

### 12.1 目录结构（部署后）

```
/opt/archery/
├── prod/                      # 生产代码
│   ├── venv/                  # Python 虚拟环境
│   ├── .env                   # 真实配置（root only 600）
│   ├── archery/, sql/, ...
│   └── manage.py
├── staging/                   # staging 代码
├── dev/                       # dev 代码
├── shared/
│   ├── logs/
│   ├── media/                 # 用户上传
│   ├── static/                # 静态文件
│   ├── backups/               # 备份
│   └── run/
├── scripts/
│   ├── deploy/
│   │   ├── 01_init_server.sh
│   │   ├── 02_deploy.sh
│   │   ├── 03_rollback.sh
│   │   └── 04_backup.sh
│   └── monitor/
│       └── check_health.sh
└── .ssh/
    └── authorized_keys         # GitHub Actions 部署用公钥

/etc/systemd/system/
├── archery-prod-gunicorn.service
├── archery-prod-celery-worker.service
├── archery-prod-celery-beat.service
├── archery-staging-gunicorn.service
├── archery-staging-celery-worker.service
├── archery-staging-celery-beat.service
├── archery-dev-gunicorn.service
├── cloudflared.service        # 钉钉回调隧道
├── archery-monitor.timer      # 健康检查定时器
└── archery-monitor.service    # 健康检查执行单元

/etc/nginx/sites-available/
└── archery.conf

/etc/cloudflared/
├── config.yml                 # Tunnel 配置
└── <TUNNEL_ID>.json           # Tunnel 凭据

/etc/archery/
├── redis_password             # Redis 密码（600 权限）
├── backup_passphrase          # 备份加密密码（600 权限）
└── dingtalk_webhook           # 钉钉通知 webhook

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
- [systemd 文档](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [nginx 文档](https://nginx.org/en/docs/)
- [Cloudflare Tunnel 文档](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
- [钉钉开放平台 - 智能工作流](https://open.dingtalk.com/document/orgapp/approval-process)
- 配套设计：[钉钉 OA 联动 v0.7](./2026-07-20_dingtalk-oa-workflow.md)

---

**文档版本**：v0.9
**最后更新**：2026-07-20（v0.8 → v0.9：12 个决策已全部拍板，新增 §5.6 Cloudflare Tunnel 钉钉回调配置，supervisor 改为 systemd）
