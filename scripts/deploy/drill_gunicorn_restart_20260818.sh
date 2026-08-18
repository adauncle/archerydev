#!/bin/bash
# W2 必做 5: gunicorn restart 演练
# 134 dev 端 kill -HUP 平滑重启, 验证 9003 端口 5 个端点 + 进程数 + DB 数据
## CUSTOM-DRILL-SCRIPT: gunicorn restart 演练,推 110 模板 @ 2026-08-18 @ mavis
PORT=9003
BASE="http://127.0.0.1:${PORT}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# 找 gunicorn master pid (启动时间最早的 = master)
# pgrep -f gunicorn 包含所有 gunicorn 进程, master 是 ppid=1 的那个
find_master_pid() {
  for pid in $(pgrep -f gunicorn); do
    ppid=$(cat /proc/$pid/stat 2>/dev/null | awk '{print $4}')
    if [[ "$ppid" == "1" ]]; then
      echo $pid
      return
    fi
  done
  # fallback: 第一个 gunicorn 进程
  pgrep -f gunicorn | head -1
}

# 1) 重启前进程状态
log "=== 1) 重启前 gunicorn 进程 ==="
ps -eo pid,comm,cmd | grep gunicorn | grep -v grep
MASTER_PID=$(find_master_pid)
WORKER_COUNT_BEFORE=$(ps -eo comm | grep -c "^gunicorn$")
log "  Master PID: $MASTER_PID"
log "  Worker count (comm=gunicorn): $WORKER_COUNT_BEFORE (期望 5: 1 master + 4 worker)"

# 2) 重启前 curl 5 端点
log ""
log "=== 2) 重启前 5 端点 HTTP 状态码 ==="
for path in / /login/ /dashboard/ /admin/ /gh_ost/list/; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${BASE}${path}" 2>&1)
  log "  ${path} → ${code}"
done

# 3) 触发 HUP
log ""
log "=== 3) kill -HUP $MASTER_PID (gunicorn reload) ==="
if [[ -n "$MASTER_PID" ]]; then
  kill -HUP $MASTER_PID
  hup_rc=$?
  log "  kill -HUP rc=$hup_rc"
  sleep 4
else
  log "  FATAL: 找不到 master pid, 跳过"
  exit 1
fi

# 4) 重启后进程状态
log ""
log "=== 4) 重启后 gunicorn 进程 ==="
ps -eo pid,comm,cmd | grep gunicorn | grep -v grep
NEW_MASTER_PID=$(find_master_pid)
log "  New Master PID: $NEW_MASTER_PID (was $MASTER_PID)"
WORKER_COUNT=$(ps -eo comm | grep -c "^gunicorn$")
log "  Worker count (comm=gunicorn): $WORKER_COUNT (期望 5: 1 master + 4 worker, 跟重启前 $WORKER_COUNT_BEFORE 对比)"

# 5) 重启后 curl 5 端点
log ""
log "=== 5) 重启后 5 端点 HTTP 状态码 ==="
for path in / /login/ /dashboard/ /admin/ /gh_ost/list/; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${BASE}${path}" 2>&1)
  log "  ${path} → ${code}"
done

# 6) DB 数据验证 (ext_approval_flow 仍 14,15,3)
log ""
log "=== 6) DB 数据验证 (ext_approval_flow) ==="
DBOPS_PASS=$(cat /etc/archery/dbops_password)
mysql -h 127.0.0.1 -udbops -p"${DBOPS_PASS}" archery_prod -e "SELECT code, audit_auth_groups FROM ext_approval_flow;" 2>&1 | grep -v Warning

# 7) gh-ost 端点细查
log ""
log "=== 7) gh-ost 端点详查 ==="
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${BASE}/gh_ost/list/" 2>&1)
log "  /gh_ost/list/ → ${code} (期望 302 跳登录)"
redirect=$(curl -s -I --max-time 10 "${BASE}/gh_ost/list/" 2>&1 | grep -i ^location)
log "  redirect: $redirect"

# 8) 静态资源 200 验证
log ""
log "=== 8) 静态资源验证 ==="
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${BASE}/static/css/style.css" 2>&1)
log "  /static/css/style.css → ${code}"
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${BASE}/static/img/logo.png" 2>&1)
log "  /static/img/logo.png → ${code}"

log ""
log "=== W2 必做 5 演练完成 ==="
