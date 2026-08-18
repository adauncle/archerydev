#!/usr/bin/env bash
# W1 必做 2: D+7 还原演练 (134 dev 端等价演练)
# 用法: bash drill_restore_20260817.sh [DRY_RUN]
# 推 110 当天同款流程: 改 MYSQL_DB=archery (110 库名), 其他不变
#
# 流程:
#   1. mysqldump archery_prod 库 (单事务,gzip)
#   2. gunzip -t 验证
#   3. DROP + CREATE 测试库 archery_drill_restore
#   4. zcat 还原过去
#   5. 验证表数量 / 关键表 schema / 关键数据
#   6. DROP 测试库清理
#
## CUSTOM-DRILL-SCRIPT: D+7 还原演练,推 110 模板 @ 2026-08-17 @ mavis

set -uo pipefail

DRY_RUN="${1:-DRY_RUN}"
DBOPS_PASS=$(cat /etc/archery/dbops_password 2>/dev/null)
if [[ -z "$DBOPS_PASS" ]]; then
  echo "FATAL: /etc/archery/dbops_password 不存在或为空" >&2
  exit 1
fi

# 演练参数
SOURCE_DB="archery_prod"           # 134 dev 库
DRILL_DB="archery_drill_restore"   # 测试库 (演练完 drop)
DRILL_DIR="/opt/archery/prod/scripts/_drill"
TS=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="${DRILL_DIR}/archery_prod_drill_${TS}.sql.gz"
LOG_FILE="${DRILL_DIR}/drill_restore_${TS}.log"

mkdir -p "${DRILL_DIR}"

log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
  echo "${msg}"
  echo "${msg}" >> "${LOG_FILE}"
}

run_mysql() {
  mysql -h 127.0.0.1 -P 3306 -udbops -p"${DBOPS_PASS}" --default-character-set=utf8mb4 "$@"
}

log "=== W1 必做 2: D+7 还原演练 (DRY_RUN=${DRY_RUN}) ==="
log "源库: ${SOURCE_DB}"
log "测试库: ${DRILL_DB}"
log "备份: ${DUMP_FILE}"
log "日志: ${LOG_FILE}"

# 步骤 0: 演练前环境检查
log "--- 步骤 0: 演练前环境检查 ---"
log "MySQL 版本: $(run_mysql -e 'SELECT VERSION()' 2>&1 | tail -1)"
log "磁盘可用: $(df -h /opt/archery | tail -1 | awk '{print $4}')"
log "源库大小: $(run_mysql -e "SELECT ROUND(SUM(data_length+index_length)/1024/1024,1) AS mb FROM information_schema.tables WHERE table_schema='${SOURCE_DB}'" 2>&1 | tail -1) MB"
log "源库表数: $(run_mysql -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${SOURCE_DB}'" 2>&1 | tail -1)"

# 步骤 1: mysqldump
log "--- 步骤 1: mysqldump ${SOURCE_DB} ---"
if [[ "${DRY_RUN}" == "DRY_RUN" ]]; then
  log "[DRY_RUN] 跳过 mysqldump"
else
  time mysqldump \
    -h 127.0.0.1 -P 3306 -udbops -p"${DBOPS_PASS}" \
    --default-character-set=utf8mb4 \
    --single-transaction --quick --routines --triggers --events \
    --set-gtid-purged=OFF \
    --hex-blob \
    "${SOURCE_DB}" 2>>"${LOG_FILE}" | gzip > "${DUMP_FILE}"
  dump_rc=$?
  if [[ ${dump_rc} -ne 0 ]]; then
    log "FATAL: mysqldump 失败 rc=${dump_rc}"
    exit 1
  fi
  log "mysqldump 成功: $(ls -la ${DUMP_FILE} | awk '{print $5}') bytes"
fi

# 步骤 2: gunzip -t 验证
log "--- 步骤 2: gunzip -t 验证 ---"
if [[ "${DRY_RUN}" == "DRY_RUN" ]]; then
  log "[DRY_RUN] 跳过"
else
  if gunzip -t "${DUMP_FILE}" 2>>"${LOG_FILE}"; then
    log "gunzip -t 验证 OK"
  else
    log "FATAL: gunzip -t 失败"
    exit 1
  fi
fi

# 步骤 3: DROP + CREATE 测试库
log "--- 步骤 3: DROP + CREATE 测试库 ${DRILL_DB} ---"
if [[ "${DRY_RUN}" == "DRY_RUN" ]]; then
  log "[DRY_RUN] 跳过"
else
  run_mysql -e "DROP DATABASE IF EXISTS ${DRILL_DB}; CREATE DATABASE ${DRILL_DB} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;" 2>>"${LOG_FILE}"
  if [[ $? -ne 0 ]]; then
    log "FATAL: DROP + CREATE 失败"
    exit 1
  fi
  log "${DRILL_DB} 创建成功"
fi

# 步骤 4: 还原
log "--- 步骤 4: zcat | mysql 还原 ---"
if [[ "${DRY_RUN}" == "DRY_RUN" ]]; then
  log "[DRY_RUN] 跳过"
else
  time zcat "${DUMP_FILE}" | run_mysql "${DRILL_DB}" 2>>"${LOG_FILE}"
  restore_rc=$?
  if [[ ${restore_rc} -ne 0 ]]; then
    log "FATAL: 还原失败 rc=${restore_rc}"
    exit 1
  fi
  log "还原成功"
fi

# 步骤 5: 验证
log "--- 步骤 5: 验证还原结果 ---"
if [[ "${DRY_RUN}" == "DRY_RUN" ]]; then
  log "[DRY_RUN] 跳过"
else
  # 5.1 表数量
  src_count=$(run_mysql -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${SOURCE_DB}'" 2>/dev/null)
  dst_count=$(run_mysql -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${DRILL_DB}'" 2>/dev/null)
  log "表数量: 源库=${src_count} 还原库=${dst_count} $([[ ${src_count} == ${dst_count} ]] && echo "✓ 一致" || echo "✗ 不一致")"

  # 5.2 关键表 schema (sql_workflow / auth_user / ext_ddl_ghost_task)
  for tbl in sql_workflow auth_user ext_ddl_ghost_task; do
    src_col=$(run_mysql -N -e "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='${SOURCE_DB}' AND table_name='${tbl}'" 2>/dev/null)
    dst_col=$(run_mysql -N -e "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='${DRILL_DB}' AND table_name='${tbl}'" 2>/dev/null)
    log "  ${tbl}: 源库列数=${src_col} 还原库列数=${dst_col} $([[ ${src_col} == ${dst_col} && -n ${src_col} ]] && echo "✓" || echo "✗")"
  done

  # 5.3 关键数据
  src_users=$(run_mysql -N -e "SELECT COUNT(*) FROM ${SOURCE_DB}.auth_user" 2>/dev/null)
  if [[ -z "${src_users}" ]]; then
    log "  auth_user: 源库表不存在 (LDAP/SSO 模式,符合预期)"
  else
    dst_users=$(run_mysql -N -e "SELECT COUNT(*) FROM ${DRILL_DB}.auth_user" 2>/dev/null)
    log "  auth_user 行数: 源库=${src_users} 还原库=${dst_users} $([[ ${src_users} == ${dst_users} ]] && echo "✓ 一致" || echo "✗ 不一致")"
  fi

  src_wf=$(run_mysql -N -e "SELECT COUNT(*) FROM ${SOURCE_DB}.sql_workflow" 2>/dev/null)
  dst_wf=$(run_mysql -N -e "SELECT COUNT(*) FROM ${DRILL_DB}.sql_workflow" 2>/dev/null)
  log "sql_workflow 行数: 源库=${src_wf} 还原库=${dst_wf} $([[ ${src_wf} == ${dst_wf} ]] && echo "✓ 一致" || echo "✗ 不一致")"
fi

# 步骤 6: 清理测试库
log "--- 步骤 6: DROP 测试库 ${DRILL_DB} 清理 ---"
if [[ "${DRY_RUN}" == "DRY_RUN" ]]; then
  log "[DRY_RUN] 跳过"
else
  run_mysql -e "DROP DATABASE ${DRILL_DB}" 2>>"${LOG_FILE}"
  log "${DRILL_DB} 已 drop"
fi

log "=== W1 必做 2 演练完成 ==="
log "备份保留: ${DUMP_FILE}"
log "日志: ${LOG_FILE}"
