# -*- coding: utf-8 -*-
"""D32 Step 5b: 演练 2 用 reverse() 验证 ddl_sync 路由 + 找业务方账号."""
import paramiko

DEV = "172.20.2.134"
PWD = "lAqfb8uEmQYsnGNQwIHtGPwukjCz6J"
DEV_BASE = "/opt/archery/prod"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(hostname=DEV, port=22, username="root", password=PWD, timeout=15)

def run(cmd, timeout=20):
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        return out
    except Exception as e:
        return f"ERR: {e}"

print("=" * 60)
print("D32 Step 5b: 演练 2 reverse() 验证 + 找业务方账号")
print("=" * 60)

# 1. reverse() 验证 ddl_sync 路由已注册
print("\n--- Step 1: reverse() 验证 ddl_sync 路由 ---")
py = '''
from django.urls import reverse, NoReverseMatch
try:
    url = reverse("ddl_sync:pair_list")
    print(f"reverse OK: {url}")
except NoReverseMatch as e:
    print(f"reverse FAIL: {e}")
'''
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c '" + py + "' 2>&1 | tail -3")
print(out)

# 2. 看 ddl_sync.urls 路由列表
print("\n--- Step 2: ddl_sync.urls 路由列表 ---")
py2 = '''
from django.urls import get_resolver
def walk(resolver, prefix=""):
    for p in resolver.url_patterns:
        if hasattr(p, "url_patterns"):
            walk(p, prefix + str(p.pattern))
        else:
            full = prefix + str(p.pattern)
            if "ddl_sync" in full:
                print(full)
walk(get_resolver())
'''
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c '" + py2 + "' 2>&1 | tail -20")
print(out)

# 3. 找业务方账号
print("\n--- Step 3: 业务方账号 ---")
py3 = '''
from sql.models import Users
# 看 dba 账号
dba_users = Users.objects.filter(role="DBA")[:5]
for u in dba_users:
    print(f"DBA: {u.username} (super={u.is_superuser}, staff={u.is_staff})")
# 看 superuser
su = Users.objects.filter(is_superuser=True)[:5]
for u in su:
    print(f"SU: {u.username}")
'''
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c '" + py3 + "' 2>&1 | tail -10")
print(out)

# 4. 用 admin/archery 重新登录 (debug 一下登录是不是真的成功)
print("\n--- Step 4: admin/archery 登录 debug ---")
py4 = '''
import urllib.request, urllib.parse, http.cookiejar, re

BASE = "http://127.0.0.1:9003"
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), urllib.request.HTTPRedirectHandler())

# 1. GET /login/ 拿 csrf
r = opener.open(BASE + "/login/")
html = r.read().decode("utf-8", errors="replace")
m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
csrf = m.group(1) if m else ""
print(f"CSRF: {csrf[:20]}")

# 2. POST /login/
data = urllib.parse.urlencode({
    "csrfmiddlewaretoken": csrf,
    "username": "admin",
    "password": "archery",
}).encode()
r = opener.open(BASE + "/login/", data)
print(f"login status: {r.status}, url: {r.url}")
# 看 cookies
for c in cj:
    print(f"  cookie: {c.name}={c.value[:20]}")

# 3. GET /ddl_sync/pair/
r2 = opener.open(BASE + "/ddl_sync/pair/")
html2 = r2.read().decode("utf-8", errors="replace")
print(f"/ddl_sync/pair/ status: {r2.status}, url: {r2.url}, len: {len(html2)}")
# 看 title
m2 = re.search(r"<title>([^<]+)</title>", html2)
if m2:
    print(f"title: {m2.group(1)}")
# 看 base.html menu 是否有 ddl_sync
print(f"contains 库对列表: {('库对列表' in html2)}")
print(f"contains DDL 跨库同步: {('DDL 跨库同步' in html2)}")
print(f"contains pair_list url: {('ddl_sync/pair/' in html2)}")
'''
import base64
py4_b64 = base64.b64encode(py4.encode('utf-8')).decode('ascii')
out = run('echo ' + py4_b64 + ' | base64 -d > /tmp/_d32_login_debug.py && python3 /tmp/_d32_login_debug.py 2>&1')
print(out)

ssh.close()
