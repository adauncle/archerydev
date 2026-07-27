#!/bin/bash
# 部署 archery-prod-qcluster systemd unit + 启用 + 启动
# 关联 changelog: docs/changelogs/2026-07-27_v0.1.9-qcluster-and-oa-observability.md
set -e

if [ "$EUID" -ne 0 ]; then
  echo "ERROR: need root to install systemd unit" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UNIT_SRC="$SCRIPT_DIR/systemd/archery-prod-qcluster.service"
UNIT_DST="/etc/systemd/system/archery-prod-qcluster.service"

if [ ! -f "$UNIT_SRC" ]; then
  echo "ERROR: unit file not found at $UNIT_SRC" >&2
  exit 1
fi

echo "1. Copying unit file..."
cp "$UNIT_SRC" "$UNIT_DST"
chmod 644 "$UNIT_DST"

echo "2. daemon-reload..."
systemctl daemon-reload

echo "3. enable (开机自启)..."
systemctl enable archery-prod-qcluster

echo "4. start..."
systemctl start archery-prod-qcluster

sleep 3

echo
echo "5. status:"
systemctl is-active archery-prod-qcluster
ps -ef | grep "manage.py qcluster" | grep -v grep

echo
echo "=== done. Verify 钉钉通知: ==="
echo "1. 用户提交一条新工单"
echo "2. tail -f /opt/archery/prod/logs/qcluster.log"
echo "3. 看 '[INFO] 钉钉 OA 工作通知发送成功 通知对象:[...]' 行"
echo
echo "或者命令行触发："
echo "  cd /opt/archery/prod && sudo -u archery ./venv/bin/python -c \\"
echo "  \"import os; os.environ['DJANGO_SETTINGS_MODULE']='archery.settings'; import django; django.setup(); \\"
echo "  from sql.models import WorkflowAudit; from sql.notify import notify_for_audit; \\"
echo "  notify_for_audit(workflow_audit=WorkflowAudit.objects.get(audit_id=<ID>))\""
