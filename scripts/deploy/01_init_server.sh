#!/usr/bin/env bash
## CUSTOM-NEW: 服务器一次性初始化（系统包 + Redis + cloudflared + 防火墙 + 用户 + 目录）@ 2026-07-20 @ devops-agent
##
## 设计依据：docs/designs/2026-07-20_devops-cicd.md §4.1
## 目标服务器：172.20.2.134（项目 owner 的部署机）
## 运行方式：以 root 身份在服务器上一次性执行
##   1) 先在本地生成 SSH 密钥对：ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/archery_deploy_key
##   2) 公钥通过环境变量传入：export SSH_PUBLIC_KEY="$(cat ~/.ssh/archery_deploy_key.pub)"
##   3) 上传并执行：  scp scripts/deploy/01_init_server.sh root@172.20.2.134:/tmp/
##                    ssh root@172.20.2.134 "SSH_PUBLIC_KEY='${SSH_PUBLIC_KEY}' bash /tmp/01_init_server.sh"
##
## 前置条件：
##   1. Ubuntu 22.04 LTS（root 身份，sudo 可用）
##   2. 出口网络可达 github.com / cloudflared binary CDN
##   3. SSH_PUBLIC_KEY 环境变量（可选；不传则跳过 authorized_keys 写入）
##   4. MySQL 元数据库已在 172.20.2.134:3306 启动（archery 元库；脚本不创建库，由 migrate 负责）
##
## 幂等性：可重复执行
##   - 已存在的用户/目录/密钥文件会跳过
##   - Redis 密码若已存在则复用（不覆盖，便于滚动升级）
##   - UFW 规则按期望最终态重置（reset 模式）
##   - cloudflared 重复安装会被 dpkg 拦截
##
## 凭据约定：
##   - Redis 密码、backup passphrase 自动生成，存到 /etc/archery/（600 权限）
##   - SSH 私钥不入 git，存到 GitHub Secrets
##   - 数据库密码写在服务器 /opt/archery/<env>/.env（已 gitignore）

set -euo pipefail

# ============================================================================
# 路径与可调参数（可通过环境变量覆盖）
# ============================================================================

ARCHERY_USER="${ARCHERY_USER:-archery}"
ARCHERY_HOME="${ARCHERY_HOME:-/opt/archery}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
SERVER_IP="${SERVER_IP:-172.20.2.134}"

# 凭据文件
ARCHERY_CONF_DIR="${ARCHERY_CONF_DIR:-/etc/archery}"
REDIS_PASSWORD_FILE="${REDIS_PASSWORD_FILE:-${ARCHERY_CONF_DIR}/redis_password}"
BACKUP_PASSPHRASE_FILE="${BACKUP_PASSPHRASE_FILE:-${ARCHERY_CONF_DIR}/backup_passphrase}"
SSH_AUTHORIZED_KEYS_FILE="${SSH_AUTHORIZED_KEYS_FILE:-/home/${ARCHERY_USER}/.ssh/authorized_keys}"

# 日志
LOG_FILE="${LOG_FILE:-/var/log/archery/init.log}"

# 钉钉通知 webhook（可选，失败时告警）
DINGTALK_WEBHOOK_FILE="${DINGTALK_WEBHOOK_FILE:-${ARCHERY_CONF_DIR}/dingtalk_webhook}"

# 临时目录
TMP_DIR="${TMPDIR:-/tmp}"

# ============================================================================
# 工具函数
# ============================================================================

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "${msg}"
    if [ -w "$(dirname "${LOG_FILE}")" ] 2>/dev/null; then
        echo "${msg}" >> "${LOG_FILE}" 2>/dev/null || true
    fi
}

notify_dingtalk() {
    # 可选：失败时通知钉钉群
    local content="$1"
    if [ ! -r "${DINGTALK_WEBHOOK_FILE}" ]; then
        return 0
    fi
    local webhook
    webhook="$(cat "${DINGTALK_WEBHOOK_FILE}" 2>/dev/null || true)"
    [ -z "${webhook}" ] && return 0

    local payload
    if command -v jq >/dev/null 2>&1; then
        payload="$(jq -Rn --arg c "${content}" '{msgtype:"text",text:{content:$c}}')"
    else
        payload="$(python3 -c 'import json,sys;print(json.dumps({"msgtype":"text","text":{"content":sys.argv[1]}}))' "${content}" 2>/dev/null || echo '')"
    fi
    [ -z "${payload}" ] && return 0
    curl -fsS --max-time 5 \
        -X POST "${webhook}" \
        -H "Content-Type: application/json" \
        -d "${payload}" >/dev/null 2>&1 || true
}

die() {
    log "ERROR: $*"
    notify_dingtalk "🚨 Archery 服务器初始化失败\n原因: $*\n时间: $(date '+%Y-%m-%d %H:%M:%S')"
    exit 1
}

cleanup() {
    rm -f "${TMP_DIR}/cloudflared.deb" \
          "${TMP_DIR}/redis.conf.patch" \
          "${TMP_DIR}/mysqldump.err" 2>/dev/null || true
}
trap cleanup EXIT

# ============================================================================
# 前置条件检查
# ============================================================================

[ "$(id -u)" -eq 0 ] || die "请用 root 运行（创建用户、改 ssh、写 /etc/ 都需要 root）"

# 探测包管理器
if ! command -v apt >/dev/null 2>&1; then
    die "未检测到 apt，脚本目前只支持 Ubuntu/Debian 系"
fi

command -v systemctl >/dev/null 2>&1 || die "未检测到 systemctl（非 systemd 系统不支持）"

# ============================================================================
# 准备
# ============================================================================

log "==> 初始化开始：服务器 ${SERVER_IP}"

mkdir -p "${ARCHERY_CONF_DIR}" /var/log/archery
chmod 700 "${ARCHERY_CONF_DIR}"
touch "${LOG_FILE}"
chmod 640 "${LOG_FILE}"

# ============================================================================
# 1. 系统包更新
# ============================================================================

log "==> 1. 系统包更新"
# 失败也允许继续（apt update 偶尔会因 CDN 抖动失败，但本机已装的包通常能装新包）
if ! apt update; then
    log "  WARN: apt update 失败，继续尝试安装（可能是上游 CDN 抖动）"
fi
# 无人值守升级：-y 避免交互；DEBIAN_FRONTEND=noninteractive 避免 tzdata 等弹窗
DEBIAN_FRONTEND=noninteractive apt upgrade -y

# ============================================================================
# 2. 基础依赖安装
# ============================================================================

log "==> 2. 基础依赖安装"
# 注意：故意不装 certbot（无 SSL 设计，决策 #4）
# 故意不装 supervisor（用 systemd，决策 #10）
DEBIAN_FRONTEND=noninteractive apt install -y \
    build-essential \
    curl wget git vim ca-certificates gnupg lsb-release \
    "python${PYTHON_VERSION}" python3-pip python3-venv python3-dev \
    default-libmysqlclient-dev pkg-config default-mysql-client \
    redis-server \
    nginx \
    ufw fail2ban \
    cron logrotate \
    openssl \
    jq

# ============================================================================
# 3. Redis 配置
# ============================================================================

log "==> 3. Redis 配置"

# 3.1 自动生成或复用 Redis 密码
if [ -r "${REDIS_PASSWORD_FILE}" ] && [ -s "${REDIS_PASSWORD_FILE}" ]; then
    REDIS_PASSWORD="$(cat "${REDIS_PASSWORD_FILE}")"
    log "  复用已有 Redis 密码（${REDIS_PASSWORD_FILE}）"
else
    # 24 字节随机 = 48 个十六进制字符，强度足够
    REDIS_PASSWORD="$(openssl rand -hex 24)"
    echo "${REDIS_PASSWORD}" > "${REDIS_PASSWORD_FILE}"
    chmod 600 "${REDIS_PASSWORD_FILE}"
    log "  生成新 Redis 密码，已存到 ${REDIS_PASSWORD_FILE}"
fi

# 3.2 备份原配置并 patch
REDIS_CONF="/etc/redis/redis.conf"
REDIS_CONF_BAK="${REDIS_CONF}.bak.$(date +%Y%m%d_%H%M%S)"
if [ ! -f "${REDIS_CONF_BAK}" ] && [ -f "${REDIS_CONF}" ]; then
    cp -a "${REDIS_CONF}" "${REDIS_CONF_BAK}"
    log "  Redis 原始配置备份: ${REDIS_CONF_BAK}"
fi

# 3.3 用 sed 在文件末尾追加配置（避免直接覆盖原文件）
#    注意：sed -i 在 GNU 与 BSD 上语法不同，这里用文件追加再 sed 替换
{
    echo ""
    echo "# === Archery customization (managed by 01_init_server.sh) ==="
    echo "bind 127.0.0.1 ::1"
    echo "protected-mode yes"
    echo "requirepass ${REDIS_PASSWORD}"
    echo "maxmemory 256mb"
    echo "maxmemory-policy allkeys-lru"
} >> "${REDIS_CONF}"

# 3.4 注释掉原文件中可能冲突的旧配置（避免 requirepass 重复）
sed -i 's/^bind .*/# bind (managed by Archery init)/' "${REDIS_CONF}"
sed -i 's/^requirepass .*/# requirepass (managed by Archery init)/' "${REDIS_CONF}"
sed -i 's/^protected-mode .*/# protected-mode (managed by Archery init)/' "${REDIS_CONF}"
sed -i 's/^maxmemory .*/# maxmemory (managed by Archery init)/' "${REDIS_CONF}"
sed -i 's/^maxmemory-policy .*/# maxmemory-policy (managed by Archery init)/' "${REDIS_CONF}"

systemctl enable redis-server
systemctl restart redis-server

# 3.5 验证密码生效
#    注意：redis-cli -a 在认证失败时会输出 "NOAUTH Authentication required." 并返回非零退出码
#    但 set -e + pipefail + stderr/stdout 合并可能误报成功，所以用 set +e 显式控制 + 检查 exit code
sleep 1
set +e
pong_out="$(redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning ping 2>&1)"
pong_rc=$?
set -e
if [ "${pong_rc}" -eq 0 ] && [ "${pong_out}" = "PONG" ]; then
    log "  ✓ Redis 密码验证通过"
else
    die "Redis 密码验证失败（rc=${pong_rc}, output='${pong_out}'）"
fi

# ============================================================================
# 4. 防火墙（UFW）
# ============================================================================

log "==> 4. 防火墙（UFW）"

# 4.1 备份当前规则
if command -v ufw >/dev/null 2>&1; then
    ufw status verbose > "${TMP_DIR}/ufw_before.rules" 2>/dev/null || true
fi

# 4.2 重置为期望终态
#     钉钉回调走 Cloudflare Tunnel（outbound），不开入站 443
#     决策 #6：钉钉回调 SSL 由 Cloudflare Tunnel 提供
#     决策 #4：主服务无 SSL
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH"
ufw allow 80/tcp comment "HTTP (Archery main + DingTalk callback from cloudflared)"
# 不开 443 / 9001-9003 —— gunicorn 仅 127.0.0.1 监听，由 nginx 反代
ufw --force enable

# 4.3 启用 fail2ban
systemctl enable fail2ban
systemctl restart fail2ban || log "  WARN: fail2ban 启动失败（不影响主流程）"

log "  ✓ UFW 规则：22, 80 入站允许；其他入站默认拒绝"

# ============================================================================
# 5. 创建 archery 用户
# ============================================================================

log "==> 5. 创建 ${ARCHERY_USER} 用户"

if id "${ARCHERY_USER}" >/dev/null 2>&1; then
    log "  用户 ${ARCHERY_USER} 已存在，跳过创建"
else
    # -r: 系统用户，-m: 创建 home，-d: 指定 home，-s: 禁止登录 shell
    useradd -r -m -d "${ARCHERY_HOME}" -s /usr/sbin/nologin "${ARCHERY_USER}"
    log "  ✓ 已创建用户 ${ARCHERY_USER}（home=${ARCHERY_HOME}, shell=nologin）"
fi

# ============================================================================
# 6. 目录结构
# ============================================================================

log "==> 6. 目录结构"

# 环境隔离目录：每个环境一份独立代码 + venv
mkdir -p "${ARCHERY_HOME}/prod"
mkdir -p "${ARCHERY_HOME}/staging"
mkdir -p "${ARCHERY_HOME}/dev"

# 共享目录
mkdir -p "${ARCHERY_HOME}/shared/logs"
mkdir -p "${ARCHERY_HOME}/shared/media"
mkdir -p "${ARCHERY_HOME}/shared/static"
mkdir -p "${ARCHERY_HOME}/shared/backups"
mkdir -p "${ARCHERY_HOME}/shared/run"

# 脚本目录
mkdir -p "${ARCHERY_HOME}/scripts/deploy"
mkdir -p "${ARCHERY_HOME}/scripts/monitor"

# 日志目录（/var/log/archery，systemd service 用）
mkdir -p /var/log/archery

# 权限
chown -R "${ARCHERY_USER}:${ARCHERY_USER}" "${ARCHERY_HOME}"
chown -R "${ARCHERY_USER}:${ARCHERY_USER}" /var/log/archery
chown -R root:root "${ARCHERY_CONF_DIR}"
chmod 700 "${ARCHERY_CONF_DIR}"

log "  ✓ 目录已创建：${ARCHERY_HOME}/{prod,staging,dev}, shared/{logs,media,static,backups,run}, scripts/{deploy,monitor}"

# ============================================================================
# 7. SSH 公钥（供 GitHub Actions 部署用）
# ============================================================================

log "==> 7. SSH 公钥（GitHub Actions 部署用）"

# 注意：nologin 用户的 home 是 /opt/archery，所以 .ssh 也在那
SSH_DIR="$(eval echo "~${ARCHERY_USER}")/.ssh"
mkdir -p "${SSH_DIR}"

if [ -n "${SSH_PUBLIC_KEY:-}" ]; then
    # 用 >> 追加（多次跑不会覆盖已有 key）
    echo "${SSH_PUBLIC_KEY}" >> "${SSH_AUTHORIZED_KEYS_FILE}"
    chmod 700 "${SSH_DIR}"
    chmod 600 "${SSH_AUTHORIZED_KEYS_FILE}"
    chown -R "${ARCHERY_USER}:${ARCHERY_USER}" "${SSH_DIR}"
    log "  ✓ SSH 公钥已追加到 ${SSH_AUTHORIZED_KEYS_FILE}"
else
    log "  ⚠ SSH_PUBLIC_KEY 未提供，跳过 authorized_keys 写入"
    log "     请手动执行：ssh-copy-id -i ~/.ssh/archery_deploy.pub ${ARCHERY_USER}@${SERVER_IP}"
fi

# ============================================================================
# 8. logrotate
# ============================================================================

log "==> 8. logrotate"

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
        # 触发 systemd reload（按需重启，避免误杀）
        systemctl reload-or-restart archery-prod-gunicorn.service > /dev/null 2>&1 || true
        systemctl reload-or-restart archery-staging-gunicorn.service > /dev/null 2>&1 || true
        systemctl reload-or-restart archery-dev-gunicorn.service > /dev/null 2>&1 || true
    endscript
}

/opt/archery/shared/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0644 archery archery
    sharedscripts
}
EOF

log "  ✓ /etc/logrotate.d/archery 已写入"

# ============================================================================
# 9. cloudflared 安装（钉钉回调隧道用）
# ============================================================================

log "==> 9. cloudflared 安装"

if command -v cloudflared >/dev/null 2>&1; then
    log "  cloudflared 已安装: $(cloudflared --version 2>&1 | head -1)"
else
    ARCH="$(uname -m)"
    case "${ARCH}" in
        x86_64)  DEB_ARCH="amd64" ;;
        aarch64) DEB_ARCH="arm64" ;;
        *)
            log "  WARN: 不支持的架构 ${ARCH}，跳过 cloudflared 安装"
            log "        请手动从 https://github.com/cloudflare/cloudflared/releases 下载安装"
            DEB_ARCH=""
            ;;
    esac

    if [ -n "${DEB_ARCH}" ]; then
        CLOUDFLARED_DEB="${TMP_DIR}/cloudflared.deb"
        # 10 分钟超时（cloudflared binary ~30MB）
        if curl -fsSL --max-time 600 \
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${DEB_ARCH}.deb" \
            -o "${CLOUDFLARED_DEB}"; then
            dpkg -i "${CLOUDFLARED_DEB}" || die "dpkg 安装 cloudflared 失败"
            log "  ✓ cloudflared 安装成功: $(cloudflared --version 2>&1 | head -1)"
        else
            die "下载 cloudflared deb 包失败（网络问题？github releases 不可达？）"
        fi
    fi
fi

# cloudflared 配置文件目录
mkdir -p /etc/cloudflared
chmod 755 /etc/cloudflared

# ============================================================================
# 10. GPG 备份密码
# ============================================================================

log "==> 10. 备份 GPG 密码"

if [ -r "${BACKUP_PASSPHRASE_FILE}" ] && [ -s "${BACKUP_PASSPHRASE_FILE}" ]; then
    log "  复用已有备份密码（${BACKUP_PASSPHRASE_FILE}）"
else
    # 32 字节随机 = 64 个十六进制字符
    GPG_PASSPHRASE="$(openssl rand -hex 32)"
    echo "${GPG_PASSPHRASE}" > "${BACKUP_PASSPHRASE_FILE}"
    chmod 600 "${BACKUP_PASSPHRASE_FILE}"
    log "  ✓ 已生成新备份密码，存到 ${BACKUP_PASSPHRASE_FILE}"
fi

# ============================================================================
# 11. MySQL 客户端验证（不创建库，由 CI/CD 跑 migrate）
# ============================================================================

log "==> 11. MySQL 客户端检查"

if command -v mysql >/dev/null 2>&1; then
    log "  mysql 客户端已安装: $(mysql --version)"
    log "  请在服务器上验证 dbops 账号可登录："
    log "    mysql -h ${SERVER_IP} -P 3306 -u dbops -p"
    log "  注：本脚本不创建数据库，由 02_deploy.sh 跑 migrate 创建"
else
    log "  WARN: 未安装 mysql 客户端（基础依赖里应该装了 default-mysql-client）"
fi

# ============================================================================
# 收尾
# ============================================================================

log ""
log "==> 初始化完成"
log ""
log "下一步："
log "  1. 在 GitHub Repo Settings > Secrets 添加 SSH_PRIVATE_KEY / DINGTALK_NOTIFY_WEBHOOK"
log "  2. 手动验证 SSH：ssh -i ~/.ssh/archery_deploy_key ${ARCHERY_USER}@${SERVER_IP}"
log "  3. 创建 /opt/archery/<env>/.env（cp .env.example .env && 编辑）"
log "  4. 第一次部署：cd ${ARCHERY_HOME}/scripts/deploy && ./02_deploy.sh prod <version>"
log "  5. 配置 Cloudflare Tunnel：详见 scripts/deploy/cloudflared/README.md"
log ""
log "关键文件位置："
log "  Redis 密码:        ${REDIS_PASSWORD_FILE}"
log "  备份 GPG 密码:     ${BACKUP_PASSPHRASE_FILE}"
log "  SSH authorized:    ${SSH_AUTHORIZED_KEYS_FILE}"
log "  Archery 代码:      ${ARCHERY_HOME}/{prod,staging,dev}"
log "  共享数据:          ${ARCHERY_HOME}/shared/{logs,media,static,backups,run}"
log "  系统日志:          /var/log/archery/"
log "  Cloudflare 配置:   /etc/cloudflared/"
log ""
log "⚠ 务必备份 ${BACKUP_PASSPHRASE_FILE} 到密码管理器，丢失将无法解密 MySQL 备份"

exit 0
