# -*- coding: utf-8 -*-
"""D34 dry-run 演练推 110 prod 9 步 runbook 在 134 dev.

演练覆盖 (134 dev 已经是完整部署, 不动 4 大步):
- Step 1: 4 大步 + D33 view/template/URL 基线确认
- Step 2: dry-run migrate ddl_sync
- Step 3: kill + 拉新 gunicorn + qcluster
- Step 4: 验证 D33 view (reverse() + showmigrations + get_resolver)
- Step 5: 验证 D33 URL (curl /ddl_sync/pair/1/history_export/ + xlsx 下载)

演练目的: D34 推 110 prod 实战 9 步 runbook 验证, 推前必演练 4 大步能 work + D33 视图改动也能 work.
"""
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
        # iconv 转 ascii 防 GBK 编码错误
        out = stdout.read().decode("utf-8", errors="replace")
        try:
            import codecs
            out = out.encode("ascii", "ignore").decode("ascii")
        except Exception:
            pass
        return out
    except Exception as e:
        return f"ERR: {e}"

print("=" * 60)
print("D34 dry-run 演练推 110 prod 9 步 runbook (134 dev)")
print("=" * 60)

# === Step 1: 基线确认 ===
print("\n--- Step 1: 134 dev 4 大步 + D33 改动基线 ---")

# 1.1 ddl_sync/ 目录
out = run('ls -d ' + DEV_BASE + '/sql/extensions/ddl_sync/ && find ' + DEV_BASE + '/sql/extensions/ddl_sync/ -type f | wc -l')
print(f"  ddl_sync 目录文件数: {out.strip().split(chr(10))[-1]}")

# 1.2 settings.py 4 大步
out = run('grep -n "ddl_sync" ' + DEV_BASE + '/archery/settings.py | head -5')
print(f"  settings.py ddl_sync 引用:\n{out.strip()}")

# 1.3 urls.py 4 大步
out = run('grep -n "ddl_sync" ' + DEV_BASE + '/archery/urls.py | head -5')
print(f"  urls.py ddl_sync 路由:\n{out.strip()}")

# 1.4 base.html 4 大步
out = run('grep -n "ddl_sync\\|库对列表" ' + DEV_BASE + '/common/templates/base.html | head -5')
print(f"  base.html ddl_sync menu:\n{out.strip()}")

# 1.5 D33 view (pair_history_export)
out = run('grep -n "pair_history_export\\|Paginator" ' + DEV_BASE + '/sql/extensions/ddl_sync/views/__init__.py | head -10')
print(f"  D33 view 改动:\n{out.strip()}")

# 1.6 D33 URL
out = run('grep -n "history_export" ' + DEV_BASE + '/sql/extensions/ddl_sync/urls.py | head -5')
print(f"  D33 url 改动:\n{out.strip()}")

# 1.7 D33 template (分页 + 导出按钮)
out = run('grep -n "history_page\\|pair_history_export\\|ddlsync-btn-export\\|ddlsync-page-link" ' + DEV_BASE + '/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html | head -10 | iconv -f utf-8 -t ascii//IGNORE')
print(f"  D33 template 改动:\n{out.strip()}")

# === Step 2: dry-run migrate ===
print("\n--- Step 2: dry-run migrate ddl_sync ---")
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py migrate ddl_sync 2>&1 | head -10 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

# === Step 3: kill + 拉新 gunicorn + qcluster ===
print("\n--- Step 3: kill + 拉新 gunicorn + qcluster ---")
run("pkill -9 -f 'gunicorn.*archery.*9003' 2>&1; sleep 2")
run("pkill -9 -f 'manage.py qcluster' 2>&1; sleep 2")
out = run("ps -ef | grep -E 'gunicorn.*9003|manage.py qcluster' | grep -v grep | wc -l")
print(f"  kill 后进程数 (期望 0): {out.strip()}")
out = run('cd ' + DEV_BASE + ' && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn_d34.log 2>&1 & disown')
print(f"  gunicorn 拉新: {out.strip()}")
out = run('cd ' + DEV_BASE + ' && setsid nohup sudo -u archery venv/bin/python manage.py qcluster </dev/null >/var/log/archery/qcluster_d34.log 2>&1 & disown')
print(f"  qcluster 拉新: {out.strip()}")
time.sleep(5)
out = run("ps -ef | grep -E 'gunicorn.*9003|manage.py qcluster' | grep -v grep | wc -l")
print(f"  拉新后进程数 (期望 7+): {out.strip()}")
out = run("ss -tlnp | grep ':9003' 2>&1 | head -1")
print(f"  9003 端口: {out.strip()}")

# === Step 4: 验证 D33 view (reverse + showmigrations + get_resolver) ===
print("\n--- Step 4: 验证 D33 view (reverse + showmigrations + get_resolver) ---")
py_lines = [
    "import os",
    "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archery.settings')",
    "import django; django.setup()",
    "from django.urls import reverse, get_resolver",
    "import re",
    "",
    "# 4.1 reverse 验证 D33 新 view",
    "export_url = reverse('ddl_sync:pair_history_export', args=[1])",
    "print('  reverse pair_history_export:', export_url)",
    "",
    "pair_url = reverse('ddl_sync:pair_detail', args=[1])",
    "print('  reverse pair_detail:', pair_url)",
    "",
    "# 4.2 showmigrations",
    "import subprocess",
    "r = subprocess.run(['venv/bin/python', 'manage.py', 'showmigrations', 'ddl_sync'],",
    "                   capture_output=True, text=True, cwd='/opt/archery/prod', env={**os.environ, 'DJANGO_SETTINGS_MODULE': 'archery.settings'})",
    "out_lines = [l for l in r.stdout.split(chr(10)) if '[X]' in l or '[ ]' in l]",
    "print('  showmigrations ddl_sync:')",
    "for l in out_lines:",
    "    print('   ', l)",
    "",
    "# 4.3 get_resolver walk ddl_sync 路由",
    "def walk(resolver, prefix=''):",
    "    n = 0",
    "    for p in resolver.url_patterns:",
    "        if hasattr(p, 'url_patterns'):",
    "            n += walk(p, prefix + str(p.pattern))",
    "        else:",
    "            full = prefix + str(p.pattern)",
    "            if 'ddl_sync' in full:",
    "                n += 1",
    "    return n",
    "n = walk(get_resolver())",
    "print('  ddl_sync 路由总数:', n)",
    "",
    "# 4.4 D33 view 函数存在性",
    "from sql.extensions.ddl_sync.views import pair_history_export",
    "print('  pair_history_export view callable:', callable(pair_history_export))",
    "import inspect",
    "sig = inspect.signature(pair_history_export)",
    "print('  pair_history_export signature:', sig)",
]
py = '\n'.join(py_lines)
py_b64 = base64.b64encode(py.encode('utf-8')).decode('ascii')
run('echo ' + py_b64 + ' | base64 -d > /tmp/_d34_step4.py')
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d34_step4.py 2>&1 | head -30 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

# === Step 5: 验证 D33 URL (curl /ddl_sync/pair/1/history_export/) ===
print("\n--- Step 5: 验证 D33 URL (curl /ddl_sync/pair/1/history_export/) ---")
# 5.1 未登录 → 302
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/ddl_sync/pair/1/history_export/")
print(f"  未登录访问 (期望 302): {out.strip()}")

# 5.2 模拟登录 + 下载 .xlsx
py_login = """
from django.test import Client
from sql.models import Users
admin = Users.objects.get(username='archery')
c = Client(); c.force_login(admin)
r = c.get('/ddl_sync/pair/1/history_export/', HTTP_HOST='172.20.2.134')
with open('/opt/archery/d34_test.xlsx', 'wb') as f:
    f.write(r.content)
print('  login + export status:', r.status_code)
print('  login + export content-type:', r.get('Content-Type'))
print('  login + export content-disposition:', r.get('Content-Disposition'))
print('  login + export length:', len(r.content))
"""
b = base64.b64encode(py_login.encode('utf-8')).decode('ascii')
run('echo ' + b + ' | base64 -d > /tmp/_d34_step5.py')
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d34_step5.py 2>&1 | head -10 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

# 5.3 openpyxl 解析
out = run('cd /opt/archery/prod && sudo -u archery venv/bin/python -c "from openpyxl import load_workbook; wb = load_workbook(\'/opt/archery/d34_test.xlsx\'); ws = wb.active; print(\'  xlsx rows:\', ws.max_row); print(\'  xlsx headers:\', [ws.cell(1, c).value for c in range(1, ws.max_column+1)])" 2>&1 | head -10 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

# 5.4 清理 .xlsx
run('rm -f /opt/archery/d34_test.xlsx')

ssh.close()
