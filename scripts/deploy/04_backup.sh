#!/usr/bin/env bash
## CUSTOM-NEW: 每日备份脚本（MySQL dump + GPG 加密 + media 打包 + 30 天保留）@ 2026-07-20 @ devops-agent
##
## 设计依据：docs/designs/2026-07-20_devops-cicd.md §7.3
## 运行方式：
##   - 推荐：systemd timer（见 scripts/deploy/systemd/archery-backup.timer + .service）
##   - 备选：/etc/cron.d/archery-backup
##   - 手动：  ./04_backup.sh
##
## 前置条件：
##   1. /etc/archery/backup_passphrase 存在（GPG 加密密码，由 01_init_server.sh 生成）
##   2. /opt/archery/prod/.env 存在（提供 MYSQL_* 凭据；如不读 .env，可通过 BACKUP_MYSQL_* 显式传入）
##   3. mysqldump / gpg / tar 在 PATH
##   4. /var/log/archery/ 目录存在且可写
##
## 幂等性：可重复运行（覆盖同名文件、按时间戳区分、清理逻辑只看 mtime）
##
## 凭据约定：所有密码通过环境变量或 .env 文件提供，不在本脚本硬编码

set -euo pipefail

# ============================================================================
# 路径与可调参数（可通过环境变量覆盖）
# ============================================================================
BACKUP_DIR="${BACKUP_DIR:-/opt/archery/shared/backups}"
MEDIA_DIR="${MEDIA_DIR:-/opt/archery/shared/media}"
LOG_FILE="${LOG_FILE:-/var/log/archery/backup.log}"
ENV_FILE="${ENV_FILE:-/opt/archery/prod/.env}"
BACKUP_PASSPHRASE_FILE="${BACKUP_PASSPHRASE_FILE:-/etc/archery/backup_passphrase}"

KEEP_DAYS="${KEEP_DAYS:-30}"
# 三个数据库名（与 v0.9 §2 决策一致）
BACKUP_DATABASES="${BACKUP_DATABASES:-archery_prod archery_staging archery_dev}"

# 钉钉通知 webhook（可选，备份失败时告警）
DINGTALK_WEBHOOK_FILE="${DINGTALK_WEBHOOK_FILE:-/etc/archery/dingtalk_webhook}"

# 临时目录（脚本退出时清理）
TMP_DIR="${TMPDIR:-/tmp}"

# ============================================================================
# 工具函数
# ============================================================================

log() {
    # 同时输出到 stdout 和 LOG_FILE
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "${msg}"
    if [ -w "$(dirname "${LOG_FILE}")" ] 2>/dev/null; then
        echo "${msg}" >> "${LOG_FILE}" 2>/dev/null || true
    fi
}

notify_dingtalk() {
    # 备份失败时调用；webhook 缺失则静默跳过
    local content="$1"
    if [ -r "${DINGTALK_WEBHOOK_FILE}" ]; then
        local webhook
        webhook="$(cat "${DINGTALK_WEBHOOK_FILE}")"
        if [ -n "${webhook}" ]; then
            # 使用 jq 安全转义；如无 jq 则用 python
            local payload
            if command -v jq >/dev/null 2>&1; then
                payload="$(jq -Rn --arg c "${content}" '{msgtype:"text",text:{content:$c}}')"
            else
                payload="$(python3 -c 'import json,sys;print(json.dumps({"msgtype":"text","text":{"content":sys.argv[1]}}))' "${content}")"
            fi
            curl -fsS --max-time 10 \
                -X POST "${webhook}" \
                -H "Content-Type: application/json" \
                -d "${payload}" >/dev/null 2>&1 || \
                log "  WARN: 钉钉通知失败（不影响备份主流程）"
        fi
    fi
}

cleanup() {
    # 清理临时文件
    if [ -n "${SQL_TMP:-}" ] && [ -f "${SQL_TMP}" ]; then
        rm -f "${SQL_TMP}"
    fi
}
trap cleanup EXIT

die() {
    log "ERROR: $*"
    notify_dingtalk "🚨 Archery 备份失败\n原因: $*\n时间: $(date '+%Y-%m-%d %H:%M:%S')"
    exit 1
}

# ============================================================================
# 前置条件检查
# ============================================================================

[ "$(id -u)" -eq 0 ] || die "请用 root 运行（mysqldump 需要读取 /etc/archery/）"

[ -r "${BACKUP_PASSPHRASE_FILE}" ] || die "找不到 GPG 密码: ${BACKUP_PASSPHRASE_FILE}"
[ -r "${ENV_FILE}" ] || die "找不到 .env: ${ENV_FILE}"

for cmd in mysqldump gpg tar find; do
    command -v "${cmd}" >/dev/null 2>&1 || die "缺少命令: ${cmd}"
done

# ============================================================================
# 1. 加载凭据（.env 是 source 模式，不在 shell 历史中泄露）
# ============================================================================

log "==> 加载 .env 配置"
# shellcheck disable=SC1090
set -a
. "${ENV_FILE}"
set +a

: "${MYSQL_HOST:?MYSQL_HOST 未在 .env 中设置}"
: "${MYSQL_PORT:?MYSQL_PORT 未在 .env 中设置}"
: "${MYSQL_USER:?MYSQL_USER 未在 .env 中设置}"
: "${MYSQL_PASSWORD:?MYSQL_PASSWORD 未在 .env 中设置}"

# 允许通过环境变量覆盖
MYSQL_HOST="${BACKUP_MYSQL_HOST:-${MYSQL_HOST}}"
MYSQL_PORT="${BACKUP_MYSQL_PORT:-${MYSQL_PORT}}"
MYSQL_USER="${BACKUP_MYSQL_USER:-${MYSQL_USER}}"
MYSQL_PASSWORD="${BACKUP_MYSQL_PASSWORD:-${MYSQL_PASSWORD}}"

# ============================================================================
# 2. 准备目录
# ============================================================================

DATE="$(date '+%Y%m%d_%H%M%S')"
mkdir -p "${BACKUP_DIR}" || die "创建备份目录失败: ${BACKUP_DIR}"

SQL_TMP="${TMP_DIR}/archery_mysql_${DATE}.sql"
GPG_FILE="${BACKUP_DIR}/mysql_${DATE}.sql.gpg"
MEDIA_FILE="${BACKUP_DIR}/media_${DATE}.tar.gz"
MANIFEST_FILE="${BACKUP_DIR}/backup_${DATE}.manifest"

# ============================================================================
# 3. MySQL dump
# ============================================================================

log "==> 备份 MySQL 数据库: ${BACKUP_DATABASES}"

# 使用 --single-transaction 保证一致性；--routines + --triggers 包含存储过程/触发器
# 注意：mysqldump -p"${PASSWORD}" 不要有空格；多库用 --databases 形式
# shellcheck disable=SC2086
mysqldump \
    --host="${MYSQL_HOST}" \
    --port="${MYSQL_PORT}" \
    --user="${MYSQL_USER}" \
    --password="${MYSQL_PASSWORD}" \
    --single-transaction \
    --routines \
    --triggers \
    --events \
    --quick \
    --hex-blob \
    --default-character-set=utf8mb4 \
    --databases ${BACKUP_DATABASES} \
    > "${SQL_TMP}" 2>/tmp/mysqldump.err || {
        err="$(cat /tmp/mysqldump.err 2>/dev/null || echo '未知错误')"
        rm -f /tmp/mysqldump.err
        die "mysqldump 失败: ${err}"
    }
rm -f /tmp/mysqldump.err

local_size=$(stat -c '%s' "${SQL_TMP}" 2>/dev/null || stat -f '%z' "${SQL_TMP}" 2>/dev/null || echo 0)
[ "${local_size}" -gt 1024 ] || die "MySQL dump 文件异常小 (${local_size} bytes)，疑似空备份"

log "  ✓ SQL dump 完成: ${local_size} bytes"

# ============================================================================
# 4. GPG 对称加密
# ============================================================================

log "==> GPG 加密"

GPG_PASSPHRASE="$(cat "${BACKUP_PASSPHRASE_FILE}")"
[ -n "${GPG_PASSPHRASE}" ] || die "backup_passphrase 文件为空"

gpg --batch --yes \
    --pinentry-mode loopback \
    --passphrase "${GPG_PASSPHRASE}" \
    --cipher-algo AES256 \
    --compress-algo none \
    --symmetric \
    --output "${GPG_FILE}" \
    "${SQL_TMP}" 2>/tmp/gpg.err || {
        err="$(cat /tmp/gpg.err 2>/dev/null || echo '未知错误')"
        rm -f /tmp/gpg.err
        die "GPG 加密失败: ${err}"
    }
rm -f /tmp/gpg.err

# 删除明文 dump
rm -f "${SQL_TMP}"

gpg_size=$(stat -c '%s' "${GPG_FILE}" 2>/dev/null || stat -f '%z' "${GPG_FILE}" 2>/dev/null || echo 0)
log "  ✓ GPG 加密完成: ${GPG_FILE} (${gpg_size} bytes)"

# ============================================================================
# 5. 备份 media 目录
# ============================================================================

if [ -d "${MEDIA_DIR}" ]; then
    log "==> 打包 media: ${MEDIA_DIR}"
    # -C 让 tar 内的路径不带 /opt/archery 前缀
    tar -czf "${MEDIA_FILE}" \
        -C "$(dirname "${MEDIA_DIR}")" \
        "$(basename "${MEDIA_DIR}")" 2>/tmp/tar.err || {
            err="$(cat /tmp/tar.err 2>/dev/null || echo '未知错误')"
            rm -f /tmp/tar.err
            die "tar 打包失败: ${err}"
        }
    rm -f /tmp/tar.err

    media_size=$(stat -c '%s' "${MEDIA_FILE}" 2>/dev/null || stat -f '%z' "${MEDIA_FILE}" 2>/dev/null || echo 0)
    log "  ✓ media 打包完成: ${MEDIA_FILE} (${media_size} bytes)"
else
    log "  WARN: media 目录不存在 (${MEDIA_DIR})，跳过 media 备份"
fi

# ============================================================================
# 6. 写 manifest（便于恢复时识别内容）
# ============================================================================

cat > "${MANIFEST_FILE}" <<EOF
backup_date=${DATE}
mysql_databases=${BACKUP_DATABASES}
mysql_host=${MYSQL_HOST}
mysql_port=${MYSQL_PORT}
mysql_dump_size=${gpg_size}
mysql_dump_gpg_file=$(basename "${GPG_FILE}")
media_tar_file=$(basename "${MEDIA_FILE}")
media_tar_size=${media_size:-0}
script_version=04_backup.sh-v1.0
EOF

log "  ✓ manifest: ${MANIFEST_FILE}"

# ============================================================================
# 7. 清理过期备份（> KEEP_DAYS 天）
# ============================================================================

log "==> 清理 ${KEEP_DAYS} 天前的备份"

# -mtime +N：修改时间超过 N*24 小时
deleted_count=$(find "${BACKUP_DIR}" \
    \( -name "*.sql.gpg" -o -name "media_*.tar.gz" -o -name "backup_*.manifest" \) \
    -mtime +"${KEEP_DAYS}" -type f -print -delete | wc -l)
log "  ✓ 已删除 ${deleted_count} 个过期文件"

# ============================================================================
# 8. 报告
# ============================================================================

log "==> 备份完成"
log "  MySQL 加密: ${GPG_FILE}"
log "  Media 打包:  ${MEDIA_FILE:-<跳过>}"
log "  Manifest:    ${MANIFEST_FILE}"
log "  保留策略:    ${KEEP_DAYS} 天"
log "  备份目录占用: $(du -sh "${BACKUP_DIR}" 2>/dev/null | cut -f1)"

# 成功也通知（INFO 级别，避免刷屏；如需关闭可设 BACKUP_NOTIFY_ON_SUCCESS=false）
if [ "${BACKUP_NOTIFY_ON_SUCCESS:-false}" = "true" ]; then
    notify_dingtalk "✓ Archery 备份完成\n时间: ${DATE}\nSQL: $(basename "${GPG_FILE}")\nMedia: $(basename "${MEDIA_FILE:-<none>}" 2>/dev/null)\n保留: ${KEEP_DAYS} 天"
fi

exit 0
