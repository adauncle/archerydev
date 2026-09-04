# -*- coding: utf-8 -*-
"""D33 render full tab-content 找空白根因 v2."""
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

# 用 base64 + 不带 backslash 的版本
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
    "print('status:', r.status_code, 'length:', len(r.content))",
    "html = r.content.decode('utf-8', errors='replace')",
    "",
    "# tab-content 块",
    "m = re.search(r'<div class=\"tab-content\">(.*?)(?=<!-- 3 modal include)', html, re.DOTALL)",
    "tc = m.group(1) if m else ''",
    "print('tab-content length:', len(tc))",
    "",
    "# 4 个 tab-pane 内容长度",
    "for tab_id in ['tab-basic', 'tab-tables', 'tab-history', 'tab-logs']:",
    "    idx = tc.find('id=\"' + tab_id + '\"')",
    "    if idx < 0: print(tab_id, 'NOT FOUND'); continue",
    "    start = tc.rfind('<div', 0, idx)",
    "    end_pat = re.search(r'<div class=\"[^\"]*\" id=\"tab-', tc[idx+10:])",
    "    end = (idx + 10 + end_pat.start()) if end_pat else len(tc)",
    "    content = tc[start:end]",
    "    h5_pat = '<h5>'",
    "    h5s = []",
    "    h5_idx = content.find(h5_pat)",
    "    while h5_idx >= 0:",
    "        end_idx = content.find('</h5>', h5_idx)",
    "        if end_idx < 0: break",
    "        h5s.append(content[h5_idx+4:end_idx])",
    "        h5_idx = content.find(h5_pat, end_idx)",
    "    print(tab_id, ': len=', len(content), 'h5=', h5s[:1])",
    "",
    "# nav-tabs 4 个哪个 active",
    "print('---')",
    "nav_match = re.search(r'<ul class=\"nav nav-tabs\"[^>]*>(.*?)</ul>', html, re.DOTALL)",
    "if nav_match:",
    "    nav = nav_match.group(1)",
    "    for li in re.findall(r'<li[^>]*>(.*?)</li>', nav, re.DOTALL):",
    "        a = re.search(r'<a[^>]*class=\"([^\"]*)\"[^>]*>([^<]+)', li)",
    "        if a:",
    "            print('tab:', a.group(1), '|', a.group(2))",
    "",
    "# 看 4 个 tab-pane 的开头 (class + 头 200 字符)",
    "print('---')",
    "for tab_id in ['tab-basic', 'tab-tables', 'tab-history', 'tab-logs']:",
    "    idx = tc.find('id=\"' + tab_id + '\"')",
    "    if idx < 0: continue",
    "    start = tc.rfind('<div', 0, idx)",
    "    print(tab_id, ' starts at offset', start, 'within tab-content')",
    "",
    "# 看 tab-content 头 200 字符",
    "print('---')",
    "print('tab-content first 200 chars:'); print(tc[:200])",
]

py = '\n'.join(py_lines)
py_b64 = base64.b64encode(py.encode('utf-8')).decode('ascii')
run('echo ' + py_b64 + ' | base64 -d > /tmp/_d33_full.py')
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d33_full.py 2>&1 | head -50 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

ssh.close()
