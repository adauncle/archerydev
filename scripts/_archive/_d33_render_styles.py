# -*- coding: utf-8 -*-
"""D33 render 检查 .tab-pane 4 个的实际 style."""
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

py_lines = [
    "import os",
    "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archery.settings')",
    "import django; django.setup()",
    "from django.test import Client",
    "from sql.models import Users",
    "import re",
    "",
    "admin = Users.objects.get(username='archery')",
    "c = Client(); c.force_login(admin)",
    "r = c.get('/ddl_sync/pair/1/', HTTP_HOST='172.20.2.134')",
    "html = r.content.decode('utf-8', errors='replace')",
    "",
    "# 找 4 个 tab-pane 开头的 div",
    "for tab_id in ['tab-basic', 'tab-tables', 'tab-history', 'tab-logs']:",
    "    pat = r'<div class=\"([^\"]*)\" id=\"' + tab_id + r'\"([^>]*)>'",
    "    m = re.search(pat, html)",
    "    if m:",
    "        cls = m.group(1)",
    "        extra = m.group(2)",
    "        print(tab_id, ' class=[' + cls + '] extra=[' + extra + ']')",
    "    else:",
    "        print(tab_id, 'NOT FOUND')",
    "",
    "# 看页面里 .tab-pane 提到多少次",
    "print('---')",
    "print('tab-pane occurrences:', html.count('class=\"tab-pane'))",
    "print('display: none occurrences:', html.count('display: none'))",
    "print('inline style in tab-content area:')",
    "m = re.search(r'<div class=\"tab-content\">(.{0,500})', html, re.DOTALL)",
    "if m:",
    "    print(m.group(1)[:500])",
    "",
    "# 找 ddlsync-tab-pane 的 inline style",
    "print('---')",
    "for m in re.finditer(r'<div class=\"ddlsync-tab-pane\"([^>]*)>', html):",
    "    print('ddlsync-tab-pane extra:', m.group(1))",
]

py = '\n'.join(py_lines)
py_b64 = base64.b64encode(py.encode('utf-8')).decode('ascii')
run('echo ' + py_b64 + ' | base64 -d > /tmp/_d33_styles.py')
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d33_styles.py 2>&1 | head -50 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

ssh.close()
