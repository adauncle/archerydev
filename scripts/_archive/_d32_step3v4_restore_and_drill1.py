# -*- coding: utf-8 -*-
"""D32 Step 3 v4: 还原 3 文件 + 重新演练 1 干净状态.

策略: 先用 .bak_d32 还原 3 文件, 重新演练 1, 用更稳的 python + 行号定位.
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
print("D32 Step 3 v4: 还原 + 重做演练 1")
print("=" * 60)

# 1. 还原 3 文件 (用 .bak_d32 覆盖)
print("\n--- Step 1: 还原 3 文件 ---")
run(f"cp -v {DEV_BASE}/archery/settings.py.bak_d32 {DEV_BASE}/archery/settings.py")
run(f"cp -v {DEV_BASE}/archery/urls.py.bak_d32 {DEV_BASE}/archery/urls.py")
run(f"cp -v {DEV_BASE}/common/templates/base.html.bak_d32 {DEV_BASE}/common/templates/base.html")
out = run(f"grep -c 'D32 演练 1' {DEV_BASE}/archery/settings.py {DEV_BASE}/archery/urls.py {DEV_BASE}/common/templates/base.html")
print(f"D32 演练 1 标记数 (期望 0): {out.strip()}")

# 2. 验证还原后状态
print("\n--- Step 2: 还原后 settings.py ---")
out = run(f"grep -n 'CUSTOM_DDL_SYNC_ENABLED\\|INSTALLED_APPS += ' {DEV_BASE}/archery/settings.py | head -5")
print(out)

print("\n--- Step 3: 还原后 urls.py ---")
out = run(f"grep -n 'ddl_sync\\|getattr' {DEV_BASE}/archery/urls.py | head -5")
print(out)

print("\n--- Step 4: 还原后 base.html ---")
out = run(f"grep -n 'ddl_sync\\|库对列表' {DEV_BASE}/common/templates/base.html | head -5")
print(out)

# 3. 找 base.html ddl_sync menu 块的精确行号
print("\n--- Step 5: base.html 块精确行号 ---")
out = run('grep -n "ddl_sync.view_ddlsyncpair\\|{% endif %}" ' + DEV_BASE + '/common/templates/base.html | head -10')
print(out)

ssh.close()
