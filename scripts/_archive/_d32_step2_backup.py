# -*- coding: utf-8 -*-
"""D32 Step 2: 备份 settings.py + urls.py + base.html 三个文件到 .bak_d32."""
import paramiko

DEV = "172.20.2.134"
PWD = "lAqfb8uEmQYsnGNQwIHtGPwukjCz6J"
DEV_BASE = "/opt/archery/prod"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(hostname=DEV, port=22, username="root", password=PWD, timeout=15)

def run(cmd, timeout=15):
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        return out
    except Exception as e:
        return f"ERR: {e}"

print("=" * 60)
print("D32 Step 2: 备份 3 文件 + 看具体内容")
print("=" * 60)

# 1. 备份 3 文件
print("\n--- 备份 3 文件到 .bak_d32 ---")
cmds = [
    f"cp -v {DEV_BASE}/archery/settings.py {DEV_BASE}/archery/settings.py.bak_d32",
    f"cp -v {DEV_BASE}/archery/urls.py {DEV_BASE}/archery/urls.py.bak_d32",
    f"cp -v {DEV_BASE}/common/templates/base.html {DEV_BASE}/common/templates/base.html.bak_d32",
]
for c in cmds:
    out = run(c)
    print(f"  $ {c}")
    print(f"  -> {out.strip()}")

# 2. 看 settings.py ddl_sync 注册段 (演练 1 改回用)
print("\n--- settings.py line 425-435 (ddl_sync 注册段) ---")
out = run(f"sed -n '425,440p' {DEV_BASE}/archery/settings.py 2>&1")
print(out)

# 3. 看 urls.py ddl_sync 路由 (演练 1 改回用)
print("\n--- urls.py line 50-58 (ddl_sync 路由段) ---")
out = run(f"sed -n '50,58p' {DEV_BASE}/archery/urls.py 2>&1")
print(out)

# 4. 看 base.html ddl_sync menu (演练 1 改回用)
print("\n--- base.html line 148-165 (ddl_sync menu 段) ---")
out = run(f"sed -n '148,165p' {DEV_BASE}/common/templates/base.html 2>&1")
print(out)

# 5. 看 base.html menu 上下文 (找 li 块边界)
print("\n--- base.html line 135-170 (menu 上下文) ---")
out = run(f"sed -n '135,170p' {DEV_BASE}/common/templates/base.html 2>&1")
print(out)

ssh.close()
