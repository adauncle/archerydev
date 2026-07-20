#!/usr/bin/env bash
## CUSTOM-NEW: 健康检查脚本（curl /healthz + 钉钉告警）@ 2026-07-20 @ devops-agent
##
## 设计依据：docs/designs/2026-07-20_devops-cicd.md §7.2
## 运行方式：每 5 分钟由 systemd timer 触发
##   - timer: scripts/deploy/systemd/archery-monitor.timer
##   - service: scripts/deploy/systemd/archery-monitor.service
##
## 前置条件：
##   1. /etc/archery/dingtalk_webhook 存在（可选；缺失时只记录日志）
##   2. curl 在 PATH
##   3. 目标服务监听 HEALTH_URL
##
## 退出码：
##   0  - 健康
##   1  - 健康检查失败（已发钉钉告警）
##   2  - 配置错误（如缺关键文件）
##
## 幂等性：纯只读检查，任意次运行无副作用

set -euo pipefail

# ============================================================================
# 可调参数（可通过环境变量覆盖）
# ============================================================================
HEALTH_URL="${HEALTH_URL:-http://172.20.2.134:9003/healthz}"
CURL_TIMEOUT="${CURL_TIMEOUT:-10}"
DINGTALK_WEBHOOK_FILE="${DINGTALK_WEBHOOK_FILE:-/etc/archery/dingtalk_webhook}"
LOG_FILE="${LOG_FILE:-/var/log/archery/monitor.log}"
TMP_DIR="${TMPDIR:-/tmp}"

# 重试次数（连续失败 N 次才告警，避免抖动）
RETRY_COUNT="${RETRY_COUNT:-2}"
RETRY_DELAY="${RETRY_DELAY:-2}"

# 告警节流：同一故障 KEY 在 ALERT_COOLDOWN 秒内只发一次
ALERT_COOLDOWN="${ALERT_COOLDOWN:-300}"
ALERT_STATE_DIR="${ALERT_STATE_DIR:-/var/tmp/archery-monitor}"

# 强制环境变量：DIAG_OUTPUT=true 输出详情到 stdout（调试用）
DIAG_OUTPUT="${DIAG_OUTPUT:-false}"

# ============================================================================
# 工具函数
# ============================================================================

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    if [ "${DIAG_OUTPUT}" = "true" ]; then
        echo "${msg}"
    fi
    if [ -w "$(dirname "${LOG_FILE}")" ] 2>/dev/null; then
        echo "${msg}" >> "${LOG_FILE}" 2>/dev/null || true
    fi
}

notify_dingtalk() {
    local content="$1"
    if [ ! -r "${DINGTALK_WEBHOOK_FILE}" ]; then
        log "WARN: 钉钉 webhook 文件不可读 (${DINGTALK_WEBHOOK_FILE})，跳过通知"
        return 0
    fi
    local webhook
    webhook="$(cat "${DINGTALK_WEBHOOK_FILE}" 2>/dev/null || true)"
    if [ -z "${webhook}" ]; then
        log "WARN: 钉钉 webhook 内容为空，跳过通知"
        return 0
    fi

    local payload
    if command -v jq >/dev/null 2>&1; then
        payload="$(jq -Rn --arg c "${content}" '{msgtype:"text",text:{content:$c}}')"
    else
        payload="$(python3 -c 'import json,sys;print(json.dumps({"msgtype":"text","text":{"content":sys.argv[1]}}))' "${content}")"
    fi

    if ! curl -fsS --max-time 5 \
        -X POST "${webhook}" \
        -H "Content-Type: application/json" \
        -d "${payload}" >/dev/null 2>&1; then
        log "WARN: 钉钉通知发送失败（不影响健康检查判定）"
    fi
}

# 简单的"故障指纹"用于告警节流
alert_key_for() {
    # 输入：HTTP code 或 error 类别
    echo "healthz_${1:-unknown}" | tr -c '[:alnum:]._-' '_'
}

# 检查是否在冷却期内（避免告警风暴）
should_alert() {
    local key="$1"
    mkdir -p "${ALERT_STATE_DIR}"
    local state_file="${ALERT_STATE_DIR}/${key}"
    if [ ! -f "${state_file}" ]; then
        date '+%s' > "${state_file}"
        return 0  # 首次告警
    fi
    local last
    last="$(cat "${state_file}" 2>/dev/null || echo 0)"
    local now
    now="$(date '+%s')"
    if [ $((now - last)) -ge "${ALERT_COOLDOWN}" ]; then
        date '+%s' > "${state_file}"
        return 0  # 冷却期满
    fi
    return 1  # 冷却中
}

cleanup() {
    rm -f "${HEALTHZ_BODY:-}" "${HEALTHZ_HEADERS:-}" 2>/dev/null || true
}
trap cleanup EXIT

# ============================================================================
# 前置检查
# ============================================================================

command -v curl >/dev/null 2>&1 || {
    log "ERROR: 缺少 curl 命令"
    exit 2
}

[ -n "${HEALTH_URL}" ] || {
    log "ERROR: HEALTH_URL 未设置"
    exit 2
}

# ============================================================================
# 健康检查主体（带重试）
# ============================================================================

HEALTHZ_BODY="${TMP_DIR}/archery_healthz.$$.body"
HEALTHZ_HEADERS="${TMP_DIR}/archery_healthz.$$.hdr"

http_code=""
curl_err=""
attempt=0
success=0

while [ "${attempt}" -lt "${RETRY_COUNT}" ] && [ "${success}" -eq 0 ]; do
    attempt=$((attempt + 1))
    if [ "${attempt}" -gt 1 ]; then
        log "  retry ${attempt}/${RETRY_COUNT} (sleep ${RETRY_DELAY}s)..."
        sleep "${RETRY_DELAY}"
    fi

    # -f: HTTP 错误时让 curl 返回非零（但 5xx 时我们想要 body，所以分开处理）
    # 用 -w 抓 http_code；--max-time 限制超时
    set +e
    http_code=$(curl -sS \
        --max-time "${CURL_TIMEOUT}" \
        --connect-timeout 5 \
        -o "${HEALTHZ_BODY}" \
        -D "${HEALTHZ_HEADERS}" \
        -w "%{http_code}" \
        "${HEALTH_URL}" 2>"${TMP_DIR}/archery_healthz.$$.err")
    curl_err="$(cat "${TMP_DIR}/archery_healthz.$$.err" 2>/dev/null || true)"
    rm -f "${TMP_DIR}/archery_healthz.$$.err"
    set -e

    if [ -z "${http_code}" ]; then
        http_code="000"
    fi

    log "尝试 ${attempt}/${RETRY_COUNT}: HTTP ${http_code} ${HEALTH_URL}"

    if [ "${http_code}" = "200" ]; then
        success=1
        break
    fi
done

# ============================================================================
# 结果处理
# ============================================================================

if [ "${success}" -eq 1 ]; then
    body_size=$(stat -c '%s' "${HEALTHZ_BODY}" 2>/dev/null || stat -f '%z' "${HEALTHZ_BODY}" 2>/dev/null || echo 0)
    log "OK  Archery 健康检查通过 (HTTP 200, body=${body_size}B)"
    exit 0
fi

# 失败：确定指纹
if [ -n "${curl_err}" ]; then
    # 提取 curl 错误类别（取前 32 字符）
    err_kind=$(echo "${curl_err}" | head -c 32 | tr -c '[:alnum:]._-' '_')
    fingerprint="curl_${err_kind}"
else
    fingerprint="http_${http_code}"
fi

log "FAIL Archery 健康检查失败 (HTTP ${http_code}, err='${curl_err:-无}')"

# 告警节流
if should_alert "$(alert_key_for "${fingerprint}")"; then
    msg="🚨 Archery 健康检查失败
URL:    ${HEALTH_URL}
HTTP:   ${http_code}
错误:   ${curl_err:-响应非 200}
时间:   $(date '+%Y-%m-%d %H:%M:%S')
服务器: $(hostname)"

    notify_dingtalk "${msg}"
    log "  → 已发送钉钉告警"
else
    log "  → 告警在冷却期内，跳过发送"
fi

exit 1
