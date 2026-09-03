# -*- coding: utf-8 -*-
"""D32 Step 3 v3: 演练 1 干净状态 - 注释 ddl_sync 引用 + kill + 拉新 + 验证 500.

修复:
1. urls.py 整块 if + urlpatterns 都注释掉 (之前 v2 只注释了 if 行, 缩进错乱)
2. base.html 用具体行号定位 (之前 v2 regex 匹配失败)
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

# 1. settings.py 注释 if CUSTOM_DDL_SYNC_ENABLED 块 (v2 已成功, 再跑一次幂等)
path = f'{base}/archery/settings.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
# 看是否已经注释过
if '# D32 演练 1: 注释 ddl_sync 注册' in content:
    print('settings.py: 已经注释过, 跳过')
else:
    lines = content.split('\n')
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.rstrip() == 'if CUSTOM_DDL_SYNC_ENABLED:':
            new_lines.append('# D32 演练 1: 注释 ddl_sync 注册')
            new_lines.append('# if CUSTOM_DDL_SYNC_ENABLED:')
            i += 1
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
        f.write('\n'.join(new_lines))
    print('settings.py: ddl_sync 注册块已注释')

# 2. urls.py: 用行号定位 (v2 v3 都改, 找干净的方式)
# 实际当前状态: line 50-57 是 ddl_sync 块 (可能已部分改过)
# 用更宽松的 regex: 从 "# D32 演练 1: 注释 ddl_sync 路由" 注释行到 urlpatterns + ] 块
path = f'{base}/archery/urls.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

if '# D32 演练 1: 注释 ddl_sync 路由 (整块)' in content:
    print('urls.py: 已经注释过 (整块), 跳过')
else:
    # 找 "if getattr(settings, \"CUSTOM_DDL_SYNC_ENABLED\", False):" 整块
    # 用 greedy 模式从 if 到第一个 "\n}" (urlpatterns 列表结束)
    pattern = r'if getattr\(settings, "CUSTOM_DDL_SYNC_ENABLED", False\):\s*# pragma: no cover\n[ \t]+urlpatterns \+=\[\n[ \t]+path\("ddl_sync/".*?\n[ \t]+\]\n'
    m = re.search(pattern, content, re.DOTALL)
    if m:
        old = m.group(0)
        new = '# D32 演练 1: 注释 ddl_sync 路由 (整块)\n' + '\n'.join(['# ' + l for l in old.split('\n')])
        content = content.replace(old, new)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print('urls.py: ddl_sync 路由整块已注释')
    else:
        print('urls.py: 没找到完整 ddl_sync 路由块, 手动看')
        sys.exit(1)

# 3. base.html: 用行号定位 (v2 regex 失败, 用更直接的方式)
path = f'{base}/common/templates/base.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

if 'D32 演练 1: 注释 ddl_sync menu (整块)' in content:
    print('base.html: 已经注释过, 跳过')
else:
    # 找 "{% if user.is_superuser or perms.ddl_sync.view_ddlsyncpair %}" 到对应的 "{% endif %}"
    # 用非贪婪匹配
    pattern = r'\{% if user\.is_superuser or perms\.ddl_sync\.view_ddlsyncpair %\}.*?\{% endif %\}'
    m = re.search(pattern, content, re.DOTALL)
    if m:
        old = m.group(0)
        new = '{# D32 演练 1: 注释 ddl_sync menu (整块) #}\n' + old
        content = content.replace(old, new)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print('base.html: ddl_sync menu 块已注释')
    else:
        print('base.html: regex 没匹配, 用行号定位')
        lines = content.split('\n')
        # 找 "{% if user.is_superuser or perms.ddl_sync.view_ddlsyncpair %}" 行号
        start = None
        for i, line in enumerate(lines):
            if '{% if user.is_superuser or perms.ddl_sync.view_ddlsyncpair %}' in line:
                start = i
                break
        if start is None:
            print('base.html: 找不到 if 行, 失败')
            sys.exit(1)
        # 找对应的 {% endif %}
        end = None
        for j in range(start + 1, len(lines)):
            if '{% endif %}' in lines[j]:
                end = j
                break
        if end is None:
            print('base.html: 找不到 endif, 失败')
            sys.exit(1)
        # 注释 start 到 end 之间的所有行
        new_lines = lines[:start] + ['{# D32 演练 1: 注释 ddl_sync menu (整块) #}'] + ['{# ' + l + ' #}' for l in lines[start:end+1]] + lines[end+1:]
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(new_lines))
        print(f'base.html: ddl_sync menu 行 {start+1}-{end+1} 已注释')
"""

print("=" * 60)
print("D32 Step 3 v3: 演练 1 干净状态 (修复 urls.py + base.html)")
print("=" * 60)

# 0. 上传改文件脚本
print("\n--- Step 0: 上传改文件脚本 ---")
out = run(f"cat > /tmp/_d32_modify.py << 'PYEOF'\n{MOD_PY}\nPYEOF\necho 'uploaded'")
print(out)

# 1. 执行改文件
print("\n--- Step 1: 执行改 3 文件 ---")
out = run("python3 /tmp/_d32_modify.py 2>&1")
print(out)

# 2. 验证 settings.py
print("\n--- Step 2: 验证 settings.py ---")
out = run(f"grep -n 'CUSTOM_DDL_SYNC_ENABLED\\|D32 演练 1' {DEV_BASE}/archery/settings.py | head -10")
print(out)

# 3. 验证 urls.py
print("\n--- Step 3: 验证 urls.py ---")
out = run(f"grep -n 'CUSTOM_DDL_SYNC_ENABLED\\|D32 演练 1\\|ddl_sync' {DEV_BASE}/archery/urls.py | head -10")
print(out)
out = run(f"sed -n '48,62p' {DEV_BASE}/archery/urls.py")
print("urls.py line 48-62:")
print(out)

# 4. 验证 base.html
print("\n--- Step 4: 验证 base.html ---")
out = run(f"grep -n 'D32 演练 1\\|ddl_sync\\|库对列表' {DEV_BASE}/common/templates/base.html | head -10")
print(out)

# 5. 清 pycache + kill
print("\n--- Step 5: 清 pycache + kill ---")
run(f"find {DEV_BASE} -name __pycache__ -type d -exec rm -rf {{}} + 2>/dev/null; find {DEV_BASE} -name '*.pyc' -delete 2>/dev/null")
run("pkill -9 -f 'gunicorn.*archery.*9003' 2>&1; sleep 2")
run("pkill -9 -f 'manage.py qcluster' 2>&1; sleep 2")
out = run("ps -ef | grep -E 'gunicorn.*9003|manage.py qcluster' | grep -v grep | wc -l")
print(f"进程数 (期望 0): {out.strip()}")

# 6. 拉新 gunicorn
print("\n--- Step 6: 拉新 gunicorn ---")
out = run(f"cd {DEV_BASE} && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn_d32_drill1.log 2>&1 & disown")
print(f"gunicorn 拉新: {out.strip()}")
time.sleep(5)
out = run("ps -ef | grep -E 'gunicorn.*9003' | grep -v grep | wc -l")
print(f"gunicorn 进程数 (期望 5): {out.strip()}")

# 7. 拉新 qcluster
print("\n--- Step 7: 拉新 qcluster ---")
out = run(f"cd {DEV_BASE} && setsid nohup sudo -u archery venv/bin/python manage.py qcluster </dev/null >/var/log/archery/qcluster_d32_drill1.log 2>&1 & disown")
print(f"qcluster 拉新: {out.strip()}")
time.sleep(4)
out = run("ps -ef | grep -E 'manage.py qcluster' | grep -v grep | head -2")
print(f"qcluster 进程: {out.strip()}")

# 8. 验证 1: /login/ 必 200
print("\n--- Step 8a: /login/ 验证 ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/login/")
print(f"/login/ HTTP status: {out.strip()}")

# 9. 验证 2: /ddl_sync/pair/ 必 500
print("\n--- Step 8b: /ddl_sync/pair/ 验证 (期望 500) ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/ddl_sync/pair/")
print(f"/ddl_sync/pair/ HTTP status: {out.strip()}")
out = run("tail -50 /var/log/archery/gunicorn_d32_drill1.log 2>&1 | grep -E 'NoReverseMatch|ddl_sync|404' | head -5")
print(f"gunicorn 日志: {out.strip()}")

# 10. 验证 3: /admin/ 200 (base.html 注释掉了, admin 渲染正常)
print("\n--- Step 8c: /admin/ 验证 ---")
out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9003/admin/ -L --max-time 10")
print(f"/admin/ HTTP status: {out.strip()}")

# 11. 看 showmigrations 状态 (ddl_sync app 没注册)
print("\n--- Step 9: showmigrations 状态 ---")
out = run(f"cd {DEV_BASE} && sudo -u archery venv/bin/python manage.py showmigrations ddl_sync 2>&1 | head -5")
print(out)

ssh.close()
