# -*- coding: utf-8 -*-
"""D33 test pagination v2: base64 整段传输避免嵌套引号."""
import paramiko
import base64

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
        return out
    except Exception as e:
        return f"ERR: {e}"

# Step 1: 当前 count
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell -c "from sql.extensions.ddl_sync.models import DdlSyncHistory; print(DdlSyncHistory.objects.count())" 2>&1 | tail -3 | iconv -f utf-8 -t ascii//IGNORE')
print(f"Step 1 - 当前 count: {out.strip()}")

# Step 2: 造 5 条 (用 get_or_create 拿 source_workflow + target_workflow)
py2 = """
from sql.extensions.ddl_sync.models import DdlSyncPair, DdlSyncHistory
from sql.models import SqlWorkflow
from django.utils import timezone
import datetime
pair = DdlSyncPair.objects.get(id=1)
# 拿一个现有 source_workflow
src_wf = DdlSyncHistory.objects.exclude(source_workflow__isnull=True).first()
if not src_wf:
    print('No source_workflow to clone - abort')
else:
    src = src_wf.source_workflow
    for i in range(5):
        h = DdlSyncHistory.objects.create(
            pair=pair,
            source_workflow=src,
            table_name='_d33_test_pagination_' + str(i),
            sync_status='synced',
            created_at=timezone.now() - datetime.timedelta(minutes=i),
            finished_at=timezone.now() - datetime.timedelta(minutes=i),
        )
        print('created:', h.id)
    print('new count:', DdlSyncHistory.objects.count())
"""
b2 = base64.b64encode(py2.encode('utf-8')).decode('ascii')
run('echo ' + b2 + ' | base64 -d > /tmp/_d33_p2.py')
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d33_p2.py 2>&1 | tail -10 | iconv -f utf-8 -t ascii//IGNORE')
print(f"\nStep 2 - 造 5 条: {out.strip()}")

# Step 3: 验证分页
py3 = """
from django.test import Client
from sql.models import Users
admin = Users.objects.get(username='archery')
c = Client(); c.force_login(admin)
r = c.get('/ddl_sync/pair/1/', HTTP_HOST='172.20.2.134')
html = r.content.decode('utf-8', errors='replace')
print('status:', r.status_code, 'len:', len(r.content))
print('has history_page link:', 'history_page=' in html)
print('has history_page=2 link:', 'history_page=2' in html)
print('has page current class:', 'ddlsync-page-current' in html)
print('has 1/2 text:', '1/2' in html or '第 1/' in html)
"""
b3 = base64.b64encode(py3.encode('utf-8')).decode('ascii')
run('echo ' + b3 + ' | base64 -d > /tmp/_d33_p3.py')
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d33_p3.py 2>&1 | tail -10 | iconv -f utf-8 -t ascii//IGNORE')
print(f"\nStep 3 - 验证分页: {out.strip()}")

# Step 4: 测 page 2
py4 = """
from django.test import Client
from sql.models import Users
admin = Users.objects.get(username='archery')
c = Client(); c.force_login(admin)
r = c.get('/ddl_sync/pair/1/?history_page=2', HTTP_HOST='172.20.2.134')
html = r.content.decode('utf-8', errors='replace')
print('page 2 status:', r.status_code, 'len:', len(r.content))
print('has _d33_test_pagination_:', '_d33_test_pagination_' in html)
import re
ms = re.findall(r'_d33_test_pagination_(\\d+)', html)
print('test entries in page 2:', ms)
"""
b4 = base64.b64encode(py4.encode('utf-8')).decode('ascii')
run('echo ' + b4 + ' | base64 -d > /tmp/_d33_p4.py')
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d33_p4.py 2>&1 | tail -10 | iconv -f utf-8 -t ascii//IGNORE')
print(f"\nStep 4 - 测 page 2: {out.strip()}")

# Step 5: 导出
py5 = """
from django.test import Client
from sql.models import Users
admin = Users.objects.get(username='archery')
c = Client(); c.force_login(admin)
r = c.get('/ddl_sync/pair/1/history_export/', HTTP_HOST='172.20.2.134')
with open('/opt/archery/d33_test.xlsx', 'wb') as f:
    f.write(r.content)
print('status:', r.status_code, 'len:', len(r.content))
print('content-type:', r.get('Content-Type'))
"""
b5 = base64.b64encode(py5.encode('utf-8')).decode('ascii')
run('echo ' + b5 + ' | base64 -d > /tmp/_d33_p5.py')
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d33_p5.py 2>&1 | tail -5 | iconv -f utf-8 -t ascii//IGNORE')
print(f"\nStep 5 - 导出: {out.strip()}")

# Step 6: 解析 xlsx
out = run('cd /opt/archery/prod && sudo -u archery venv/bin/python -c "from openpyxl import load_workbook; wb = load_workbook(\'/opt/archery/d33_test.xlsx\'); ws = wb.active; print(\'rows:\', ws.max_row); print(\'headers:\', [c.value for c in ws[1]]); print(\'row 2:\', [c.value for c in ws[2]])" 2>&1 | head -10 | iconv -f utf-8 -t ascii//IGNORE')
print(f"\nStep 6 - 解析 xlsx: {out.strip()}")

# Step 7: 清理
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c \"from sql.extensions.ddl_sync.models import DdlSyncHistory; n = DdlSyncHistory.objects.filter(table_name__startswith='_d33_test_pagination_').delete(); print('deleted:', n); print('count after:', DdlSyncHistory.objects.count())\" 2>&1 | tail -5 | iconv -f utf-8 -t ascii//IGNORE")
print(f"\nStep 7 - 清理: {out.strip()}")

run('rm -f /opt/archery/d33_test.xlsx')
print("\nfile cleanup OK")

ssh.close()
