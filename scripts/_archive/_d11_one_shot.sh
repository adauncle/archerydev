#!/bin/bash
# D11 实战 - 134 dev 端点 verify + detail/119 渲染验证 (单脚本)
set -e

echo "=== 14 端点 verify ==="
for ep in /login/ / /admin/ /dbaprinciples/ /sqlworkflow/ /ddl_sync/ /ddl_sync/pair/list/ /ddl_sync/pair/1/ /ddl_sync/pair/1/compute_diff/ /ddl_sync/pair/1/one_click_setup/ /ddl_sync/pair/1/bulk_import/ /ddl_sync/pair/1/add_table/ /ddl_sync/history/ /static/ddl_sync/pair_detail.js; do
  code=$(curl -sS -m 5 -o /dev/null -w 'HTTP:%{http_code}' "http://127.0.0.1:9003${ep}")
  echo "  $ep -> $code"
done

echo ""
echo "=== detail/119 实际渲染 ==="
sudo -u archery /opt/archery/prod/venv/bin/python /tmp/d11_render_v2.py
echo ""
echo "=== grep var dbName ==="
grep -n 'var dbName\|var sqlContent\|var instanceId\|hly_accesscard_history' /tmp/d11_detail119_render.html | head -10

echo ""
echo "=== Django check ddl_sync ==="
cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py check ddl_sync 2>&1 | tail -5

echo ""
echo "=== gunicorn ps ==="
ps -eo pid,ppid,etime,cmd | grep gunicorn | grep -v grep

echo ""
echo "=== 9003 端口 ==="
ss -tlnp 2>/dev/null | grep 9003 || netstat -tlnp 2>/dev/null | grep 9003

echo ""
echo "=== md5 ==="
md5sum /opt/archery/prod/sql/templates/detail.html /opt/archery/prod/sql/views.py

echo ""
echo "DONE"
