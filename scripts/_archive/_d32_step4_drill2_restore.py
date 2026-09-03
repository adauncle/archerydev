# -*- coding: utf-8 -*-
"""D32 Step 4: 演练 2 恢复状态 - 还原 3 文件 + migrate + kill + 拉新 + 验证.

演练 2 期望:
- /ddl_sync/pair/ -> 302 (中间件重定向到登录, 证明 ddl_sync 路由已注册)
- /login/ -> 200
- showmigrations ddl_sync -> 2 migrations [X]
- ddl_sync menu 可见 (admin 登录后)

实际验证: 用 curl 带 session 登录, 访问 /ddl_sync/pair/ 期望 200 (业务方登录后看到页面)
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
print("D32 Step 4: 演练 2 恢复状态")
print("=" * 60)

# 1. 还原 3 文件 (从 .bak_d32)
print("\n--- Step 1: 还原 3 文件 ---")
run('cp ' + DEV_BASE + '/archery/settings.py.bak_d32 ' + DEV_BASE + '/archery/settings.py')
run('cp ' + DEV_BASE + '/archery/urls.py.bak_d32 ' + DEV_BASE + '/archery/urls.py')
run('cp ' + DEV_BASE + '/common/templates/base.html.bak_d32 ' + DEV_BASE + '/common/templates/base.html')
out = run('grep -c "D32DRILL1" ' + DEV_BASE + '/archery/settings.py ' + DEV_BASE + '/archery/urls.py ' + DEV_BASE + '/common/templates/base.html')
print(f"D32DRILL1 标记数 (期望 0): {out.strip()}")

# 2. 验证还原后状态
print("\n--- Step 2: 验证还原 ---")
out = run('grep -n "if CUSTOM_DDL_SYNC_ENABLED\\|INSTALLED_APPS.*ddl_sync" ' + DEV_BASE + '/archery/settings.py | head -3')
print(f"settings.py: {out.strip()}")
out = run('grep -n "if getattr.*CUSTOM_DDL_SYNC\\|ddl_sync/" ' + DEV_BASE + '/archery/urls.py | head -3')
print(f"urls.py: {out.strip()}")
out = run('grep -n "ddl_sync.view_ddlsyncpair\\|库对列表" ' + DEV_BASE + '/common/templates/base.html | head -3')
print(f"base.html: {out.strip()}")

# 3. 清 pycache
print("\n--- Step 3: 清 pycache ---")
run('find ' + DEV_BASE + ' -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null')
run('find ' + DEV_BASE + ' -name "*.pyc" -delete 2>/dev/null')
print("pycache cleared")

# 4. migrate ddl_sync (演练 2 关键步骤, 实战必查 already applied)
print("\n--- Step 4: migrate ddl_sync ---")
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py migrate ddl_sync 2>&1 | head -20')
print(out)

# 5. kill gunicorn + qcluster
print("\n--- Step 5: kill ---")
run("pkill -9 -f 'gunicorn.*archery.*9003' 2>&1; sleep 2")
run("pkill -9 -f 'manage.py qcluster' 2>&1; sleep 2")
out = run("ps -ef | grep -E 'gunicorn.*9003|manage.py qcluster' | grep -v grep | wc -l")
print(f"kill 后进程数 (期望 0): {out.strip()}")

# 6. 拉新 gunicorn
print("\n--- Step 6: 拉新 gunicorn ---")
out = run('cd ' + DEV_BASE + ' && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn_d32_drill2.log 2>&1 & disown')
print(f"gunicorn 拉新: {out.strip()}")
time.sleep(5)
out = run("ps -ef | grep -E 'gunicorn.*9003' | grep -v grep | wc -l")
print(f"gunicorn 进程数 (期望 5): {out.strip()}")

# 7. 拉新 qcluster
print("\n--- Step 7: 拉新 qcluster ---")
out = run('cd ' + DEV_BASE + ' && setsid nohup sudo -u archery venv/bin/python manage.py qcluster </dev/null >/var/log/archery/qcluster_d32_drill2.log 2>&1 & disown')
print(f"qcluster 拉新: {out.strip()}")
time.sleep(4)
out = run("ps -ef | grep -E 'manage.py qcluster' | grep -v grep | head -2")
print(f"qcluster 进程: {out.strip()}")

# 8. 验证 1: /login/ 200
print("\n--- Step 8a: /login/ ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/login/")
print(f"/login/ HTTP (期望 200): {out.strip()}")

# 9. 验证 2: /ddl_sync/pair/ 302 (中间件重定向, 证明 ddl_sync 路由注册了)
print("\n--- Step 8b: /ddl_sync/pair/ ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/ddl_sync/pair/")
print(f"/ddl_sync/pair/ HTTP (期望 302 -> /login/): {out.strip()}")
out = run('tail -50 /var/log/archery/gunicorn_d32_drill2.log 2>&1 | grep "ddl_sync" | head -3')
print(f"gunicorn 日志: {out.strip()}")

# 10. 验证 3: showmigrations 状态 (期望 2 migrations [X])
print("\n--- Step 8c: showmigrations ---")
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py showmigrations ddl_sync 2>&1')
print(out)

# 11. 验证 4: 业务方登录后访问 /ddl_sync/pair/ 期望 200
print("\n--- Step 8d: 业务方登录访问 /ddl_sync/pair/ ---")
# 用 curl 模拟业务方登录
py_login = '''
import urllib.request, urllib.parse, http.cookiejar
# 134 dev 业务方账号
# 这里用 admin (有 view_ddlsyncpair 权限)
BASE = "http://127.0.0.1:9003"

# 1. 拿 csrf token
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
r = opener.open(BASE + "/login/")
html = r.read().decode("utf-8", errors="replace")
import re
m = re.search(r"name=\\"csrfmiddlewaretoken\\" value=\\"([^\\"]+)\\"", html)
csrf = m.group(1) if m else ""
print(f"CSRF: {csrf[:20]}...")

# 2. 登录
data = urllib.parse.urlencode({
    "csrfmiddlewaretoken": csrf,
    "username": "admin",
    "password": "archery",
}).encode()
r = opener.open(BASE + "/login/", data)
print(f"登录状态: {r.status}")

# 3. 访问 /ddl_sync/pair/
r = opener.open(BASE + "/ddl_sync/pair/")
html = r.read().decode("utf-8", errors="replace")
print(f"/ddl_sync/pair/ 状态: {r.status}")
print(f"页面长度: {len(html)}")
print(f"包含 '库对列表' (期望 True): {('库对列表' in html)}")
print(f"包含 'DDL 跨库同步' (期望 True): {('DDL 跨库同步' in html)}")
'''
out = run('python3 -c "' + py_login.replace('"', '\\"') + '" 2>&1')
print(out)

ssh.close()
