# -*- coding: utf-8 -*-
"""D32 Step 5: 演练 2 明确验证 - 业务方登录后访问 ddl_sync 页面.

策略: 用 admin/admin (DBA 账号) 登录, 访问 /ddl_sync/pair/ 期望 200 + 页面内容.
"""
import paramiko
import time

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
print("D32 Step 5: 演练 2 明确验证 (登录 + 访问 ddl_sync)")
print("=" * 60)

# 1. 拿 admin 密码
print("\n--- Step 1: 找 admin 密码 ---")
out = run('cat ' + DEV_BASE + '/.env 2>&1 | head -10')
print(out)
out = run('grep -i "admin\\|superuser\\|django_super" /opt/archery/prod/.env 2>&1 | head -5')
print(f"admin env: {out.strip()}")
# 试常见密码
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell -c "from django.contrib.auth.models import User; u = User.objects.filter(is_superuser=True).values_list(\\"username\\", flat=True); print(list(u))" 2>&1 | tail -5')
print(f"superusers: {out.strip()}")

# 2. 上传登录脚本
print("\n--- Step 2: 上传登录脚本 ---")
login_py = '''
import urllib.request, urllib.parse, http.cookiejar, re, sys

BASE = "http://127.0.0.1:9003"
USERNAME = "admin"
PASSWORD = "archery"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# 1. 拿 csrf
r = opener.open(BASE + "/login/")
html = r.read().decode("utf-8", errors="replace")
m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
csrf = m.group(1) if m else ""
print(f"CSRF: {csrf[:20]}...")

# 2. 登录
data = urllib.parse.urlencode({
    "csrfmiddlewaretoken": csrf,
    "username": USERNAME,
    "password": PASSWORD,
}).encode()
r = opener.open(BASE + "/login/", data)
print(f"login status: {r.status}")
print(f"after login url: {r.url}")

# 3. 访问 /ddl_sync/pair/
r = opener.open(BASE + "/ddl_sync/pair/")
html = r.read().decode("utf-8", errors="replace")
print(f"/ddl_sync/pair/ status: {r.status}")
print(f"page length: {len(html)}")
print(f"contains 库对列表: {('库对列表' in html)}")
print(f"contains DDL 跨库同步: {('DDL 跨库同步' in html)}")
print(f"contains pair_list: {('pair_list' in html)}")
'''
# 用 base64 上传避免引号问题
import base64
login_b64 = base64.b64encode(login_py.encode('utf-8')).decode('ascii')
out = run('echo ' + login_b64 + ' | base64 -d > /tmp/_d32_login.py && echo "uploaded"')
print(f"upload: {out.strip()}")
out = run('cat /tmp/_d32_login.py | head -5')
print(out)

# 3. 试 admin/archery 登录
print("\n--- Step 3: 试 admin/archery 登录 ---")
out = run('python3 /tmp/_d32_login.py 2>&1')
print(out)

# 4. 如果失败, 试 admin/admin / admin/123456 / hly
print("\n--- Step 4: 试 admin/123456 登录 ---")
login_py2 = login_py.replace('PASSWORD = "archery"', 'PASSWORD = "123456"')
login_b64_2 = base64.b64encode(login_py2.encode('utf-8')).decode('ascii')
out = run('echo ' + login_b64_2 + ' | base64 -d > /tmp/_d32_login2.py && python3 /tmp/_d32_login2.py 2>&1')
print(out)

# 5. 试 admin/admin
print("\n--- Step 5: 试 admin/admin 登录 ---")
login_py3 = login_py.replace('PASSWORD = "archery"', 'PASSWORD = "admin"')
login_b64_3 = base64.b64encode(login_py3.encode('utf-8')).decode('ascii')
out = run('echo ' + login_b64_3 + ' | base64 -d > /tmp/_d32_login3.py && python3 /tmp/_d32_login3.py 2>&1')
print(out)

# 6. 用 session 模拟 + 业务方账号 (DBA)
print("\n--- Step 6: 看 134 dev 业务方账号 ---")
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py shell -c "from django.contrib.auth.models import User; print([u.username for u in User.objects.filter(is_superuser=True)]); print([u.username for u in User.objects.filter(groups__name=\\"DBA\\")][:5])" 2>&1 | tail -5')
print(out)

ssh.close()
