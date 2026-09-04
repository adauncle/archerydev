# -*- coding: utf-8 -*-
"""D33 push pair_detail.html fix to 134 dev + 验证渲染."""
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

print("=" * 60)
print("D33 push pair_detail.html fix to 134 dev")
print("=" * 60)

# 1. scp 本地 pair_detail.html 到 134 dev
print("\n--- Step 1: scp pair_detail.html ---")
import os
LOCAL = r"G:\MiniMax工作空间\archery_dev\sql\extensions\ddl_sync\templates\ddl_sync\pair_detail.html"
out = run('ls -la ' + LOCAL.replace('\\', '/').replace('G:/', '/tmp/'))
print(out)

# 用 sftp
sftp = ssh.open_sftp()
sftp.put(LOCAL, '/tmp/_pair_detail_d33.html')
sftp.close()
out = run('ls -la /tmp/_pair_detail_d33.html 2>&1')
print(out)

# 2. 备份原文件
print("\n--- Step 2: 备份原文件 ---")
out = run('cp -v ' + DEV_BASE + '/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html ' + DEV_BASE + '/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html.bak_d33')
print(out)

# 3. 覆盖
print("\n--- Step 3: 覆盖新文件 ---")
out = run('cp -v /tmp/_pair_detail_d33.html ' + DEV_BASE + '/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html')
print(out)

# 4. 清 pycache
print("\n--- Step 4: 清 pycache ---")
out = run('find ' + DEV_BASE + ' -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null && find ' + DEV_BASE + ' -name "*.pyc" -delete 2>/dev/null && echo pycache cleared')
print(out)

# 5. kill + 拉新 gunicorn
print("\n--- Step 5: kill + 拉新 gunicorn ---")
run("pkill -9 -f 'gunicorn.*archery.*9003' 2>&1; sleep 2")
out = run("ps -ef | grep -E 'gunicorn.*9003' | grep -v grep | wc -l")
print(f"kill 后 gunicorn 进程数 (期望 0): {out.strip()}")
import time
out = run('cd ' + DEV_BASE + ' && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn_d33.log 2>&1 & disown')
print(f"gunicorn 拉新: {out.strip()}")
time.sleep(5)
out = run("ps -ef | grep -E 'gunicorn.*9003' | grep -v grep | wc -l")
print(f"gunicorn 进程数 (期望 5): {out.strip()}")

# 6. 验证渲染
print("\n--- Step 6: 验证 pair/1/ 渲染 ---")
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
    "# 找 ddlsync-basic-grid 是否出现",
    "print('has ddlsync-basic-grid:', 'ddlsync-basic-grid' in html)",
    "print('has tab-pane:not(.active): NO inline check needed')",
    "print('tab-pane count:', html.count('class=\"tab-pane'))",
    "print('display: none inline count:', html.count('display: none'))",
    "",
    "# 找 tab-content 内的 4 tab 起始",
    "m = re.search(r'<div class=\"tab-content\">(.*?)(?=<!-- 3 modal)', html, re.DOTALL)",
    "if m:",
    "    tc = m.group(1)",
    "    for tab_id in ['tab-basic', 'tab-tables', 'tab-history', 'tab-logs']:",
    "        idx = tc.find('id=\"' + tab_id + '\"')",
    "        if idx < 0:",
    "            print(tab_id, 'NOT FOUND'); continue",
    "        start = tc.rfind('<div', 0, idx)",
    "        end_pat = re.search(r'<div class=\"[^\"]*\" id=\"tab-', tc[idx+10:])",
    "        end = (idx + 10 + end_pat.start()) if end_pat else len(tc)",
    "        content = tc[start:end]",
    "        print(tab_id, 'len=', len(content))",
    "",
    "# 看 tab-basic 的 grid",
    "m = re.search(r'id=\"tab-basic\".*?<div class=\"ddlsync-basic-grid\">(.*?)</div>\\s*</div>\\s*</div>', html, re.DOTALL)",
    "if m:",
    "    print('grid content len:', len(m.group(1)))",
    "    print('grid divs:', m.group(1).count('<div'))",
]
py = '\n'.join(py_lines)
py_b64 = base64.b64encode(py.encode('utf-8')).decode('ascii')
run('echo ' + py_b64 + ' | base64 -d > /tmp/_d33_verify.py')
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d33_verify.py 2>&1 | head -30 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

# 7. curl /ddl_sync/pair/1/ 看 HTTP
print("\n--- Step 7: curl ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/ddl_sync/pair/1/")
print(f"HTTP: {out.strip()}")

ssh.close()
