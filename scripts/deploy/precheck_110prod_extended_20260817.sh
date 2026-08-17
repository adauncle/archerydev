#!/bin/bash
# precheck_110prod_extended_20260817.sh — 推 110 prod 关联组件 + 资源 extended precheck
#
# ⚠️  本脚本是 110 prod 内部命令清单, 不通过 sshpass 远程调用
# ⚠️  跑法: ssh 登 110 prod → bash /tmp/precheck_110prod_extended_20260817.sh
#
# 覆盖:
# - Redis 容器 (172.19.0.4:6379) 状态 + 连通 + 密码
# - goinception 容器 状态 + 连通 + panic 现场
# - Nginx (httpd) 状态 + 80 端口 + 静态资源
# - MySQL 5.7.44 主库 进程 + socket + 主从状态
# - 磁盘 / 内存 / CPU 资源
# - 134 dev ↔ 110 prod 网络连通

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

ok() { echo -e "${GREEN}[OK]${NC} $*"; PASS=$((PASS+1)); }
err() { echo -e "${RED}[ERR]${NC} $*"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; WARN=$((WARN+1)); }
section() { echo ""; echo "=== $* ==="; }

echo "================================================================"
echo "precheck_110prod_extended_20260817.sh (在 110 prod 内部跑)"
echo "  时间: $(date)"
echo "  推 110 前关联组件 + 资源 + 老进程/僵尸容器 摸底"
echo "================================================================"

# === 0. 老进程/僵尸容器/孤儿 venv (8/13 警告遗留问题) ===
section "0. 老进程/僵尸容器/孤儿 venv (8/13 警告遗留)"
echo ""
echo "  0.1 孤儿 gunicorn 进程 (老的 archery_v114/venv 不在 active 目录)"
out=$(ps aux | grep "archery_v114/venv" | grep -v grep | head -5)
echo "  $out"
old_gunicorn_count=$(echo "$out" | grep -c "gunicorn" || echo "0")
if [[ "$old_gunicorn_count" -gt 0 ]]; then
    warn "发现 ${old_gunicorn_count} 个孤儿 gunicorn 进程 (老 venv 路径), 推 110 前清理"
    echo "  清理命令: pkill -9 -f 'archery_v114/venv/bin/gunicorn' (谨慎, 确认是 9004 老进程)"
else
    ok "无孤儿 gunicorn 进程"
fi

echo ""
echo "  0.2 僵尸 docker 容器 (Exited 但还在)"
out=$(docker ps -a 2>/dev/null | grep -E "Exited|Dead" | head -10)
echo "$out"
if [[ -n "$out" ]]; then
    warn "发现僵尸容器 (上面 list), 推 110 前 docker rm 清理"
else
    ok "无僵尸 docker 容器"
fi

echo ""
echo "  0.3 孤儿 venv 目录 (老 /dbdata/archery_v114/venv/ 跟 active 冲突检查)"
out=$(ls -ld /dbdata/archery_v114/venv 2>&1)
echo "  $out"
if [[ -f /dbdata/archery_v114/venv/bin/gunicorn ]]; then
    warn "老 venv 存在 /dbdata/archery_v114/venv/bin/gunicorn, 跟 9123 venv 同名"
    echo "  风险: 老 venv 的 gunicorn 如果被 systemd 误启会覆盖 9123"
fi

echo ""
echo "  0.4 老的备份目录 (8/13 记忆里 archery_v110_backup Exited 4 days 早失效)"
out=$(ls -d /dbdata/archery_v110_backup 2>&1)
echo "  $out"
if [[ -d "/dbdata/archery_v110_backup" ]]; then
    warn "/dbdata/archery_v110_backup 还在, A 级回滚保险早失效 (8/13 警告)"
fi

# === 1. Redis 容器 ===
section "1. Redis 容器 (172.19.0.4:6379)"
out=$(docker ps 2>/dev/null | grep -i redis)
echo "  docker ps | grep redis:"
echo "  $out"
if echo "$out" | grep -q "Up"; then
    ok "Redis 容器在跑"
else
    err "Redis 容器没在跑, 推 110 时缓存/celery broker 会断"
fi

# Redis 端口连通
out=$(timeout 3 bash -c "echo > /dev/tcp/172.19.0.4/6379" 2>&1 && echo "OK" || echo "FAIL")
if [[ "$out" == "OK" ]]; then
    ok "Redis 端口 172.19.0.4:6379 可连"
else
    err "Redis 端口 172.19.0.4:6379 不可连"
fi

# Redis 密码验证
out=$(redis-cli -h 172.19.0.4 -p 6379 PING 2>&1)
echo "  redis-cli PING: $out"
if [[ "$out" == *"PONG"* ]]; then
    ok "Redis PING 正常"
else
    warn "Redis 密码可能没配 (或 redis-cli 不存在): $out"
fi

# === 2. goinception 容器 ===
section "2. goinception 容器"
out=$(docker ps 2>/dev/null | grep -i inception)
echo "  docker ps | grep inception:"
echo "  $out"
if echo "$out" | grep -q "Up"; then
    ok "goinception 容器在跑"
else
    err "goinception 容器没在跑, 推 110 时 SQL 检测会全断"
fi

# goinception panic 现场
echo ""
echo "  最近 10 行 goinception 日志 (查 panic 现场):"
out=$(docker logs --tail 10 $(docker ps -q --filter "ancestor=hanchuanchuan/goinception" 2>/dev/null | head -1) 2>&1)
echo "$out" | head -15
if echo "$out" | grep -q "panic\|FATAL\|slice bounds"; then
    warn "goinception 日志有 panic/FATAL, 推 110 前最好先排查"
else
    ok "goinception 日志无 panic/FATAL"
fi

# === 3. Nginx (httpd) ===
section "3. Nginx (httpd) 80 端口"
out=$(systemctl is-active httpd 2>&1 || echo "unknown")
echo "  systemctl is-active httpd: $out"
if [[ "$out" == "active" ]]; then
    ok "httpd active"
else
    warn "httpd 不是 active, 推 110 时 80 端口可能断 (110 prod 用户访问入口)"
fi

# 80 端口
out=$(ss -tlnp 2>/dev/null | grep ":80 " | head -3)
echo "  ss -tlnp 80: $out"
if echo "$out" | grep -q ":80"; then
    ok "80 端口在监听"
else
    err "80 端口没监听, 用户访问入口断"
fi

# 80 端口 curl
out=$(curl -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:80/admin/login/ 2>&1)
echo "  curl http://127.0.0.1:80/admin/login/ → $out"
if [[ "$out" == "200" || "$out" == "302" ]]; then
    ok "http 80 → 9123 反代正常 (admin/login 返 $out)"
else
    err "http 80 → 9123 反代失败 (admin/login 返 $out)"
fi

# 静态资源
out=$(curl -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:80/static/bootstrap/css/bootstrap.min.css 2>&1)
echo "  curl /static/bootstrap/css/bootstrap.min.css → $out"
if [[ "$out" == "200" ]]; then
    ok "静态资源 bootstrap.css 200"
else
    warn "静态资源 bootstrap.css 返 $out (8/10 教训: 静态资源必须验)"
fi

# === 4. MySQL 5.7.44 主库 ===
section "4. MySQL 5.7.44 主库"
out=$(ps aux | grep mysqld | grep -v grep | head -1)
echo "  mysqld 进程: $out" | head -2
if echo "$out" | grep -q "mysqld"; then
    ok "mysqld 进程在跑"
else
    err "mysqld 进程不在, 推 110 时所有 DB 操作断"
fi

# socket 连通
out=$(mysql --defaults-file=/root/.my.cnf -e "SELECT VERSION();" 2>&1 | grep -v "Warning")
echo "  MySQL VERSION: $out"
if [[ "$out" == *"5.7"* ]]; then
    ok "MySQL 5.7.x 版本对 (跟 user memory 5.7.44 一致)"
else
    warn "MySQL 版本不是 5.7: $out"
fi

# 主从状态
echo ""
echo "  SHOW SLAVE STATUS:"
out=$(mysql --defaults-file=/root/.my.cnf -e "SHOW SLAVE STATUS\G" 2>&1 | grep -v "Warning")
if [[ -z "$out" ]]; then
    warn "无主从配置 (110 prod 是单库, 推 110 时 D+1 备份是唯一保险)"
else
    echo "$out" | head -20
    if echo "$out" | grep -q "Seconds_Behind_Master: 0"; then
        ok "主从延迟 0"
    fi
fi

# === 5. 磁盘空间 ===
section "5. 磁盘空间 (D 级备份 ~30GB 需要)"
out=$(df -h /dbdata /var/log 2>&1)
echo "$out"
use_pct=$(df -h /dbdata 2>&1 | tail -1 | awk '{print $5}' | tr -d '%')
if [[ "$use_pct" -lt 50 ]]; then
    ok "/dbdata 空闲充足 (Use%=${use_pct}%)"
elif [[ "$use_pct" -lt 80 ]]; then
    warn "/dbdata 空间紧 (Use%=${use_pct}%), 推 110 D 级备份前先清理"
else
    err "/dbdata 满了 (Use%=${use_pct}%), 推 110 前必须清理"
fi

# === 6. 内存 / CPU ===
section "6. 内存 / CPU 资源"
out=$(free -h 2>&1)
echo "$out"
mem_avail=$(free -m 2>&1 | grep Mem | awk '{print $7}')
if [[ "$mem_avail" -gt 2000 ]]; then
    ok "可用内存 ${mem_avail}MB > 2GB (restart gunicorn 不会 OOM)"
elif [[ "$mem_avail" -gt 1000 ]]; then
    warn "可用内存 ${mem_avail}MB, 推 110 restart 时需关注"
else
    err "可用内存 ${mem_avail}MB < 1GB, restart gunicorn 可能 OOM"
fi

out=$(uptime 2>&1)
echo "  uptime: $out"
load_1min=$(echo "$out" | awk -F'load average:' '{print $2}' | awk -F, '{print $1}' | xargs)
echo "  1min load: $load_1min"
load_int=$(echo "$load_1min" | cut -d. -f1)
if [[ "$load_int" -lt 4 ]]; then
    ok "load average 1min = $load_1min (健康)"
else
    warn "load average 1min = $load_1min (推 110 时需关注)"
fi

# === 7. 134 dev ↔ 110 prod 网络 ===
section "7. 134 dev ↔ 110 prod 网络 (推 110 时 sync 物料走这)"
# 110 prod ping 134 dev
out=$(timeout 5 ping -c 3 172.20.2.134 2>&1 | tail -3)
echo "  ping 134 dev: $out"
if echo "$out" | grep -q "0% packet loss"; then
    ok "110 → 134 dev 网络通 (0% packet loss)"
else
    warn "110 → 134 dev 网络可能不稳"
fi

# 134 dev ssh 22 端口
out=$(timeout 3 bash -c "echo > /dev/tcp/172.20.2.134/22" 2>&1 && echo "OK" || echo "FAIL")
if [[ "$out" == "OK" ]]; then
    ok "134 dev 22 端口可连 (ssh 推物料走这)"
else
    err "134 dev 22 端口不可连, 推 110 时 scp 物料会断"
fi

# === Summary ===
echo ""
echo "================================================================"
echo "  ${GREEN}OK${NC}:   $PASS"
echo "  ${YELLOW}WARN${NC}: $WARN"
echo "  ${RED}ERR${NC}:  $FAIL"
echo "================================================================"

if [[ $FAIL -gt 0 ]]; then
    echo "❌ 有 $FAIL 项 ERR, 推 110 前必须修复"
    exit 1
elif [[ $WARN -gt 0 ]]; then
    echo "⚠️  有 $WARN 项 WARN, 推 110 时需关注"
    exit 0
else
    echo "✅ 全部 OK, 可以推 110"
    exit 0
fi
