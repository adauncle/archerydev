#!/bin/bash
# reload_gunicorn_after_code_change.sh — 改 Python 代码后 reload gunicorn
# 134 dev: kill master + systemd 自动拉起
# 110 prod: kill master + 手动 nohup 拉起
#
# 用法:
#   bash reload_gunicorn_after_code_change.sh <env>    # env = 134dev | 110prod
#
# 8/24 教训: gunicorn HUP 不重载 Python 代码, 必须 kill master 让 systemd 拉新进程
# 关联: docs/runbooks/2026-08-24_gunicorn-reload-after-code-change.md

set -e

ENV=${1:-134dev}

case "${ENV}" in
    134dev)
        HOST="root@172.20.2.134"
        PORT=9003
        SERVICE="archery-prod-gunicorn.service"
        ;;
    110prod)
        HOST="root@172.20.2.110"
        PORT=9123
        SERVICE=""  # 110 prod 没 systemd
        ;;
    *)
        echo "Usage: $0 <134dev|110prod>"
        exit 1
        ;;
esac

echo "================================================================"
echo "reload_gunicorn_after_code_change.sh (${ENV})"
echo "  time: $(date)"
echo "  host: ${HOST}"
echo "  port: ${PORT}"
echo "================================================================"

echo ""
echo "=== 1. 找 master pid ==="
master_pid=$(ssh ${HOST} "ps -ef | grep gunicorn | grep -v grep | awk '\$3==1 {print \$2}' | head -1")
if [[ -z "${master_pid}" ]]; then
    echo "ERR: 找不到 master, 排查 gunicorn 进程状态"
    exit 1
fi
echo "master_pid: ${master_pid}"

echo ""
echo "=== 2. kill master ==="
ssh ${HOST} "kill ${master_pid}"
echo "OK: kill ${master_pid}"

echo ""
echo "=== 3. 等 7s 看新进程 (systemd 拉起 master 实际要 5-7s) ==="
sleep 7
if [[ -n "${SERVICE}" ]]; then
    # 134 dev: systemd 拉起
    new_status=$(ssh ${HOST} "systemctl is-active ${SERVICE}")
    echo "systemd status: ${new_status}"
    if [[ "${new_status}" != "active" ]]; then
        echo "ERR: systemd 拉起失败, 看 journalctl -u ${SERVICE} -n 50"
        exit 1
    fi
else
    # 110 prod: 手动 nohup 拉起
    echo "110 prod 没 systemd, DBA 手动 nohup 拉起新进程..."
    echo ""
    echo "  在 110 prod 上跑:"
    echo "  cd /dbdata/archery_v114_c9236a0"
    echo "  nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:${PORT} --access-logfile - --error-logfile - --timeout 120 > /tmp/gunicorn.log 2>&1 &"
    echo ""
    read -p "DBA 拉起完成? (yes/no): " confirm
    if [[ "${confirm}" != "yes" ]]; then
        echo "退出, 推 110 必做补一条 (5 步必做步骤 13 失败)"
        exit 1
    fi
fi

echo ""
echo "=== 4. HTTP 健康检查 ==="
http_out=$(ssh ${HOST} "curl -sI --max-time 5 http://127.0.0.1:${PORT}/" 2>&1 | head -3)
echo "${http_out}"
if echo "${http_out}" | grep -q "200\|302"; then
    echo "OK: HTTP 200/302, gunicorn alive"
else
    echo "ERR: HTTP 不正常, 排查 ${PORT} 端口 + gunicorn log"
    exit 1
fi

echo ""
echo "=== 5. ⚠️ 必做验证: 提新工单看详情页 ==="
echo "DBA 必做:"
echo "  1. 浏览器登平台, 选测试组"
echo "  2. SQL 上线提交页 → 选 group / instance / db → 看 '审批流程' 应跟 admin config 配的一致"
echo "  3. 提一条新工单 (随便一句 ALTER ... DROP COLUMN xxx)"
echo "  4. detail 页 → '审批流' → ⚠️ 必须跟 admin config 配的一致"
echo ""
echo "  如果 3+4 不一致 → kill master 没生效, 排查 master 启动时间 (runbook §故障排查)"
echo ""

read -p "DBA 验证完成? (yes/no): " confirm
if [[ "${confirm}" != "yes" ]]; then
    echo "退出, 推 110 必做补一条 (5 步必做步骤 13 失败)"
    exit 1
fi

echo ""
echo "=== ✅ reload gunicorn 流程完成 ==="
echo "  host: ${HOST}"
echo "  port: ${PORT}"
echo "  master: ${master_pid} → 已 kill"
echo "  验证: 提新工单 detail 页已确认"
