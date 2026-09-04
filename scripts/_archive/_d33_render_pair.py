# -*- coding: utf-8 -*-
"""D33 render pair_detail.html via Django shell - 看实际 HTML + 找空白."""
import paramiko

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

# 1. 用 Django shell 直接渲染模板 + 看 tab-content 内的 4 个 tab-pane 是否都显示
print("=" * 60)
print("D33 render pair_detail.html via Django shell")
print("=" * 60)

py = '''
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()

from django.template.loader import get_template
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser
from sql.models import Users

# 1. 拿 pair 1
from sql.extensions.ddl_sync.models import DdlSyncPair
pair = DdlSyncPair.objects.get(id=1)
print(f"pair: {pair.name}")

# 2. 渲染模板 (用 superuser admin)
try:
    admin = Users.objects.get(username="admin")
except:
    admin = Users.objects.filter(is_superuser=True).first()
print(f"user: {admin.username if admin else None}")

# 3. 用 Django test client 模拟请求
from django.test import Client
c = Client()
c.force_login(admin) if admin else None
r = c.get("/ddl_sync/pair/1/", HTTP_HOST="172.20.2.134")
print(f"status: {r.status_code}")
print(f"content length: {len(r.content)}")

# 4. 看 tab-content 内的 4 个 tab-pane
import re
html = r.content.decode("utf-8", errors="replace")

# 找 tab-content 块
m = re.search(r\'<div class="tab-content">(.*?)(?=<div class="modal|<div id="modal|<!-- 3 modal|\\{% include)\', html, re.DOTALL)
if m:
    snippet = m.group(1)
    print(f"\\ntab-content length: {len(snippet)}")
    # 提取 4 个 tab-pane 的开头
    for tab_id in ["tab-basic", "tab-tables", "tab-history", "tab-logs"]:
        m2 = re.search(rf\'(<div class="[^"]*" id="{tab_id}">)\', snippet)
        if m2:
            print(f"  {tab_id}: {m2.group(1)}")
    # 找 tab-content 末尾 + 之后的内容
    after = html[m.end():m.end()+500]
    print(f"\\ntab-content 之后 500 字符: {after}")
else:
    print("没找到 tab-content 块")
    # 退而求其次: 找 4 个 tab-pane
    for tab_id in ["tab-basic", "tab-tables", "tab-history", "tab-logs"]:
        m = re.search(rf\'<div class="([^"]*)" id="{tab_id}">\', html)
        if m:
            print(f"  {tab_id} class: {m.group(1)}")
        else:
            print(f"  {tab_id} NOT FOUND")
'''

# 上传并执行
import base64
py_b64 = base64.b64encode(py.encode('utf-8')).decode('ascii')
out = run('echo ' + py_b64 + ' | base64 -d > /tmp/_d33_render.py')
print(f"upload: {out.strip()}")

# 用 django_q shell 环境跑
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell < /tmp/_d33_render.py 2>&1 | head -80 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

ssh.close()
