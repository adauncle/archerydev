# -*- coding: utf-8 -*-
"""D32 Step 3 v2: 演练 1 干净状态 - 注释 ddl_sync 引用 + kill + 拉新 + 验证 500.

用 python 直接改 3 个文件 (避免 sed 跟 format % 冲突).
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

# 改文件的 python 脚本 (远程执行)
MOD_PY = r"""
import re, sys

base = '/opt/archery/prod'

# 1. settings.py 注释 if CUSTOM_DDL_SYNC_ENABLED 块
path = f'{base}/archery/settings.py'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()
new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    # 检测到 "    if CUSTOM_DDL_SYNC_ENABLED:" 这种行, 整块注释掉
    if line.rstrip() == 'if CUSTOM_DDL_SYNC_ENABLED:':
        # 找块末尾 (缩进回到 0 的行 或 文件结束)
        new_lines.append('# D32 演练 1: 注释 ddl_sync 注册\n')
        new_lines.append('# if CUSTOM_DDL_SYNC_ENABLED:\n')
        i += 1
        # 跳到块结束: 缩进 < 4 的行 (除了空行)
        while i < len(lines):
            cur = lines[i]
            if cur.strip() == '' or cur.startswith('    ') or cur.startswith('\t'):
                new_lines.append('# ' + cur)
                i += 1
            else:
                break
        continue
    new_lines.append(line)
    i += 1
with open(path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('settings.py: ddl_sync 注册块已注释')

# 2. urls.py 注释 if getattr 块
path = f'{base}/archery/urls.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
# 找 "if getattr(settings, "CUSTOM_DDL_SYNC_ENABLED", False):" 整块
pattern = r'(    )if getattr\(settings, "CUSTOM_DDL_SYNC_ENABLED", False\):.*?(\n\})'
m = re.search(pattern, content, re.DOTALL)
if m:
    old = m.group(0)
    new = '# D32 演练 1: 注释 ddl_sync 路由\n' + '\n'.join(['# ' + l for l in old.split('\n')])
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('urls.py: ddl_sync 路由块已注释')
else:
    print('urls.py: ddl_sync 路由块没找到')
    sys.exit(1)

# 3. base.html 注释 ddl_sync li 块
path = f'{base}/common/templates/base.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
# 找 {% if user.is_superuser or perms.ddl_sync.view_ddlsyncpair %} 到对应的 {% endif %}
pattern = r'                    \{\%\s*if user\.is_superuser or perms\.ddl_sync\.view_ddlsyncpair\s*\%\}.*?\{\%\s*endif\s*\%\}'
m = re.search(pattern, content, re.DOTALL)
if m:
    old = m.group(0)
    new = '{# D32 演练 1: 注释 ddl_sync menu #}\n{# ' + old.replace('\n', '\n{# ') + ' #}'
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('base.html: ddl_sync menu 块已注释')
else:
    print('base.html: ddl_sync menu 块没找到')
    sys.exit(1)
"""

print("=" * 60)
print("D32 Step 3 v2: 演练 1 干净状态")
print("=" * 60)

# 0. 上传改文件脚本
print("\n--- Step 0: 上传改文件脚本 ---")
out = run(f"cat > /tmp/_d32_modify.py << 'PYEOF'\n{MOD_PY}\nPYEOF\necho 'uploaded'")
print(out)

# 1. 执行改文件
print("\n--- Step 1: 执行改 3 文件 ---")
out = run("python3 /tmp/_d32_modify.py 2>&1")
print(out)

# 2. 验证 settings.py 改成功
print("\n--- Step 2: 验证 settings.py ---")
out = run(f"sed -n '425,445p' {DEV_BASE}/archery/settings.py")
print(out)

# 3. 验证 urls.py 改成功
print("\n--- Step 3: 验证 urls.py ---")
out = run(f"sed -n '48,62p' {DEV_BASE}/archery/urls.py")
print(out)

# 4. 验证 base.html 改成功
print("\n--- Step 4: 验证 base.html ---")
out = run(f"sed -n '150,180p' {DEV_BASE}/common/templates/base.html")
print(out)

# 5. 清 pycache
print("\n--- Step 5: 清 pycache ---")
out = run(f"find {DEV_BASE} -name __pycache__ -type d -exec rm -rf {{}} + 2>/dev/null; find {DEV_BASE} -name '*.pyc' -delete 2>/dev/null; echo 'pycache cleared'")
print(out)

# 6. kill 老 gunicorn + qcluster
print("\n--- Step 6: kill gunicorn + qcluster ---")
run("pkill -9 -f 'gunicorn.*archery.*9003' 2>&1; sleep 2")
run("pkill -9 -f 'manage.py qcluster' 2>&1; sleep 2")
out = run("ps -ef | grep -E 'gunicorn.*9003|manage.py qcluster' | grep -v grep | wc -l")
print(f"gunicorn+qcluster 进程数 (期望 0): {out.strip()}")

# 7. 拉新 gunicorn
print("\n--- Step 7: 拉新 gunicorn ---")
out = run(f"cd {DEV_BASE} && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn_d32_drill1.log 2>&1 & disown")
print(f"gunicorn 拉新返回: {out.strip()}")
time.sleep(5)
out = run("ps -ef | grep -E 'gunicorn.*9003' | grep -v grep | wc -l")
print(f"gunicorn 进程数 (期望 5: 1 master + 4 worker): {out.strip()}")

# 8. 拉新 qcluster
print("\n--- Step 8: 拉新 qcluster ---")
out = run(f"cd {DEV_BASE} && setsid nohup sudo -u archery venv/bin/python manage.py qcluster </dev/null >/var/log/archery/qcluster_d32_drill1.log 2>&1 & disown")
print(f"qcluster 拉新返回: {out.strip()}")
time.sleep(4)
out = run("ps -ef | grep -E 'manage.py qcluster' | grep -v grep | head -2")
print(f"qcluster 进程: {out.strip()}")

# 9. 验证 1: /login/ 必 200
print("\n--- Step 9a: /login/ 验证 ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/login/")
print(f"/login/ HTTP status: {out.strip()}")

# 10. 验证 2: /ddl_sync/pair/ 必 500
print("\n--- Step 9b: /ddl_sync/pair/ 验证 (期望 500) ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/ddl_sync/pair/")
print(f"/ddl_sync/pair/ HTTP status: {out.strip()}")
out = run("tail -50 /var/log/archery/gunicorn_d32_drill1.log 2>&1 | grep -E 'NoReverseMatch|ddl_sync' | head -3")
print(f"gunicorn 日志 (期望 NoReverseMatch): {out.strip()}")

# 11. 验证 3: /admin/ base.html 渲染不会抛 perms.ddl_sync
print("\n--- Step 9c: /admin/ 验证 ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/admin/ -L --max-time 10")
print(f"/admin/ HTTP status: {out.strip()}")

# 12. 看 ddl_sync app 还在不在 (演练 1 保留目录)
print("\n--- Step 10: ddl_sync 目录保留确认 ---")
out = run(f"ls -d {DEV_BASE}/sql/extensions/ddl_sync/ 2>&1")
print(f"ddl_sync 目录 (期望保留): {out.strip()}")

# 13. 看 migration 状态
print("\n--- Step 11: migration 状态 ---")
out = run(f"cd {DEV_BASE} && sudo -u archery venv/bin/python manage.py showmigrations ddl_sync 2>&1 | head -10")
print(out)

ssh.close()
