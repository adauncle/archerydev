#!/bin/bash
# precheck_push_110prod.sh — 推 110 prod 当天 推前确认 (在 110 prod 上直接跑)
#
# ⚠️  本脚本是 110 prod 内部命令清单, 不通过 sshpass 远程调用
# ⚠️  跑法: ssh 登 110 prod → bash /tmp/precheck_push_110prod.sh
# ⚠️  不要在 134 dev / Windows 上跑 (本机会找不到 mysql / 110 文件系统)
#
# 跟 runbook `docs/runbooks/2026-08-17_push-v030b-to-110prod.md` 阶段 0 一一对应

DEPLOY_DATE=$(date +%Y%m%d)
BACKUP_DIR="/dbdata/archery_v114_pre_gh_ost_${DEPLOY_DATE}"

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
echo "precheck_push_110prod.sh (在 110 prod 内部跑)"
echo "  时间: $(date)"
echo "  备份目录 (D 级): $BACKUP_DIR"
echo "  只读检查, 不改任何东西"
echo "================================================================"

# === 0.1 gunicorn 状态 ===
section "0.1 gunicorn 状态"
out=$(ps aux | grep gunicorn | grep -v grep | head -3)
echo "$out"
if echo "$out" | grep -q "gunicorn"; then
    gunicorn_count=$(echo "$out" | wc -l)
    if [[ $gunicorn_count -ge 3 ]]; then
        ok "gunicorn ${gunicorn_count} 进程在跑 (主+worker)"
    else
        warn "gunicorn 只有 ${gunicorn_count} 进程, 期望 ≥ 3"
    fi
else
    err "gunicorn 进程不在, 110 prod 不可用"
fi

# === 0.2 端口 9123 ===
section "0.2 端口 9123"
out=$(ss -tlnp 2>/dev/null | grep 9123 || netstat -tlnp 2>/dev/null | grep 9123)
if echo "$out" | grep -q ":9123"; then
    ok "9123 端口在监听"
else
    err "9123 端口没监听, 110 prod 服务不可用"
fi

# === 0.3 curl admin/login ===
section "0.3 curl admin/login"
out=$(curl -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:9123/admin/login/)
if [[ "$out" == "200" || "$out" == "302" ]]; then
    ok "admin/login 返 $out (200/302 正常)"
else
    err "admin/login 返 $out, 期望 200/302"
fi

# === 0.4 /var/log/archery/ 权属 ===
section "0.4 /var/log/archery/ 权属"
out=$(ls -ld /var/log/archery/)
echo "$out"
if echo "$out" | grep -q "archery archery"; then
    ok "/var/log/archery/ 是 archery:archery"
else
    warn "/var/log/archery/ 不是 archery:archery, 推 110 时 chown"
fi

# === 0.5 /var/log/archery/gh_ost/ 子目录 ===
section "0.5 /var/log/archery/gh_ost/ 子目录"
out=$(ls -ld /var/log/archery/gh_ost/ 2>&1)
if echo "$out" | grep -q "No such file"; then
    warn "/var/log/archery/gh_ost/ 不存在, 推 110 时 mkdir"
else
    if echo "$out" | grep -q "archery archery"; then
        ok "gh_ost 子目录存在且权属对"
    else
        warn "gh_ost 子目录存在但权属错: $out"
    fi
fi

# === 0.6 sock 残留 ===
section "0.6 sock 残留"
out=$(ls -la /tmp/gh-ost.*.sock 2>&1 | head -5)
if echo "$out" | grep -q "No such file"; then
    ok "/tmp/gh-ost.*.sock 无残留"
else
    warn "有 sock 残留: $out"
fi

# === 0.7 影子表 ===
section "0.7 影子表 (ext_ddl_ghost_task 残留 + _gho/_del/_ghc)"
out=$(mysql --defaults-file=/root/.my.cnf -D archery -N -e "SELECT GROUP_CONCAT(table_name SEPARATOR ', ') FROM information_schema.tables WHERE table_schema = 'archery' AND (table_name LIKE '%_gho' OR table_name LIKE '%_del' OR table_name LIKE '%_ghc');")
if [[ -z "$out" || "$out" == "NULL" ]]; then
    ok "影子表 0 张"
else
    err "有影子表: $out"
fi

# === 0.8 ext_ddl_ghost_task 表 ===
section "0.8 ext_ddl_ghost_task 表 (推 110 时 migration 必建)"
out=$(mysql --defaults-file=/root/.my.cnf -D archery -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'archery' AND table_name = 'ext_ddl_ghost_task';")
if [[ "$out" == "1" ]]; then
    ok "ext_ddl_ghost_task 表存在"
else
    warn "ext_ddl_ghost_task 表不存在 (推 110 时 migration 0001-0004 必建)"
fi

# === 0.9 ext_approval_flow 表数据 ===
section "0.9 ext_approval_flow 表数据"
out=$(mysql --defaults-file=/root/.my.cnf -D archery -N -e "SELECT GROUP_CONCAT(name, '=', audit_auth_groups SEPARATOR ' | ') FROM ext_approval_flow;")
if [[ -z "$out" || "$out" == "NULL" ]]; then
    warn "ext_approval_flow 表空, 推 110 时 fix_approval_flow_3level 会建 3 个 flow"
else
    ok "ext_approval_flow 数据: $out"
fi

# === 0.10 mysql_slow_query_review_history 表 ===
section "0.10 mysql_slow_query_review_history 表"
out=$(mysql --defaults-file=/root/.my.cnf -D archery -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'archery' AND table_name = 'mysql_slow_query_review_history';")
if [[ "$out" == "1" ]]; then
    ok "mysql_slow_query_review_history 表存在"
else
    err "mysql_slow_query_review_history 表不存在 (跟 8/17 dashboard 修复相关)"
fi

# === 0.11 备份情况 (D+7 保险 + D 级) ===
section "0.11 备份情况 (D+7 保险 + D 级)"
out=$(ls -d /dbdata/archery_v114 2>&1; du -sh /dbdata/archery_v114 2>&1)
echo "$out"
if echo "$out" | grep -q "archery_v114"; then
    ok "D+7 保险 /dbdata/archery_v114 存在"
else
    err "D+7 保险 /dbdata/archery_v114 不存在, 不能回滚"
fi

out=$(ls -la /backup/upgrade_v114/ 2>&1 | head -5)
if echo "$out" | grep -q "archery_pre_v114"; then
    ok "D+7 mysqldump 备份存在"
else
    err "D+7 mysqldump 备份不存在, 不能回滚"
fi

# === 0.12 业务流量 ===
section "0.12 业务流量 (推 110 时机参考)"
out=$(mysql --defaults-file=/root/.my.cnf -D archery -N -e "SELECT CONCAT('today=', (SELECT COUNT(*) FROM sql_workflow WHERE create_time >= CURDATE()), ' week=', (SELECT COUNT(*) FROM sql_workflow WHERE create_time >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)), ' total=', (SELECT COUNT(*) FROM sql_workflow));")
echo "$out"
ok "业务流量: $out"

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
    echo "⚠️  有 $WARN 项 WARN, 推 110 时 5 步必做会修"
    exit 0
else
    echo "✅ 全部 OK, 可以推 110"
    exit 0
fi
