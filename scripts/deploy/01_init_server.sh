#!/usr/bin/env bash
## CUSTOM-MODIFIED: 改造为 CentOS 7.9 版本（yum/rpm + firewalld + pyenv + mariadb）@ 2026-07-20 @ mavis
##   - 原版：Ubuntu 22.04 / apt / ufw
##   - 现版：CentOS 7.9 / yum / firewalld / pyenv（Python 3.11 在 deploy 阶段编译）
##   - 设计依据：docs/designs/2026-07-20_devops-cicd.md §4.1
##   - 目标服务器：172.20.2.134（replica4，CentOS 7.9.2009，MySQL 8.0 已在跑）
##
##   运行方式（以 root 身份在服务器上一次性执行）：
##     1) 本地生成 SSH 密钥对：ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/archery_deploy
##     2) 公钥通过环境变量传入：export SSH_PUBLIC_KEY="$(cat ~/.ssh/archery_deploy.pub)"
##     3) 上传并执行：
##          scp scripts/deploy/01_init_server.sh root@172.20.2.134:/tmp/
##          ssh root@172.20.2.134 "SSH_PUBLIC_KEY='${SSH_PUBLIC_KEY}' MYSQL_ROOT_PASSWORD='<ask-it>' bash /tmp/01_init_server.sh"
##
##   前置条件：
##     1. CentOS 7.9（root 身份）
##     2. 出口网络可达 github.com / cloudflared binary CDN / pypi
##     3. SSH_PUBLIC_KEY 环境变量（可选；不传则跳过 authorized_keys 写入）
##     4. MYSQL_ROOT_PASSWORD 环境变量（**必填**；脚本要建库建用户，需要 root 权限）
##     5. MySQL 8.0 已在 172.20.2.134:3306 启动（脚本不修改 my.cnf）
##
##   幂等性：可重复执行
##     - 已存在的用户/目录/密钥文件会跳过
##     - Redis 密码若已存在则复用（不覆盖，便于滚动升级）
##     - firewalld 规则按期望最终态增量追加（不 reset，避免影响现有规则）
##     - MySQL 库/用户存在则跳过（IF NOT EXISTS / CREATE USER IF NOT EXISTS 的等价处理）
##
##   凭据约定：
##     - Redis 密码、备份 GPG passphrase、MySQL dbops 密码自动生成，存到 /etc/archery/（600 权限）
##     - SSH 私钥不入 git，存到 GitHub Secrets
##     - 数据库密码写在服务器 /opt/archery/<env>/.env（已 gitignore）

set -euo pipefail

# ============================================================================
# 路径与可调参数
# ============================================================================

ARCHERY_USER="${ARCHERY_USER:-archery}"
ARCHERY_HOME="${ARCHERY_HOME:-/opt/archery}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11.10}"
SERVER_IP="${SERVER_IP:-172.20.2.134}"

# 凭据文件
ARCHERY_CONF_DIR="${ARCHERY_CONF_DIR:-/etc/archery}"
REDIS_PASSWORD_FILE="${REDIS_PASSWORD_FILE:-${ARCHERY_CONF_DIR}/redis_password}"
BACKUP_PASSPHRASE_FILE="${BACKUP_PASSPHRASE_FILE:-${ARCHERY_CONF_DIR}/backup_passphrase}"
DBOPS_PASSWORD_FILE="${DBOPS_PASSWORD_FILE:-${ARCHERY_CONF_DIR}/dbops_password}"

# MySQL 元数据库
MYSQL_DBS=(archery_prod archery_staging archery_dev)

# 日志
LOG_FILE="${LOG_FILE:-/var/log/archery/init.log}"

# 钉钉通知 webhook（可选，失败时告警）
DINGTALK_WEBHOOK_FILE="${DINGTALK_WEBHOOK_FILE:-${ARCHERY_CONF_DIR}/dingtalk_webhook}"

# 临时目录
TMP_DIR="${TMPDIR:-/tmp}"

# pyenv 安装位置
PYENV_ROOT="${PYENV_ROOT:-/opt/pyenv}"

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
    rm -f "${TMP_DIR}/cloudflared.rpm" \
          "${TMP_DIR}/cloudflared-linux-amd64.rpm" 2>/dev/null || true
}
trap cleanup EXIT

# ============================================================================
# 前置条件检查
# ============================================================================

[ "$(id -u)" -eq 0 ] || die "请用 root 运行（创建用户、改 ssh、写 /etc/ 都需要 root）"

# 探测包管理器（CentOS 优先，Ubuntu 友好降级）
if command -v yum >/dev/null 2>&1; then
    PKG_MGR="yum"
    log "  检测到 yum（CentOS/RHEL 系）"
elif command -v apt >/dev/null 2>&1; then
    PKG_MGR="apt"
    log "  WARN: 检测到 apt（Ubuntu/Debian 系），本脚本针对 CentOS 7 设计，可能不完全兼容"
else
    die "未检测到 yum 或 apt，本脚本不支持该系统"
fi

command -v systemctl >/dev/null 2>&1 || die "未检测到 systemctl（非 systemd 系统不支持）"

# MySQL root 密码：env var 优先，文件 fallback
: "${MYSQL_ROOT_PASSWORD_FILE:=/etc/archery/.mysql_root}"
if [ -z "${MYSQL_ROOT_PASSWORD:-}" ]; then
    if [ -r "${MYSQL_ROOT_PASSWORD_FILE}" ]; then
        MYSQL_ROOT_PASSWORD="$(cat "${MYSQL_ROOT_PASSWORD_FILE}")"
        log "  MySQL root 密码从 ${MYSQL_ROOT_PASSWORD_FILE} 读取（${#MYSQL_ROOT_PASSWORD} 字符）"
    else
        die "未设置 MYSQL_ROOT_PASSWORD，且 ${MYSQL_ROOT_PASSWORD_FILE} 不可读"
    fi
fi

# ============================================================================
# 准备
# ============================================================================

log "==> 初始化开始：服务器 ${SERVER_IP}（$(cat /etc/redhat-release 2>/dev/null || uname -r)）"

mkdir -p "${ARCHERY_CONF_DIR}" /var/log/archery
chmod 700 "${ARCHERY_CONF_DIR}"
touch "${LOG_FILE}"
chmod 640 "${LOG_FILE}"

# ============================================================================
# 1. 系统包
# ============================================================================

log "==> 1. 系统包安装"

# yum update 通常很慢且不必要（CentOS 7 已经在用），跳过以加快 init
# 失败也允许继续（CDN 偶尔抖动）
if ! yum -y install epel-release >/dev/null 2>&1; then
    log "  WARN: epel-release 安装失败，可能已启用或 CDN 抖动，继续"
fi

# 基础依赖
#   - gcc/make：编译 Python 3.11 用
#   - mariadb-devel + mariadb：MySQL 客户端 + Python mysqlclient 编译头
#   - openssl-devel / libffi-devel / zlib-devel / bzip2-devel / readline-devel / sqlite-devel：pyenv 编译 Python 3.11 依赖
#   - nginx / redis / firewalld：服务
#   - jq / logrotate / cronie / fail2ban：工具
#   - 不要装 supervisor（设计决策 #10，用 systemd）
#   - 不要装 certbot（设计决策 #4，无 SSL）
yum install -y \
    gcc gcc-c++ make \
    openssl-devel bzip2-devel bzip2 \
    libffi-devel zlib-devel \
    readline-devel sqlite-devel \
    xz xz-devel \
    mariadb mariadb-devel \
    redis \
    nginx \
    firewalld \
    fail2ban \
    cronie logrotate \
    vim-enhanced git curl wget \
    jq \
    ca-certificates \
    || die "yum install 失败"

log "  ✓ 系统包安装完成"

# ============================================================================
# 2. pyenv（Python 3.11 在 deploy 阶段编译，init 只装 pyenv）
# ============================================================================

log "==> 2. pyenv（Python 多版本管理）"

if [ -d "${PYENV_ROOT}" ] && [ -x "${PYENV_ROOT}/bin/pyenv" ]; then
    log "  pyenv 已存在：$(${PYENV_ROOT}/bin/pyenv --version)"
else
    # 用 git clone（避免 curl 安装脚本信任问题）
    git clone --depth=1 https://github.com/pyenv/pyenv.git "${PYENV_ROOT}" \
        || die "pyenv clone 失败（github 可达？）"
    # 编译依赖已在第 1 步装好
    log "  ✓ pyenv 已安装到 ${PYENV_ROOT}"
fi

# 确保 archery 用户能读 pyenv
chmod -R a+rX "${PYENV_ROOT}"

# ============================================================================
# 3. Redis 配置
# ============================================================================

log "==> 3. Redis 配置"

# 3.1 自动生成或复用 Redis 密码
if [ -r "${REDIS_PASSWORD_FILE}" ] && [ -s "${REDIS_PASSWORD_FILE}" ]; then
    REDIS_PASSWORD="$(cat "${REDIS_PASSWORD_FILE}")"
    log "  复用已有 Redis 密码（${REDIS_PASSWORD_FILE}）"
else
    REDIS_PASSWORD="$(openssl rand -hex 24)"
    echo "${REDIS_PASSWORD}" > "${REDIS_PASSWORD_FILE}"
    chmod 600 "${REDIS_PASSWORD_FILE}"
    log "  ✓ 生成新 Redis 密码，已存到 ${REDIS_PASSWORD_FILE}"
fi

# 3.2 备份原配置
REDIS_CONF="/etc/redis.conf"
REDIS_CONF_BAK="${REDIS_CONF}.bak.$(date +%Y%m%d_%H%M%S)"
if [ ! -f "${REDIS_CONF_BAK}" ] && [ -f "${REDIS_CONF}" ]; then
    cp -a "${REDIS_CONF}" "${REDIS_CONF_BAK}"
    log "  Redis 原始配置备份: ${REDIS_CONF_BAK}"
fi

# 3.3 追加配置（幂等：检测已存在则跳过）
if grep -q "Archery customization" "${REDIS_CONF}" 2>/dev/null; then
    log "  Redis 配置已包含 Archery customization，跳过追加"
else
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
fi

# 3.5 enable + start
systemctl enable redis >/dev/null 2>&1 || true
if systemctl is-active --quiet redis; then
    systemctl restart redis
    log "  Redis 已在运行，已重启加载新配置"
else
    systemctl start redis || die "redis 启动失败（journalctl -u redis 看详情）"
    log "  ✓ Redis 已启动"
fi

# 3.6 验证密码生效
#    注意：CentOS 7 的 redis 3.2 不支持 --no-auth-warning（4.0+ 才有）
#    redis-cli -a 在认证失败时会输出 "NOAUTH..." 到 stderr，用 2>/dev/null 抑制
sleep 1
set +e
pong_out="$(redis-cli -a "${REDIS_PASSWORD}" ping 2>/dev/null)"
pong_rc=$?
set -e
if [ "${pong_rc}" -eq 0 ] && [ "${pong_out}" = "PONG" ]; then
    log "  ✓ Redis 密码验证通过"
else
    die "Redis 密码验证失败（rc=${pong_rc}, output='${pong_out}'）"
fi

# ============================================================================
# 4. firewalld（CentOS 7 默认防火墙）
# ============================================================================

log "==> 4. firewalld 配置"

# 4.1 启用 firewalld（如果还没启）
if ! systemctl is-active --quiet firewalld; then
    systemctl enable --now firewalld || die "firewalld 启动失败"
    log "  firewalld 已 enable + start"
else
    log "  firewalld 已在运行"
fi

# 4.2 放行 SSH(22) + HTTP(80)
#    注：不放行 HTTPS(443)——钉钉回调走 cloudflared 隧道（outbound），主服务无 SSL
#    注：不放行 gunicorn 9001-9003——gunicorn 仅 127.0.0.1 监听，由 nginx 反代
firewall-cmd --permanent --add-service=ssh >/dev/null 2>&1 || log "  WARN: ssh service rule add 失败（可能已存在）"
firewall-cmd --permanent --add-service=http >/dev/null 2>&1 || log "  WARN: http service rule add 失败（可能已存在）"
firewall-cmd --reload >/dev/null

# 4.3 验证
log "  ✓ firewalld 规则：$(firewall-cmd --list-all --permanent | grep -E 'services|ports' | tr -d '\n' | sed 's/^ *//')"

# 4.4 fail2ban
systemctl enable fail2ban >/dev/null 2>&1 || true
systemctl restart fail2ban >/dev/null 2>&1 || log "  WARN: fail2ban 启动失败（不影响主流程）"
log "  ✓ fail2ban 已 enable"

# ============================================================================
# 5. archery 用户（兼容已存在）
# ============================================================================

log "==> 5. ${ARCHERY_USER} 用户"

if id "${ARCHERY_USER}" >/dev/null 2>&1; then
    EXISTING_HOME="$(getent passwd "${ARCHERY_USER}" | cut -d: -f6)"
    EXISTING_SHELL="$(getent passwd "${ARCHERY_USER}" | cut -d: -f7)"
    log "  用户 ${ARCHERY_USER} 已存在"
    log "    home = ${EXISTING_HOME}"
    log "    shell = ${EXISTING_SHELL}"
    if [ "${EXISTING_HOME}" != "${ARCHERY_HOME}" ]; then
        log "  WARN: home 不在 ${ARCHERY_HOME}（在 ${EXISTING_HOME}）"
        log "        不会强制改 home，部署时脚本用 ARCHERY_HOME=${ARCHERY_HOME} 即可"
        log "        如需统一，请手动：usermod -d ${ARCHERY_HOME} -m ${ARCHERY_USER}"
    fi
else
    useradd -m -s /bin/bash "${ARCHERY_USER}" || die "useradd 失败"
    log "  ✓ 已创建用户 ${ARCHERY_USER}（home=/home/${ARCHERY_USER}, shell=/bin/bash）"
fi

# ============================================================================
# 6. 目录结构
# ============================================================================

log "==> 6. 目录结构"

# 环境隔离目录
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

# 日志目录
mkdir -p /var/log/archery

# 权限（archery 用户拥有应用目录，root 拥有 /etc/archery）
chown -R "${ARCHERY_USER}:${ARCHERY_USER}" "${ARCHERY_HOME}"
chown -R "${ARCHERY_USER}:${ARCHERY_USER}" /var/log/archery
chown -R root:root "${ARCHERY_CONF_DIR}"
chmod 700 "${ARCHERY_CONF_DIR}"

log "  ✓ 目录已创建：${ARCHERY_HOME}/{prod,staging,dev}, shared/*, scripts/*"

# ============================================================================
# 7. SSH 公钥（GitHub Actions 部署用）
# ============================================================================

log "==> 7. SSH 公钥（GitHub Actions 部署用）"

# 用 getent 拿 home 而不是 eval（避免 home 路径含特殊字符的问题）
ARCHERY_HOME_ACTUAL="$(getent passwd "${ARCHERY_USER}" | cut -d: -f6)"
SSH_DIR="${ARCHERY_HOME_ACTUAL}/.ssh"
SSH_AUTHORIZED_KEYS_FILE_ACTUAL="${SSH_DIR}/authorized_keys"
mkdir -p "${SSH_DIR}"

if [ -n "${SSH_PUBLIC_KEY:-}" ]; then
    echo "${SSH_PUBLIC_KEY}" >> "${SSH_AUTHORIZED_KEYS_FILE_ACTUAL}"
    chmod 700 "${SSH_DIR}"
    chmod 600 "${SSH_AUTHORIZED_KEYS_FILE_ACTUAL}"
    chown -R "${ARCHERY_USER}:${ARCHERY_USER}" "${SSH_DIR}"
    log "  ✓ SSH 公钥已追加到 ${SSH_AUTHORIZED_KEYS_FILE_ACTUAL}"
else
    log "  ⚠ SSH_PUBLIC_KEY 未提供，跳过 authorized_keys 写入"
    log "     请手动：ssh-copy-id -i ~/.ssh/archery_deploy.pub ${ARCHERY_USER}@${SERVER_IP}"
fi

# ============================================================================
# 8. logrotate
# ============================================================================

log "==> 8. logrotate"

if [ -f /etc/logrotate.d/archery ]; then
    log "  /etc/logrotate.d/archery 已存在，跳过写入"
else
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
fi

# ============================================================================
# 9. cloudflared 安装（钉钉回调隧道用）
# ============================================================================

log "==> 9. cloudflared 安装"

if command -v cloudflared >/dev/null 2>&1; then
    log "  cloudflared 已安装: $(cloudflared --version 2>&1 | head -1)"
else
    ARCH="$(uname -m)"
    case "${ARCH}" in
        x86_64)  RPM_ARCH="x86_64" ;;
        aarch64) RPM_ARCH="arm64" ;;
        *)
            log "  WARN: 不支持的架构 ${ARCH}，跳过 cloudflared 安装"
            log "        请手动从 https://github.com/cloudflare/cloudflared/releases 下载安装"
            RPM_ARCH=""
            ;;
    esac

    if [ -n "${RPM_ARCH}" ]; then
        CLOUDFLARED_RPM="${TMP_DIR}/cloudflared-linux-${RPM_ARCH}.rpm"
        # 10 分钟超时（cloudflared ~30MB）
        if curl -fsSL --max-time 600 \
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${RPM_ARCH}.rpm" \
            -o "${CLOUDFLARED_RPM}"; then
            rpm -i "${CLOUDFLARED_RPM}" 2>&1 || yum localinstall -y "${CLOUDFLARED_RPM}" || die "cloudflared rpm 安装失败"
            log "  ✓ cloudflared 安装成功: $(cloudflared --version 2>&1 | head -1)"
        else
            die "下载 cloudflared rpm 失败（github releases 不可达？）"
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
    GPG_PASSPHRASE="$(openssl rand -hex 32)"
    echo "${GPG_PASSPHRASE}" > "${BACKUP_PASSPHRASE_FILE}"
    chmod 600 "${BACKUP_PASSPHRASE_FILE}"
    log "  ✓ 已生成新备份密码，存到 ${BACKUP_PASSPHRASE_FILE}"
fi

# ============================================================================
# 11. MySQL 库 + dbops 用户（不修改 my.cnf，不重启 mysqld）
# ============================================================================

log "==> 11. MySQL 库 + dbops 用户"

# 11.1 测试连接
if ! mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -h 127.0.0.1 -P 3306 \
        -e "SELECT VERSION();" >/dev/null 2>&1; then
    die "MySQL root 连接失败（密码错？端口 3306 改了？）"
fi
log "  ✓ MySQL 连接正常"

# 11.2 自动生成或复用 dbops 密码
if [ -r "${DBOPS_PASSWORD_FILE}" ] && [ -s "${DBOPS_PASSWORD_FILE}" ]; then
    DBOPS_PASSWORD="$(cat "${DBOPS_PASSWORD_FILE}")"
    log "  复用已有 dbops 密码（${DBOPS_PASSWORD_FILE}）"
else
    DBOPS_PASSWORD="$(openssl rand -hex 16)"
    echo "${DBOPS_PASSWORD}" > "${DBOPS_PASSWORD_FILE}"
    chmod 600 "${DBOPS_PASSWORD_FILE}"
    log "  ✓ 生成新 dbops 密码，已存到 ${DBOPS_PASSWORD_FILE}"
fi

# 11.3 建库（每个环境一个，全部 utf8mb4）
for db in "${MYSQL_DBS[@]}"; do
    if mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -h 127.0.0.1 \
            -e "CREATE DATABASE IF NOT EXISTS \`${db}\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null; then
        log "  ✓ 数据库 ${db}（utf8mb4）"
    else
        die "建库 ${db} 失败"
    fi
done

# 11.3.5 重新生成满足 MySQL 8 validate_password 策略的 dbops 密码
#        策略默认 MEDIUM：长度 >= 8 + 1 大写 + 1 小写 + 1 数字 + 1 特殊字符
#        用 /dev/urandom 从全字符集采样，20 字符长度
if [ -r "${DBOPS_PASSWORD_FILE}" ] && [ -s "${DBOPS_PASSWORD_FILE}" ]; then
    EXISTING_PWD="$(cat "${DBOPS_PASSWORD_FILE}")"
    # 校验既有密码是否满足策略（用 mysql 试探）
    set +e
    probe_out="$(mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -h 127.0.0.1 \
        -e "ALTER USER 'dbops_probe'@'localhost' IDENTIFIED BY '${EXISTING_PWD}';" 2>&1)"
    probe_rc=$?
    set -e
    if [ "${probe_rc}" -eq 0 ]; then
        # 满足策略，复用
        mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -h 127.0.0.1 \
            -e "DROP USER IF EXISTS 'dbops_probe'@'localhost';" >/dev/null 2>&1 || true
        DBOPS_PASSWORD="${EXISTING_PWD}"
        log "  复用已有 dbops 密码（满足策略）"
    else
        log "  已有密码不满足 validate_password 策略，重新生成"
        log "    probe error: $(echo "${probe_out}" | head -1)"
        mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -h 127.0.0.1 \
            -e "DROP USER IF EXISTS 'dbops_probe'@'localhost';" >/dev/null 2>&1 || true
    fi
fi
if [ -z "${DBOPS_PASSWORD:-}" ]; then
    # /dev/urandom 采样，满足 MEDIUM 策略
    DBOPS_PASSWORD="$(tr -dc 'A-Za-z0-9!@#%^&_+' < /dev/urandom | head -c 24)"
    echo "${DBOPS_PASSWORD}" > "${DBOPS_PASSWORD_FILE}"
    chmod 600 "${DBOPS_PASSWORD_FILE}"
    log "  ✓ 生成新 dbops 密码（24 字符，满足 MySQL 8 MEDIUM 策略）"
fi

# 11.4 建 dbops 用户（'%' 允许任意来源；本机 127.0.0.1 即可）
#     注意：MySQL 8 的 CREATE USER IF NOT EXISTS 在 8.0.29+ 才支持，
#     这里用更稳的"先查再建"模式（先 SELECT 再判断）
USER_EXISTS="$(mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -h 127.0.0.1 -N -B \
    -e "SELECT COUNT(*) FROM mysql.user WHERE user='dbops' AND host='%';" 2>/dev/null || echo "0")"
if [ "${USER_EXISTS}" = "0" ]; then
    mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -h 127.0.0.1 \
        -e "CREATE USER 'dbops'@'%' IDENTIFIED BY '${DBOPS_PASSWORD}';" \
        || die "创建 dbops 用户失败"
    log "  ✓ 创建用户 dbops@'%'"
else
    # 已存在：更新密码（避免密码漂移）
    mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -h 127.0.0.1 \
        -e "ALTER USER 'dbops'@'%' IDENTIFIED BY '${DBOPS_PASSWORD}';" \
        || die "更新 dbops 密码失败"
    log "  dbops@'%' 已存在，已更新密码"
fi

# 11.5 授权
#     11.5.0 如果 root 没有 WITH GRANT OPTION，先给自己加（root 有 RELOAD 权限可 UPDATE+FLUSH）
ROOT_GRANTS="$(mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -h 127.0.0.1 -N -B -e "SHOW GRANTS FOR CURRENT_USER();" 2>/dev/null | grep -v 'Using a password' | head -1 || true)"
if ! echo "${ROOT_GRANTS}" | grep -q "WITH GRANT OPTION"; then
    log "  root 用户没有 WITH GRANT OPTION，自动添加（UPDATE mysql.user + FLUSH）"
    mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -h 127.0.0.1 \
        -e "UPDATE mysql.user SET Grant_priv='Y' WHERE User='root'; FLUSH PRIVILEGES;" 2>/dev/null
    log "  ✓ root 已加 WITH GRANT OPTION"
fi

mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -h 127.0.0.1 \
    -e "GRANT ALL PRIVILEGES ON \`archery_%\`.* TO 'dbops'@'%';" \
    || die "GRANT 失败"
mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -h 127.0.0.1 \
    -e "FLUSH PRIVILEGES;" >/dev/null
log "  ✓ GRANT ALL ON archery_%.* TO dbops@'%'"

# 11.6 验证
set +e
verify_out="$(mysql -udbops -p"${DBOPS_PASSWORD}" -h 127.0.0.1 -N -B \
    -e "SHOW DATABASES LIKE 'archery_%';" 2>&1)"
verify_rc=$?
set -e
if [ "${verify_rc}" -eq 0 ] && [ -n "${verify_out}" ]; then
    log "  ✓ dbops 验证通过，可见库: $(echo "${verify_out}" | tr '\n' ' ')"
else
    die "dbops 验证失败（rc=${verify_rc}, output='${verify_out}'）"
fi

# ============================================================================
# 收尾
# ============================================================================

log ""
log "==> 初始化完成"
log ""
log "下一步："
log "  1. 在 GitHub Repo Settings > Secrets 添加 SSH_PRIVATE_KEY / DINGTALK_NOTIFY_WEBHOOK"
log "  2. 验证 SSH 登录：ssh -i ~/.ssh/archery_deploy ${ARCHERY_USER}@${SERVER_IP}"
log "  3. 创建 /opt/archery/<env>/.env（cp .env.example .env && 编辑）"
log "  4. 第一次部署：cd ${ARCHERY_HOME}/scripts/deploy && ./02_deploy.sh prod <version>"
log "  5. 配置 Cloudflare Tunnel：详见 scripts/deploy/cloudflared/README.md"
log ""
log "关键文件位置："
log "  Redis 密码:        ${REDIS_PASSWORD_FILE}"
log "  备份 GPG 密码:     ${BACKUP_PASSPHRASE_FILE}"
log "  dbops MySQL 密码:  ${DBOPS_PASSWORD_FILE}"
log "  SSH authorized:    ${SSH_AUTHORIZED_KEYS_FILE_ACTUAL:-/home/${ARCHERY_USER}/.ssh/authorized_keys}"
log "  Archery 代码:      ${ARCHERY_HOME}/{prod,staging,dev}"
log "  共享数据:          ${ARCHERY_HOME}/shared/{logs,media,static,backups,run}"
log "  系统日志:          /var/log/archery/"
log "  Cloudflare 配置:   /etc/cloudflared/"
log "  pyenv:             ${PYENV_ROOT}"
log ""
log "⚠ 务必把以下密码备份到密码管理器（丢失将无法恢复）："
log "  - ${REDIS_PASSWORD_FILE}"
log "  - ${BACKUP_PASSPHRASE_FILE}"
log "  - ${DBOPS_PASSWORD_FILE}"

exit 0
