# -*- coding: utf-8 -*-
"""D32 Step 1: 查 134 dev 当前 4 大步状态 (作为演练基线)."""
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
print("D32 Step 1: 134 dev 当前 4 大步状态 (演练基线)")
print("=" * 60)

# 1. ddl_sync 目录存在
print("\n--- /opt/archery/prod/sql/extensions/ddl_sync/ ---")
out = run(f"ls -la {DEV_BASE}/sql/extensions/ddl_sync/ 2>&1")
print(out)

# 2. settings.py INSTALLED_APPS 现状
print("\n--- /opt/archery/prod/archery/settings.py INSTALLED_APPS ---")
out = run(f"grep -n -A 2 'ddl_sync' {DEV_BASE}/archery/settings.py 2>&1")
print(out)

# 3. urls.py ddl_sync 路由现状
print("\n--- /opt/archery/prod/archery/urls.py ddl_sync ---")
out = run(f"grep -n 'ddl_sync\\|ddl_gh_ost' {DEV_BASE}/archery/urls.py 2>&1")
print(out)

# 4. base.html ddl_sync menu 现状
print("\n--- /opt/archery/prod/common/templates/base.html ddl_sync ---")
out = run(f"grep -n 'ddl_sync\\|库对列表' {DEV_BASE}/common/templates/base.html 2>&1")
print(out)

# 5. ddl_sync 目录大小 + 文件数
print("\n--- ddl_sync 目录总览 ---")
out = run(f"find {DEV_BASE}/sql/extensions/ddl_sync/ -type f 2>&1 | head -40")
print(out)
out = run(f"find {DEV_BASE}/sql/extensions/ddl_sync/ -type f | wc -l 2>&1")
print(f"\n[file count: {out.strip()}]")

# 6. migration 状态
print("\n--- ddl_sync migrations ---")
out = run(f"ls -la {DEV_BASE}/sql/extensions/ddl_sync/migrations/ 2>&1")
print(out)

# 7. gunicorn / qcluster 当前进程
print("\n--- gunicorn / qcluster 进程 ---")
out = run("ps -ef | grep -E 'gunicorn.*archery|qcluster' | grep -v grep 2>&1")
print(out)

# 8. 134 dev gunicorn 端口
print("\n--- 134 dev gunicorn 端口 ---")
out = run("ss -tlnp | grep -E ':9003|:9123' 2>&1")
print(out)

ssh.close()
