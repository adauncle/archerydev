# -*- coding: utf-8 -*-
"""D32 Step 3 v6: 演练 1 干净状态 - 用 if False 替换 (块结构不变).

策略:
- settings.py: if CUSTOM_DDL_SYNC_ENABLED: -> if False:  # D32DRILL1
- urls.py: if getattr(settings, "CUSTOM_DDL_SYNC_ENABLED", False): -> if False:  # D32DRILL1
- base.html: 用 sed 整段注释 (v5 已成功)
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
print("D32 Step 3 v6: 演练 1 干净状态 (if False + base.html 注释)")
print("=" * 60)

# 1. 还原 3 文件到 .bak_d32 (干净基线)
print("\n--- Step 1: 还原 3 文件到 .bak_d32 ---")
run('cp ' + DEV_BASE + '/archery/settings.py.bak_d32 ' + DEV_BASE + '/archery/settings.py')
run('cp ' + DEV_BASE + '/archery/urls.py.bak_d32 ' + DEV_BASE + '/archery/urls.py')
run('cp ' + DEV_BASE + '/common/templates/base.html.bak_d32 ' + DEV_BASE + '/common/templates/base.html')
out = run('grep -c "D32DRILL1\\|D32 演练 1" ' + DEV_BASE + '/archery/settings.py ' + DEV_BASE + '/archery/urls.py ' + DEV_BASE + '/common/templates/base.html')
print(f"D32 标记数 (期望 0): {out.strip()}")

# 2. settings.py: if CUSTOM_DDL_SYNC_ENABLED: -> if False:  # D32DRILL1
print("\n--- Step 2: settings.py if 行替换 ---")
# 先看 if 行
out = run('grep -n "if CUSTOM_DDL_SYNC_ENABLED:" ' + DEV_BASE + '/archery/settings.py')
print(f"if 行: {out.strip()}")
# 替换
run('sed -i "s|^if CUSTOM_DDL_SYNC_ENABLED:|if False:  # D32DRILL1 if CUSTOM_DDL_SYNC_ENABLED:|" ' + DEV_BASE + '/archery/settings.py')
out = run('grep -n "D32DRILL1\\|if False" ' + DEV_BASE + '/archery/settings.py | head -5')
print(f"替换后: {out.strip()}")
out = run('sed -n "428,432p" ' + DEV_BASE + '/archery/settings.py')
print("After 428-432:")
print(out)

# 3. urls.py: if getattr 替换
print("\n--- Step 3: urls.py if 行替换 ---")
out = run('grep -n "if getattr.*CUSTOM_DDL_SYNC" ' + DEV_BASE + '/archery/urls.py')
print(f"if 行: {out.strip()}")
# 用 perl 替换 (双引号 + # pragma 都处理)
run('perl -i -pe "s|^if getattr\\(settings, \"CUSTOM_DDL_SYNC_ENABLED\", False\\):|if False:  # D32DRILL1 if getattr(settings, \\\"CUSTOM_DDL_SYNC_ENABLED\\\", False):|" ' + DEV_BASE + '/archery/urls.py')
out = run('grep -n "D32DRILL1\\|if False" ' + DEV_BASE + '/archery/urls.py | head -5')
print(f"替换后: {out.strip()}")
out = run('sed -n "50,57p" ' + DEV_BASE + '/archery/urls.py')
print("After 50-57:")
print(out)

# 4. base.html: sed 注释 152-169 (v5 验证有效)
print("\n--- Step 4: base.html 注释 152-169 ---")
run('sed -i "152,169s/^/###D32DRILL1### /" ' + DEV_BASE + '/common/templates/base.html')
out = run('sed -n "148,175p" ' + DEV_BASE + '/common/templates/base.html')
print("After 148-175:")
print(out)

# 5. 清 pycache + kill
print("\n--- Step 5: 清 pycache + kill ---")
run('find ' + DEV_BASE + ' -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null')
run('find ' + DEV_BASE + ' -name "*.pyc" -delete 2>/dev/null')
run("pkill -9 -f 'gunicorn.*archery.*9003' 2>&1; sleep 2")
run("pkill -9 -f 'manage.py qcluster' 2>&1; sleep 2")
out = run("ps -ef | grep -E 'gunicorn.*9003|manage.py qcluster' | grep -v grep | wc -l")
print(f"进程数 (期望 0): {out.strip()}")

# 6. 拉新 gunicorn
print("\n--- Step 6: 拉新 gunicorn ---")
out = run('cd ' + DEV_BASE + ' && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn_d32_drill1.log 2>&1 & disown')
print(f"gunicorn 拉新: {out.strip()}")
time.sleep(5)
out = run("ps -ef | grep -E 'gunicorn.*9003' | grep -v grep | wc -l")
print(f"gunicorn 进程数 (期望 5): {out.strip()}")

# 7. 拉新 qcluster
print("\n--- Step 7: 拉新 qcluster ---")
out = run('cd ' + DEV_BASE + ' && setsid nohup sudo -u archery venv/bin/python manage.py qcluster </dev/null >/var/log/archery/qcluster_d32_drill1.log 2>&1 & disown')
print(f"qcluster 拉新: {out.strip()}")
time.sleep(4)
out = run("ps -ef | grep -E 'manage.py qcluster' | grep -v grep | head -2")
print(f"qcluster 进程: {out.strip()}")

# 8. 验证 1: /login/ 必 200
print("\n--- Step 8a: /login/ 验证 ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/login/")
print(f"/login/ HTTP status (期望 200): {out.strip()}")

# 9. 验证 2: /ddl_sync/pair/ 必 500
print("\n--- Step 8b: /ddl_sync/pair/ 验证 (期望 500) ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/ddl_sync/pair/")
print(f"/ddl_sync/pair/ HTTP status (期望 500): {out.strip()}")
out = run('tail -80 /var/log/archery/gunicorn_d32_drill1.log 2>&1 | grep -E "NoReverseMatch|404|500|not found" | head -3')
print(f"gunicorn 日志: {out.strip()}")

# 10. 验证 3: /admin/ 200
print("\n--- Step 8c: /admin/ 验证 ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/admin/ -L --max-time 10")
print(f"/admin/ HTTP status (期望 200): {out.strip()}")

# 11. 验证 4: showmigrations 状态
print("\n--- Step 8d: showmigrations 状态 ---")
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py showmigrations ddl_sync 2>&1 | head -5')
print(out)

ssh.close()
