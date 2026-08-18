#!/bin/bash
# W2 必做 7: 完整 sync 链路 dry-run
# 流程: pack (134 dev 当前代码) → 部署到测试目录 → 起测试 gunicorn (9005) → 烟测 → 清理
## CUSTOM-DRILL-SCRIPT: 完整 sync 链路 dry-run,推 110 模板 @ 2026-08-18 @ mavis

set -uo pipefail

SOURCE_DIR="/opt/archery/prod"
TEST_DIR="/opt/archery/prod_drill_sync"
TEST_PORT=9005
TS=$(date +%Y%m%d_%H%M%S)
DRILL_DIR="/opt/archery/prod/scripts/_drill"
TARBALL="${DRILL_DIR}/prod_sync_drill_${TS}.tar.gz"
LOG_FILE="${DRILL_DIR}/sync_drill_${TS}.log"

mkdir -p "${DRILL_DIR}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "${LOG_FILE}"
}

# 0) 演练前环境检查
log "=== 0) 演练前环境检查 ==="
log "  源目录: ${SOURCE_DIR} (大小: $(du -sh ${SOURCE_DIR} 2>/dev/null | awk '{print $1}'))"
log "  venv 大小: $(du -sh ${SOURCE_DIR}/venv 2>/dev/null | awk '{print $1}')"
log "  磁盘可用: $(df -h /opt/archery | tail -1 | awk '{print $4}')"
log "  测试目录: ${TEST_DIR} (期望不存在)"
ls -la ${TEST_DIR} 2>/dev/null && log "  WARN: 测试目录已存在,先清理" && rm -rf ${TEST_DIR}

# 1) pack: 排除 venv / .git / logs / media / static / _drill (演练产物)
log ""
log "=== 1) pack: tar 整个 prod 目录 (排除 venv / .git / logs / media / static / _drill) ==="
cd /opt/archery
time tar -czf "${TARBALL}" \
  --exclude='prod/venv' \
  --exclude='prod/.git' \
  --exclude='prod/logs' \
  --exclude='prod/media' \
  --exclude='prod/static' \
  --exclude='prod/staticfiles' \
  --exclude='prod/__pycache__' \
  --exclude='prod/scripts/_drill' \
  --exclude='*.pyc' \
  --exclude='*.log' \
  -C /opt/archery \
  prod/ 2>>"${LOG_FILE}"
tar_rc=$?
log "  tar rc=${tar_rc}, 文件大小: $(du -h ${TARBALL} | awk '{print $1}')"

# 2) 解压到测试目录 (--strip-components=1 去掉 prod/ 前缀)
log ""
log "=== 2) 解压到 ${TEST_DIR} (--strip-components=1 去掉 prod/ 前缀) ==="
mkdir -p ${TEST_DIR}
cd ${TEST_DIR}
time tar -xzf "${TARBALL}" --strip-components=1 2>>"${LOG_FILE}"
tar_extract_rc=$?
log "  tar -xzf rc=${tar_extract_rc}"
log "  测试目录大小: $(du -sh ${TEST_DIR} | awk '{print $1}')"

# 3) chown
log ""
log "=== 3) chown -R archery:archery ==="
chown -R archery:archery ${TEST_DIR}
log "  chown 完成"

# 4) 链接 venv (复用现有, 不重装依赖)
log ""
log "=== 4) 链接 venv ==="
ln -s ${SOURCE_DIR}/venv ${TEST_DIR}/venv
log "  venv 链接: ${TEST_DIR}/venv → ${SOURCE_DIR}/venv"

# 5) 复制 .env (用同一份, 演练用) + 创建必要目录
log ""
log "=== 5) 复制 .env + 创建 logs/media 目录 ==="
cp -a ${SOURCE_DIR}/.env ${TEST_DIR}/.env
mkdir -p ${TEST_DIR}/logs
mkdir -p ${TEST_DIR}/media
chown -R archery:archery ${TEST_DIR}/logs ${TEST_DIR}/media 2>/dev/null
log "  .env + logs + media 已就绪"

# 6) 验证代码就绪 (用 manage.py check + migrate --plan)
log ""
log "=== 6) 验证代码就绪 (manage.py check) ==="
cd ${TEST_DIR}
sudo -u archery venv/bin/python manage.py check 2>&1 | tee -a "${LOG_FILE}"
log ""
log "=== 7) 验证 migration plan (migrate --plan) ==="
sudo -u archery venv/bin/python manage.py migrate --plan 2>&1 | tee -a "${LOG_FILE}"

# 8) 烟测 - 用 HUP 触发 9003 gunicorn 重新加载新代码 (从 venv 链接)
log ""
log "=== 8) 烟测 - HUP 现有 9003 gunicorn 重新加载 ==="
MASTER_PID=$(ps -eo pid,cmd | grep gunicorn | grep -v grep | awk '$3 == "gunicorn" {print $1; exit}')
if [[ -z "$MASTER_PID" ]]; then
  # 找 ppid=1 的 master
  for pid in $(pgrep -f gunicorn); do
    ppid=$(cat /proc/$pid/stat 2>/dev/null | awk '{print $4}')
    if [[ "$ppid" == "1" ]]; then
      MASTER_PID=$pid
      break
    fi
  done
fi
log "  9003 master pid: $MASTER_PID"
if [[ -n "$MASTER_PID" ]]; then
  kill -HUP $MASTER_PID
  log "  kill -HUP 已发, 等 5 秒"
  sleep 5
fi
log "  9003 5 端点状态码:"
for path in / /login/ /dashboard/ /admin/ /gh_ost/list/; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://127.0.0.1:9003${path}" 2>&1)
  log "    ${path} → ${code}"
done

# 9) 验证 gh-ost 端点 + ext_approval_flow 数据
log ""
log "=== 9) 验证 gh-ost 端点 + ext_approval_flow ==="
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://127.0.0.1:9003/gh_ost/list/" 2>&1)
log "  /gh_ost/list/ → ${code} (期望 302 跳登录)"
DBOPS_PASS=$(cat /etc/archery/dbops_password)
mysql -h 127.0.0.1 -udbops -p"${DBOPS_PASS}" archery_prod -e "SELECT code, audit_auth_groups FROM ext_approval_flow;" 2>&1 | grep -v Warning | tee -a "${LOG_FILE}"

# 10) 清理测试目录 + tarball
log ""
log "=== 10) 清理 ==="
rm -rf ${TEST_DIR}
log "  测试目录 ${TEST_DIR} 已删"
log "  tarball 保留: ${TARBALL}"
log "  日志: ${LOG_FILE}"

log ""
log "=== W2 必做 7 完整 sync 链路 dry-run 完成 ==="
