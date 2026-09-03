# -*- coding: utf-8 -*-
"""D32 fix urls.py: 单独修 urls.py if 行 + 重启 + 验证."""
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
print("D32 修复 urls.py if 行 + 重启 + 验证")
print("=" * 60)

# 1. 单独修 urls.py (用 sed 单引号)
print("\n--- Step 1: urls.py if 行替换 ---")
out = run('grep -n "if getattr.*CUSTOM_DDL_SYNC" ' + DEV_BASE + '/archery/urls.py')
print(f"当前: {out.strip()}")

# 用 python 修最稳
py_script = '''
path = "/opt/archery/prod/archery/urls.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()
old = "if getattr(settings, \\"CUSTOM_DDL_SYNC_ENABLED\\", False):  # pragma: no cover"
new = "if False:  # D32DRILL1 if getattr(settings, \\"CUSTOM_DDL_SYNC_ENABLED\\", False):  # pragma: no cover"
if old in content:
    content = content.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: urls.py if 行已替换")
else:
    print("ERR: if 行没找到")
    print(repr(content[content.find("if getattr"):content.find("if getattr")+200]))
'''
out = run("python3 -c '" + py_script + "' 2>&1")
print(f"python 输出: {out.strip()}")
out = run('grep -n "D32DRILL1\\|if False\\|if getattr.*CUSTOM_DDL_SYNC" ' + DEV_BASE + '/archery/urls.py')
print(f"替换后: {out.strip()}")
out = run('sed -n "50,57p" ' + DEV_BASE + '/archery/urls.py')
print("After 50-57:")
print(out)

# 2. 清 pycache + kill + 拉新
print("\n--- Step 2: 清 pycache + kill + 拉新 ---")
run('find ' + DEV_BASE + ' -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null')
run('find ' + DEV_BASE + ' -name "*.pyc" -delete 2>/dev/null')
run("pkill -9 -f 'gunicorn.*archery.*9003' 2>&1; sleep 2")
run("pkill -9 -f 'manage.py qcluster' 2>&1; sleep 2")
out = run("ps -ef | grep -E 'gunicorn.*9003|manage.py qcluster' | grep -v grep | wc -l")
print(f"kill 后进程数 (期望 0): {out.strip()}")

out = run('cd ' + DEV_BASE + ' && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn_d32_drill1.log 2>&1 & disown')
print(f"gunicorn 拉新: {out.strip()}")
time.sleep(5)
out = run("ps -ef | grep -E 'gunicorn.*9003' | grep -v grep | wc -l")
print(f"gunicorn 进程数 (期望 5): {out.strip()}")

out = run('cd ' + DEV_BASE + ' && setsid nohup sudo -u archery venv/bin/python manage.py qcluster </dev/null >/var/log/archery/qcluster_d32_drill1.log 2>&1 & disown')
print(f"qcluster 拉新: {out.strip()}")
time.sleep(4)
out = run("ps -ef | grep -E 'manage.py qcluster' | grep -v grep | head -2")
print(f"qcluster 进程: {out.strip()}")

# 3. 验证 1: /login/ 200
print("\n--- Step 3a: /login/ ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/login/")
print(f"/login/ HTTP (期望 200): {out.strip()}")

# 4. 验证 2: /ddl_sync/pair/ 500
print("\n--- Step 3b: /ddl_sync/pair/ ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/ddl_sync/pair/")
print(f"/ddl_sync/pair/ HTTP (期望 500): {out.strip()}")
out = run('tail -80 /var/log/archery/gunicorn_d32_drill1.log 2>&1 | grep -E "NoReverseMatch|404|500|not found" | head -3')
print(f"gunicorn 日志: {out.strip()}")

# 5. 验证 3: /admin/ 200
print("\n--- Step 3c: /admin/ ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/admin/ -L --max-time 10")
print(f"/admin/ HTTP (期望 200): {out.strip()}")

# 6. 验证 4: showmigrations 状态
print("\n--- Step 3d: showmigrations ---")
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py showmigrations ddl_sync 2>&1 | head -5')
print(out)

ssh.close()
