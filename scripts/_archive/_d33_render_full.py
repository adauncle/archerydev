# -*- coding: utf-8 -*-
"""D33 render full tab-content 找空白根因."""
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

py = '''
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()
from django.test import Client
from sql.models import Users
import re

# 1. 拿 admin 用户
admin = Users.objects.get(username="archery")

# 2. 渲染 pair/1/
c = Client()
c.force_login(admin)
r = c.get("/ddl_sync/pair/1/", HTTP_HOST="172.20.2.134")
print(f"status: {r.status_code}, length: {len(r.content)}")
html = r.content.decode("utf-8", errors="replace")

# 3. 提取 tab-content 块
m = re.search(r\'<div class="tab-content">(.*?)(?=<!-- 3 modal include)\', html, re.DOTALL)
if not m:
    print("NO tab-content found")
    import sys; sys.exit(1)
tc = m.group(1)
print(f"\\ntab-content length: {len(tc)}")

# 4. 4 个 tab-pane 顺序提取 + 内容长度
for tab_id in ["tab-basic", "tab-tables", "tab-history", "tab-logs"]:
    pattern = rf\'<div class="[^"]*" id="{tab_id}">(.*?)(?=<div class="[^"]*" id="tab-|<div class="modal-fade"|\\s*</div>\\s*<!-- tab \\d|$)\'
    # 简化: 找 tab-pane 开头到下一个 tab-pane 开头
    idx = tc.find(f\'id="{tab_id}"\')
    if idx < 0:
        print(f"  {tab_id}: NOT FOUND")
        continue
    # 找结束位置 (下一个 <div class="tab-pane" 或 <div class="modal" 或 tab-content 结束)
    start = tc.rfind("<div", 0, idx)
    # 找下一个 id="tab-
    end_pat = re.search(r\'<div class="[^"]*" id="tab-\', tc[idx+10:])
    end = (idx + 10 + end_pat.start()) if end_pat else len(tc)
    content = tc[start:end]
    print(f"  {tab_id}: length={len(content)}, h5={re.findall(r\\\'<h5>([^<]+)</h5>\\\', content)[:1]}, first 100={content[:100]!r}")

# 5. 看 nav-tabs 4 个 tab 哪个 active
print("\\nnav-tabs analysis:")
nav_match = re.search(r\'<ul class="nav nav-tabs"[^>]*>(.*?)</ul>\', html, re.DOTALL)
if nav_match:
    nav = nav_match.group(1)
    for li in re.findall(r\'<li[^>]*>(.*?)</li>\', nav, re.DOTALL):
        a = re.search(r\'<a[^>]*class="([^"]*)"[^>]*>([^<]+)\', li)
        if a:
            print(f"  tab: class={a.group(1)}, text={a.group(2)}")
'''

py_b64 = base64.b64encode(py.encode('utf-8')).decode('ascii')
run('echo ' + py_b64 + ' | base64 -d > /tmp/_d33_render_full.py')
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d33_render_full.py 2>&1 | head -50 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

ssh.close()
