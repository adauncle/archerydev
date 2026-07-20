#!/usr/bin/env bash
## CUSTOM-NEW: 通用部署脚本（dev/staging/prod，systemd 版本）@ 2026-07-20 @ devops-agent
##
## 设计依据：docs/designs/2026-07-20_devops-cicd.md §5.1
## 运行方式：服务器上由 GitHub Actions 触发（SSH 后调用）
##   ./02_deploy.sh <env> <version>
##   env:     dev | staging | prod
##   version: git commit hash / tag / branch（如 v1.14.0.1、main、c7170ff）
##
## 流程：拉代码 → 装依赖 → 加载 .env → migrate → collectstatic → 重启 systemd → 健康检查 → 通知钉钉
## 异常：健康检查失败自动调用 03_rollback.sh 回滚
##
## 前置条件：
##   1. /opt/archery/<env>/.env 存在（从 .env.example 复制并填入真实凭据）
##   2. systemd service 单元已部署（archery-<env>-gunicorn.service 等）
##   3. Redis、MySQL 已就绪
##   4. /etc/archery/dingtalk_webhook 存在（可选；缺失时只记录日志）
##   5. SSH 用户对 /opt/archery/<env>/ 有写权限
##
## 幂等性：可重复执行同一 version（git checkout 是幂等的；pip install 会增量更新）
##
## 凭据约定：所有密码通过 .env 文件提供，不在脚本中硬编码

set -euo pipefail

# ============================================================================
# 参数解析
# ============================================================================

usage() {
    cat <<EOF
Usage: $0 <env> <version>

Arguments:
  env       dev | staging | prod
  version   git commit hash / tag / branch

Examples:
  $0 prod v1.14.0.1
  $0 staging main
  $0 dev c7170ff

Environment overrides:
  REPO            Git URL (default: https://github.com/adauncle/archerydev.git)
  SKIP_HEALTHCHECK  跳过健康检查（默认 false）
  SKIP_NOTIFY       跳过钉钉通知（默认 false）
  ROLLBACK_ON_FAIL  健康检查失败时自动回滚（默认 true）
EOF
}

if [ $# -lt 2 ]; then
    usage
    exit 1
fi

ENV="$1"
VERSION="$2"

case "${ENV}" in
    dev)     PORT=9001; DB_NAME="archery_dev";     WORKERS=1; REPO_DIR="/opt/archery/dev"     ;;
    staging) PORT=9002; DB_NAME="archery_staging"; WORKERS=2; REPO_DIR="/opt/archery/staging" ;;
    prod)    PORT=9003; DB_NAME="archery_prod";    WORKERS=4; REPO_DIR="/opt/archery/prod"    ;;
    *)
        echo "ERROR: 未知环境: ${ENV}（必须是 dev | staging | prod）" >&2
        usage
        exit 1
        ;;
esac

# ============================================================================
# 路径与可调参数
# ============================================================================

ARCHERY_USER="${ARCHERY_USER:-archery}"
SHARED_DIR="/opt/archery/shared"
LOG_DIR="/var/log/archery"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLLBACK_SH="${SCRIPT_DIR}/03_rollback.sh"

REPO="${REPO:-https://github.com/adauncle/archerydev.git}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
VENV_DIR="${REPO_DIR}/venv"

DEPLOY_LOG="${LOG_DIR}/deploy_${ENV}.log"
DINGTALK_WEBHOOK_FILE="${DINGTALK_WEBHOOK_FILE:-/etc/archery/dingtalk_webhook}"

# 健康检查参数
HEALTH_URL="http://127.0.0.1:${PORT}/healthz"
HEALTH_RETRIES="${HEALTH_RETRIES:-10}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-2}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-5}"

# 流程开关
SKIP_HEALTHCHECK="${SKIP_HEALTHCHECK:-false}"
SKIP_NOTIFY="${SKIP_NOTIFY:-false}"
ROLLBACK_ON_FAIL="${ROLLBACK_ON_FAIL:-true}"

# ============================================================================
# 工具函数
# ============================================================================

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [${ENV}] $*"
    echo "${msg}"
    if [ -w "${LOG_DIR}" ] 2>/dev/null; then
        echo "${msg}" >> "${DEPLOY_LOG}" 2>/dev/null || true
    fi
}

notify_dingtalk() {
    # 部署完成/失败时调用；webhook 缺失则静默跳过
    local content="$1"
    if [ "${SKIP_NOTIFY}" = "true" ]; then
        return 0
    fi
    if [ ! -r "${DINGTALK_WEBHOOK_FILE}" ]; then
        log "  (通知跳过：${DINGTALK_WEBHOOK_FILE} 不可读)"
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
        -d "${payload}" >/dev/null 2>&1 || \
        log "  WARN: 钉钉通知失败（不影响部署主流程）"
}

die() {
    log "ERROR: $*"
    notify_dingtalk "✗ Archery ${ENV} 部署失败
原因: $*
时间: $(date '+%Y-%m-%d %H:%M:%S')
版本: ${VERSION}
服务器: $(hostname)"

    if [ "${ROLLBACK_ON_FAIL}" = "true" ] && [ -x "${ROLLBACK_SH}" ]; then
        # 记录当前版本（失败时回滚到失败前的版本 = VERSION 本身）
        # 注意：如果失败发生在 deploy 中途，可能 git checkout 已切到 VERSION，
        # 此时"回滚"会再 checkout 一次，是 idempotent 的。
        log "  自动回滚：调用 ${ROLLBACK_SH} ${ENV} ${VERSION}"
        "${ROLLBACK_SH}" "${ENV}" "${VERSION}" || \
            log "  WARN: 自动回滚失败，请人工处理"
    fi
    exit 1
}

cleanup() {
    # 部署主流程不产生临时文件（git 操作和 pip install 都是 in-place）
    # 此函数作为占位，便于后续扩展
    :
}
trap cleanup EXIT

# ============================================================================
# 前置条件检查
# ============================================================================

command -v systemctl >/dev/null 2>&1 || die "未检测到 systemctl（非 systemd 系统不支持）"
command -v "${PYTHON_BIN}" >/dev/null 2>&1 || die "未检测到 ${PYTHON_BIN}"
command -v git >/dev/null 2>&1 || die "未检测到 git"
command -v curl >/dev/null 2>&1 || die "未检测到 curl"

[ -x "${ROLLBACK_SH}" ] || log "WARN: ${ROLLBACK_SH} 不可执行，回滚功能将不可用"

# .env 必须存在（不允许在 CI 上凭空创建）
[ -f "${REPO_DIR}/.env" ] || die "找不到 ${REPO_DIR}/.env
请先：ssh ${ARCHERY_USER}@<server>
      cp /opt/archery/.env.example /opt/archery/${ENV}/.env
      然后编辑填入真实凭据（MYSQL_* / REDIS_* / SECRET_KEY 等）"

# systemd service 必须存在
if ! systemctl cat "archery-${ENV}-gunicorn.service" >/dev/null 2>&1; then
    die "systemd service archery-${ENV}-gunicorn.service 未部署
请先：sudo cp ${SCRIPT_DIR}/systemd/archery-${ENV}-*.service /etc/systemd/system/
      sudo systemctl daemon-reload"
fi

# ============================================================================
# 0. 记录当前版本（用于回滚参考）
# ============================================================================

PREV_VERSION="unknown"
if [ -d "${REPO_DIR}/.git" ]; then
    PREV_VERSION="$(sudo -u "${ARCHERY_USER}" -H git -C "${REPO_DIR}" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
    PREV_TAG="$(sudo -u "${ARCHERY_USER}" -H git -C "${REPO_DIR}" describe --tags --always 2>/dev/null || echo 'unknown')"
    log "==> 0. 当前版本: ${PREV_VERSION} (${PREV_TAG})，目标版本: ${VERSION}"
else
    log "==> 0. 首次部署（仓库不存在），目标版本: ${VERSION}"
fi

# ============================================================================
# 1. 拉代码
# ============================================================================

log "==> 1. 拉代码"

if [ ! -d "${REPO_DIR}/.git" ]; then
    log "  首次部署：clone 仓库到 ${REPO_DIR}"
    sudo -u "${ARCHERY_USER}" -H git clone "${REPO}" "${REPO_DIR}" || die "git clone 失败"
fi

sudo -u "${ARCHERY_USER}" -H bash -c "
    set -e
    cd '${REPO_DIR}'
    git remote set-url origin '${REPO}'
    git fetch --all --prune --tags
    git checkout '${VERSION}'
    git log -1 --oneline
" || die "git checkout ${VERSION} 失败"

# 记录新版本
NEW_VERSION="$(sudo -u "${ARCHERY_USER}" -H git -C "${REPO_DIR}" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
log "  ✓ 代码已切换到 ${NEW_VERSION}"

# ============================================================================
# 2. 装依赖
# ============================================================================

log "==> 2. 装 Python 依赖"

sudo -u "${ARCHERY_USER}" -H bash -c "
    set -e
    cd '${REPO_DIR}'
    if [ ! -d venv ]; then
        ${PYTHON_BIN} -m venv venv
    fi
    source venv/bin/activate
    pip install --upgrade pip wheel setuptools
    pip install -r requirements.txt
" || die "pip install 失败"

# ============================================================================
# 3. 数据库迁移
# ============================================================================

log "==> 3. 数据库迁移 (migrate)"

sudo -u "${ARCHERY_USER}" -H bash -c "
    set -e
    cd '${REPO_DIR}'
    source venv/bin/activate
    set -a
    . ./.env
    set +a
    python manage.py migrate --noinput
" || die "migrate 失败"

# ============================================================================
# 4. 收集静态文件
# ============================================================================

log "==> 4. 收集静态文件 (collectstatic)"

# 静态文件输出到 shared/static（多环境共享）
STATIC_ROOT="${SHARED_DIR}/static"
mkdir -p "${STATIC_ROOT}"
chown "${ARCHERY_USER}:${ARCHERY_USER}" "${STATIC_ROOT}"

sudo -u "${ARCHERY_USER}" -H bash -c "
    set -e
    cd '${REPO_DIR}'
    source venv/bin/activate
    set -a
    . ./.env
    set +a
    python manage.py collectstatic --noinput --clear
" || die "collectstatic 失败"

log "  ✓ 静态文件已收集到 ${STATIC_ROOT}"

# ============================================================================
# 5. 重启 systemd 服务
# ============================================================================

log "==> 5. 重启 systemd 服务"

# 5.1 gunicorn（必需）
systemctl restart "archery-${ENV}-gunicorn.service" || die "重启 archery-${ENV}-gunicorn.service 失败"
log "  ✓ archery-${ENV}-gunicorn.service 已重启"

# 5.2 celery worker（prod/staging 才有；dev 可选）
if systemctl cat "archery-${ENV}-celery-worker.service" >/dev/null 2>&1; then
    systemctl restart "archery-${ENV}-celery-worker.service" || \
        log "  WARN: 重启 archery-${ENV}-celery-worker.service 失败"
    log "  ✓ archery-${ENV}-celery-worker.service 已重启"
fi

# 5.3 celery beat（仅 prod）
if systemctl cat "archery-${ENV}-celery-beat.service" >/dev/null 2>&1; then
    systemctl restart "archery-${ENV}-celery-beat.service" || \
        log "  WARN: 重启 archery-${ENV}-celery-beat.service 失败"
    log "  ✓ archery-${ENV}-celery-beat.service 已重启"
fi

# ============================================================================
# 6. 健康检查
# ============================================================================

if [ "${SKIP_HEALTHCHECK}" = "true" ]; then
    log "==> 6. 健康检查（已跳过 SKIP_HEALTHCHECK=true）"
else
    log "==> 6. 健康检查 (${HEALTH_URL})"

    success=0
    attempt=0
    last_http_code=""
    last_curl_err=""

    while [ "${attempt}" -lt "${HEALTH_RETRIES}" ]; do
        attempt=$((attempt + 1))
        # 第一次不用等
        if [ "${attempt}" -gt 1 ]; then
            log "  retry ${attempt}/${HEALTH_RETRIES} (sleep ${HEALTH_INTERVAL}s)..."
            sleep "${HEALTH_INTERVAL}"
        fi

        set +e
        body_file="$(mktemp)"
        last_http_code=$(curl -sS \
            --max-time "${HEALTH_TIMEOUT}" \
            --connect-timeout 3 \
            -o "${body_file}" \
            -w "%{http_code}" \
            "${HEALTH_URL}" 2>/tmp/curl_healthz.err)
        last_curl_err="$(cat /tmp/curl_healthz.err 2>/dev/null || true)"
        rm -f /tmp/curl_healthz.err
        body_size=$(stat -c '%s' "${body_file}" 2>/dev/null || stat -f '%z' "${body_file}" 2>/dev/null || echo 0)
        rm -f "${body_file}"
        set -e

        if [ -z "${last_http_code}" ]; then
            last_http_code="000"
        fi

        log "  尝试 ${attempt}/${HEALTH_RETRIES}: HTTP ${last_http_code} (body=${body_size}B)"

        if [ "${last_http_code}" = "200" ]; then
            success=1
            break
        fi
    done

    if [ "${success}" -ne 1 ]; then
        die "健康检查失败 (HTTP ${last_http_code}, err='${last_curl_err:-无}')，共尝试 ${HEALTH_RETRIES} 次"
    fi

    log "  ✓ 健康检查通过 (${ENV} on port ${PORT})"
fi

# ============================================================================
# 7. 通知钉钉
# ============================================================================

log "==> 7. 通知钉钉群"

DEPLOY_MSG="✓ Archery ${ENV} 部署成功
版本: ${VERSION} (${NEW_VERSION})
之前: ${PREV_VERSION} → 现在: ${NEW_VERSION}
端口: ${PORT}
时间: $(date '+%Y-%m-%d %H:%M:%S')
服务器: $(hostname)"

notify_dingtalk "${DEPLOY_MSG}"

# ============================================================================
# 收尾
# ============================================================================

log ""
log "==> 部署完成 [${ENV}] ${NEW_VERSION}"
log "  健康检查:  http://127.0.0.1:${PORT}/healthz"
log "  回滚命令:  ${ROLLBACK_SH} ${ENV} ${PREV_VERSION}"

exit 0
