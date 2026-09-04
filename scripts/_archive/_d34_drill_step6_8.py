# -*- coding: utf-8 -*-
"""D34 dry-run Step 6-8: 造临时 history 验证分页 + 清理 + 验证 134 dev 业务不中断."""
import paramiko
import base64
import time

DEV = "172.20.2.134"
PWD = "lAqfb8uEmQYsnGNQwIHtGPwukjCz6J"
DEV_BASE = "/opt/archery/prod"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(hostname=DEV, port=22, username="root", password=PWD, timeout=15)

def run(cmd, timeout=30):
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        try:
            out = out.encode("ascii", "ignore").decode("ascii")
        except Exception:
            pass
        return out
    except Exception as e:
        return f"ERR: {e}"

print("=" * 60)
print("D34 dry-run Step 6-8: 造临时 history 验证分页 + 清理")
print("=" * 60)

# === Step 6: 造 5 条临时 history ===
print("\n--- Step 6: 造 5 条临时 history ---")
py_create = """
from sql.extensions.ddl_sync.models import DdlSyncPair, DdlSyncHistory
from django.utils import timezone
import datetime
pair = DdlSyncPair.objects.get(id=1)
src_wf = DdlSyncHistory.objects.exclude(source_workflow__isnull=True).first().source_workflow
for i in range(5):
    h = DdlSyncHistory.objects.create(
        pair=pair,
        source_workflow=src_wf,
        table_name='_d34_drill_' + str(i),
        sync_status='synced',
        created_at=timezone.now() - datetime.timedelta(minutes=i),
        finished_at=timezone.now() - datetime.timedelta(minutes=i),
    )
    print('created:', h.id)
print('new count:', DdlSyncHistory.objects.count())
"""
b = base64.b64encode(py_create.encode('utf-8')).decode('ascii')
run('echo ' + b + ' | base64 -d > /tmp/_d34_step6.py')
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d34_step6.py 2>&1 | head -10 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

# === Step 7: 验证分页 + 导出 ===
print("\n--- Step 7: 验证 21 条 → 2 页 + 导出全部 21 条 ---")
py_verify = """
from django.test import Client
from sql.models import Users
from django.urls import reverse

admin = Users.objects.get(username='archery')
c = Client(); c.force_login(admin)

# 7.1 page 1
r1 = c.get('/ddl_sync/pair/1/', HTTP_HOST='172.20.2.134')
html1 = r1.content.decode('utf-8', errors='replace')
print('  page 1 status:', r1.status_code, 'len:', len(r1.content))
print('  page 1 has history_page link:', 'history_page=' in html1)
print('  page 1 has history_page=2 link:', 'history_page=2' in html1)
print('  page 1 has 1/2 text:', '1/2' in html1)

# 7.2 page 2
r2 = c.get('/ddl_sync/pair/1/?history_page=2', HTTP_HOST='172.20.2.134')
html2 = r2.content.decode('utf-8', errors='replace')
print('  page 2 status:', r2.status_code, 'len:', len(r2.content))
print('  page 2 has _d34_drill_ entries:', '_d34_drill_' in html2)
import re
ms = re.findall(r'_d34_drill_(\\d+)', html2)
print('  page 2 d34_drill entries:', ms)

# 7.3 导出 21 条
r3 = c.get('/ddl_sync/pair/1/history_export/', HTTP_HOST='172.20.2.134')
with open('/opt/archery/d34_step7.xlsx', 'wb') as f:
    f.write(r3.content)
print('  export status:', r3.status_code, 'len:', len(r3.content))
print('  export content-type:', r3.get('Content-Type'))
print('  export content-disposition:', r3.get('Content-Disposition'))
"""
b = base64.b64encode(py_verify.encode('utf-8')).decode('ascii')
run('echo ' + b + ' | base64 -d > /tmp/_d34_step7.py')
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d34_step7.py 2>&1 | head -20 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

# 7.4 openpyxl 解析 21 条 .xlsx
out = run('cd /opt/archery/prod && sudo -u archery venv/bin/python -c "from openpyxl import load_workbook; wb = load_workbook(\'/opt/archery/d34_step7.xlsx\'); ws = wb.active; print(\'  xlsx rows (1 + 21 data):\', ws.max_row); print(\'  xlsx last row id:\', ws.cell(ws.max_row, 1).value, \'/ table:\', ws.cell(ws.max_row, 2).value)" 2>&1 | head -5 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

# === Step 7.5: 清理临时 5 条 history + .xlsx ===
print("\n--- Step 7.5: 清理 ---")
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c \"from sql.extensions.ddl_sync.models import DdlSyncHistory; n = DdlSyncHistory.objects.filter(table_name__startswith='_d34_drill_').delete(); print('deleted:', n); print('count after:', DdlSyncHistory.objects.count())\" 2>&1 | tail -3 | iconv -f utf-8 -t ascii//IGNORE")
print(out)
run('rm -f /opt/archery/d34_step7.xlsx')
print("  xlsx file cleaned")

# === Step 8: 验证 134 dev 业务不中断 ===
print("\n--- Step 8: 验证 134 dev 业务不中断 (拉新后 < 1 分钟业务恢复) ---")
# 8.1 拉新后业务可访问
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/login/")
print(f"  /login/ status (期望 200): {out.strip()}")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/ddl_sync/pair/")
print(f"  /ddl_sync/pair/ status (期望 302): {out.strip()}")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/ddl_sync/pair/1/history_export/")
print(f"  /ddl_sync/pair/1/history_export/ status (期望 302): {out.strip()}")

# 8.2 4 大步状态完全恢复
out = run('grep -c "ddl_sync" ' + DEV_BASE + '/archery/settings.py ' + DEV_BASE + '/archery/urls.py ' + DEV_BASE + '/common/templates/base.html | head -3')
print(f"  4 大步 ddl_sync 引用数: {out.strip()}")

# 8.3 D33 改动全在
out = run('grep -c "pair_history_export\\|Paginator\\|ddlsync-btn-export\\|ddlsync-page-link" ' + DEV_BASE + '/sql/extensions/ddl_sync/views/__init__.py ' + DEV_BASE + '/sql/extensions/ddl_sync/urls.py ' + DEV_BASE + '/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html | head -3')
print(f"  D33 改动在 3 文件数: {out.strip()}")

# 8.4 进程数
out = run("ps -ef | grep -E 'gunicorn.*9003|manage.py qcluster' | grep -v grep | wc -l")
print(f"  gunicorn+qcluster 进程数 (期望 7+): {out.strip()}")

# 8.5 showmigrations 最终
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py showmigrations ddl_sync 2>&1 | tail -5 | iconv -f utf-8 -t ascii//IGNORE')
print(f"  showmigrations:\n{out.strip()}")

ssh.close()
