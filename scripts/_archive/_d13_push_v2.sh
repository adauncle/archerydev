#!/bin/bash
# D13 实战 - 推 134 dev 3 文件 + kill gunicorn 拉新
set -e

echo "=== D13 推 134 dev ==="
DATE=$(date +%Y%m%d_%H%M%S)
echo "Backup timestamp: $DATE"

# 1. 备份 134 dev 现场
echo ""
echo "[1/6] 备份 134 dev 现场"
sudo -u archery cp /opt/archery/prod/sql/extensions/ddl_gh_ost/services/column_diff.py /opt/archery/prod/sql/extensions/ddl_gh_ost/services/column_diff.py.bak_$DATE
sudo -u archery cp /opt/archery/prod/sql/templates/detail.html /opt/archery/prod/sql/templates/detail.html.bak_$DATE
sudo -u archery cp /opt/archery/prod/sql/templates/sqlsubmit.html /opt/archery/prod/sql/templates/sqlsubmit.html.bak_$DATE
ls -la /opt/archery/prod/sql/extensions/ddl_gh_ost/services/column_diff.py.bak_$DATE /opt/archery/prod/sql/templates/detail.html.bak_$DATE /opt/archery/prod/sql/templates/sqlsubmit.html.bak_$DATE

# 2. /tmp 文件已 SFTP 推上去了 (root 推), 用 root cp 覆盖 + chown
echo ""
echo "[2/6] root cp 覆盖 3 文件 + chown"
cp /tmp/_push_column_diff.py /opt/archery/prod/sql/extensions/ddl_gh_ost/services/column_diff.py && chown archery:archery /opt/archery/prod/sql/extensions/ddl_gh_ost/services/column_diff.py
cp /tmp/_push_detail.html /opt/archery/prod/sql/templates/detail.html && chown archery:archery /opt/archery/prod/sql/templates/detail.html
cp /tmp/_push_sqlsubmit.html /opt/archery/prod/sql/templates/sqlsubmit.html && chown archery:archery /opt/archery/prod/sql/templates/sqlsubmit.html
ls -la /opt/archery/prod/sql/extensions/ddl_gh_ost/services/column_diff.py /opt/archery/prod/sql/templates/detail.html /opt/archery/prod/sql/templates/sqlsubmit.html

# 3. md5 验证
echo ""
echo "[3/6] md5 验证"
md5sum /opt/archery/prod/sql/extensions/ddl_gh_ost/services/column_diff.py /opt/archery/prod/sql/templates/detail.html /opt/archery/prod/sql/templates/sqlsubmit.html
echo "---local---"
md5sum /tmp/_push_column_diff.py /tmp/_push_detail.html /tmp/_push_sqlsubmit.html

# 4. 清 __pycache__
echo ""
echo "[4/6] 清 __pycache__"
find /opt/archery/prod -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
echo "剩余 __pycache__: $(find /opt/archery/prod -type d -name __pycache__ 2>/dev/null | wc -l)"

# 5. kill 老 gunicorn + nohup 拉新 (disown 脱钩)
echo ""
echo "[5/6] kill gunicorn + 拉新"
pkill -9 -f 'gunicorn archery.wsgi' || true
sleep 2
echo "after kill: $(pgrep -f 'gunicorn archery.wsgi' | head -5 || true)"

cd /opt/archery/prod && nohup venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 > /tmp/gunicorn_134.log 2>&1 & disown
sleep 5
echo "new gunicorn pids: $(pgrep -f 'gunicorn archery.wsgi' | head -10)"

# 6. 14 端点 verify
echo ""
echo "[6/6] 14 端点 verify"
for ep in /login/ / /admin/ /dbaprinciples/ /sqlworkflow/ /ddl_sync/ /ddl_sync/pair/list/ /ddl_sync/pair/1/ /ddl_sync/pair/1/compute_diff/ /ddl_sync/pair/1/one_click_setup/ /ddl_sync/pair/1/bulk_import/ /ddl_sync/pair/1/add_table/ /ddl_sync/history/ /static/ddl_sync/pair_detail.js; do
  code=$(curl -sS -m 5 -o /dev/null -w 'HTTP:%{http_code}' "http://127.0.0.1:9003${ep}")
  echo "  $ep -> $code"
done

echo ""
echo "DONE"
