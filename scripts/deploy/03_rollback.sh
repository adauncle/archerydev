#!/usr/bin/env bash
## CUSTOM-NEW: 一键回滚脚本（切到指定 version + 重启服务 + 健康检查）@ 2026-07-20 @ devops-agent
##
## 设计依据：docs/designs/2026-07-20_devops-cicd.md §8.2
## 运行方式：服务器上手动执行或由 02_deploy.sh 在健康检查失败时自动调用
##   ./03_rollback.sh <env> <prev_version>
##   env:         dev | staging | prod
##   prev_version: 之前稳定的 git commit / tag / branch
##
## 流程：git checkout <prev_version> → systemctl restart → 健康检查 → 通知钉钉
##
## ⚠ 注意：
##   - 本脚本只回滚代码，不回滚数据库
##   - 如果新版本有破坏性的数据库迁移，回滚后服务可能起不来，需要手动处理
##   - 建议每次部署前由 04_backup.sh 跑一次 MySQL dump（生产环境）
##
## 前置条件：
##   1. 02_deploy.sh 至少成功跑过一次（/opt/archery/<env>/ 已有 .git）
##   2. systemd service 单元已部署
##   3. /etc/archery/dingtalk_webhook 存在（可选）
##
## 幂等性：可重复执行同一版本（git checkout 幂等）

set -euo pipefail

# ============================================================================
# 参数解析
# ============================================================================

usage() {
    cat <<EOF
Usage: $0 <env> <prev_version>

Arguments:
  env         dev | staging | prod
  prev_version 之前稳定的 git commit / tag / branch

Examples:
  $0 prod v1.14.0
  $0 staging c7170ff
  $0 dev main

Environment overrides:
  SKIP_HEALTHCHECK  跳过健康检查（默认 false）
  SKIP_NOTIFY       跳过钉钉通知（默认 false）
EOF
}

if [ $# -lt 2 ]; then
    usage
    exit 1
fi

ENV="$1"
PREV_VERSION="$2"

case "${ENV}" in
    dev)     PORT=9001; REPO_DIR="/opt/archery/dev"     ;;
    staging) PORT=9002; REPO_DIR="/opt/archery/staging" ;;
    prod)    PORT=9003; REPO_DIR="/opt/archery/prod"    ;;
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
LOG_DIR="/var/log/archery"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DEPLOY_LOG="${LOG_DIR}/deploy_${ENV}.log"
DINGTALK_WEBHOOK_FILE="${DINGTALK_WEBHOOK_FILE:-/etc/archery/dingtalk_webhook}"

HEALTH_URL="http://127.0.0.1:${PORT}/healthz"
HEALTH_RETRIES="${HEALTH_RETRIES:-10}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-2}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-5}"

SKIP_HEALTHCHECK="${SKIP_HEALTHCHECK:-false}"
SKIP_NOTIFY="${SKIP_NOTIFY:-false}"

# ============================================================================
# 工具函数
# ============================================================================

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [ROLLBACK ${ENV}] $*"
    echo "${msg}"
    if [ -w "${LOG_DIR}" ] 2>/dev/null; then
        echo "${msg}" >> "${DEPLOY_LOG}" 2>/dev/null || true
    fi
}

notify_dingtalk() {
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
        log "  WARN: 钉钉通知失败（不影响回滚主流程）"
}

die() {
    log "ERROR: $*"
    notify_dingtalk "✗ Archery ${ENV} 回滚失败
原因: $*
目标版本: ${PREV_VERSION}
时间: $(date '+%Y-%m-%d %H:%M:%S')
服务器: $(hostname)"
    exit 1
}

# ============================================================================
# 前置条件检查
# ============================================================================

command -v systemctl >/dev/null 2>&1 || die "未检测到 systemctl"
command -v git >/dev/null 2>&1 || die "未检测到 git"
command -v curl >/dev/null 2>&1 || die "未检测到 curl"

[ -d "${REPO_DIR}/.git" ] || die "${REPO_DIR} 不是 git 仓库（请先成功跑一次 02_deploy.sh）"

# ============================================================================
# 0. 记录当前版本
# ============================================================================

CURRENT_VERSION="$(sudo -u "${ARCHERY_USER}" -H git -C "${REPO_DIR}" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
log "==> 0. 当前版本: ${CURRENT_VERSION}，目标回滚版本: ${PREV_VERSION}"

# ============================================================================
# 1. git checkout
# ============================================================================

log "==> 1. git checkout ${PREV_VERSION}"

sudo -u "${ARCHERY_USER}" -H bash -c "
    set -e
    cd '${REPO_DIR}'
    git fetch --all --prune --tags
    git checkout '${PREV_VERSION}'
    git log -1 --oneline
" || die "git checkout ${PREV_VERSION} 失败"

NEW_VERSION="$(sudo -u "${ARCHERY_USER}" -H git -C "${REPO_DIR}" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
log "  ✓ 代码已切到 ${NEW_VERSION}"

# ============================================================================
# 2. 装依赖（避免新版 venv 与旧代码不兼容）
# ============================================================================

log "==> 2. 装 Python 依赖（如有变化）"

# 不强制重装；只做 upgrade pip + 增量 install
# 如果回滚前后 requirements.txt 没变，pip install 几乎无副作用
sudo -u "${ARCHERY_USER}" -H bash -c "
    set -e
    cd '${REPO_DIR}'
    if [ ! -d venv ]; then
        ${PYTHON_BIN:-python3.11} -m venv venv
    fi
    source venv/bin/activate
    pip install --upgrade pip wheel setuptools
    pip install -r requirements.txt
" || die "pip install 失败（回滚后依赖安装失败）"

# 收集静态文件（如果旧版本 static 路径不同，需要重新 collect）
if [ -d "${REPO_DIR}/venv" ]; then
    log "==> 3. 重新 collectstatic"
    SHARED_STATIC_DIR="/opt/archery/shared/static"
    sudo -u "${ARCHERY_USER}" -H bash -c "
        set -e
        cd '${REPO_DIR}'
        source venv/bin/activate
        set -a
        . ./.env
        set +a
        python manage.py collectstatic --noinput
    " || log "  WARN: collectstatic 失败（不影响服务启动）"
fi

# ============================================================================
# 3. 重启 systemd 服务
# ============================================================================

log "==> 4. 重启 systemd 服务"

systemctl restart "archery-${ENV}-gunicorn.service" || die "重启 archery-${ENV}-gunicorn.service 失败"
log "  ✓ archery-${ENV}-gunicorn.service 已重启"

if systemctl cat "archery-${ENV}-celery-worker.service" >/dev/null 2>&1; then
    systemctl restart "archery-${ENV}-celery-worker.service" || \
        log "  WARN: 重启 archery-${ENV}-celery-worker.service 失败"
    log "  ✓ archery-${ENV}-celery-worker.service 已重启"
fi

if systemctl cat "archery-${ENV}-celery-beat.service" >/dev/null 2>&1; then
    systemctl restart "archery-${ENV}-celery-beat.service" || \
        log "  WARN: 重启 archery-${ENV}-celery-beat.service 失败"
    log "  ✓ archery-${ENV}-celery-beat.service 已重启"
fi

# ============================================================================
# 4. 健康检查
# ============================================================================

if [ "${SKIP_HEALTHCHECK}" = "true" ]; then
    log "==> 5. 健康检查（已跳过 SKIP_HEALTHCHECK=true）"
else
    log "==> 5. 健康检查 (${HEALTH_URL})"

    success=0
    attempt=0
    last_http_code=""

    while [ "${attempt}" -lt "${HEALTH_RETRIES}" ]; do
        attempt=$((attempt + 1))
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
        curl_err="$(cat /tmp/curl_healthz.err 2>/dev/null || true)"
        rm -f /tmp/curl_healthz.err
        body_size=$(stat -c '%s' "${body_file}" 2>/dev/null || stat -f '%z' "${body_file}" 2>/dev/null || echo 0)
        rm -f "${body_file}"
        set -e

        if [ -z "${last_http_code}" ]; then
            last_http_code="000"
        fi

        log "  尝试 ${attempt}/${HEALTH_RETRIES}: HTTP ${last_http_code}"

        if [ "${last_http_code}" = "200" ]; then
            success=1
            break
        fi
    done

    if [ "${success}" -ne 1 ]; then
        die "回滚后健康检查仍失败 (HTTP ${last_http_code})，请人工介入"
    fi

    log "  ✓ 健康检查通过 (${ENV} on port ${PORT})"
fi

# ============================================================================
# 5. 通知钉钉
# ============================================================================

log "==> 6. 通知钉钉群"

ROLLBACK_MSG="⏪ Archery ${ENV} 回滚完成
原版本: ${CURRENT_VERSION} → 回滚到: ${PREV_VERSION} (${NEW_VERSION})
端口:   ${PORT}
时间:   $(date '+%Y-%m-%d %H:%M:%S')
服务器: $(hostname)

请检查：
  1. 业务功能是否正常
  2. 数据库是否有不一致（新版本可能跑了迁移）"

notify_dingtalk "${ROLLBACK_MSG}"

# ============================================================================
# 收尾
# ============================================================================

log ""
log "==> 回滚完成 [${ENV}] ${NEW_VERSION}"
log "  健康检查:  http://127.0.0.1:${PORT}/healthz"
log "  重新部署:  ${SCRIPT_DIR}/02_deploy.sh ${ENV} <version>"

exit 0
