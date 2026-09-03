# -*- coding: utf-8 -*-
"""D32 Step 6: 演练结束清理 .bak_d32 备份 + 验证 134 dev 最终状态."""
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
print("D32 Step 6: 演练结束清理 + 验证 134 dev 最终状态")
print("=" * 60)

# 1. 看 .bak_d32* 文件
print("\n--- Step 1: 演练前备份文件列表 ---")
out = run('ls -la ' + DEV_BASE + '/archery/*.bak_d32* ' + DEV_BASE + '/common/templates/*.bak_d32* 2>&1')
print(out)

# 2. 清理 .bak_d32* 备份 (演练结束)
print("\n--- Step 2: 清理 .bak_d32* 备份 ---")
out = run('rm -v ' + DEV_BASE + '/archery/settings.py.bak_d32 ' + DEV_BASE + '/archery/settings.py.bak_d32_pre_drill1 ' + DEV_BASE + '/archery/urls.py.bak_d32 ' + DEV_BASE + '/archery/urls.py.bak_d32_pre_drill1 ' + DEV_BASE + '/common/templates/base.html.bak_d32 ' + DEV_BASE + '/common/templates/base.html.bak_d32_pre_drill1 2>&1')
print(out)

# 3. 验证清理后
print("\n--- Step 3: 清理后 .bak_d32 文件 ---")
out = run('ls ' + DEV_BASE + '/archery/*.bak_d32* ' + DEV_BASE + '/common/templates/*.bak_d32* 2>&1 | head -3')
print(out)

# 4. 验证 134 dev 最终状态
print("\n--- Step 4: 134 dev 最终状态 ---")
out = run('grep -n "if CUSTOM_DDL_SYNC_ENABLED\\|INSTALLED_APPS.*ddl_sync" ' + DEV_BASE + '/archery/settings.py | head -3')
print(f"settings.py: {out.strip()}")
out = run('grep -n "if getattr.*CUSTOM_DDL_SYNC\\|ddl_sync/" ' + DEV_BASE + '/archery/urls.py | head -3')
print(f"urls.py: {out.strip()}")
out = run('grep -n "ddl_sync.view_ddlsyncpair\\|库对列表" ' + DEV_BASE + '/common/templates/base.html | head -3')
print(f"base.html: {out.strip()}")

# 5. 进程
print("\n--- Step 5: 进程 ---")
out = run("ps -ef | grep -E 'gunicorn.*9003|manage.py qcluster' | grep -v grep | wc -l")
print(f"gunicorn+qcluster 进程数: {out.strip()}")
out = run("ss -tlnp | grep ':9003' 2>&1 | head -3")
print(f"9003 端口: {out.strip()}")

# 6. showmigrations 最终状态
print("\n--- Step 6: showmigrations ---")
out = run('cd ' + DEV_BASE + ' && sudo -u archery venv/bin/python manage.py showmigrations ddl_sync 2>&1 | tail -5')
print(out)

# 7. reverse() 最终验证
print("\n--- Step 7: reverse() 最终验证 ---")
py = '''
from django.urls import reverse
print(f"pair_list: {reverse('ddl_sync:pair_list')}")
print(f"pair_create: {reverse('ddl_sync:pair_create')}")
'''
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c '" + py + "' 2>&1 | tail -3")
print(out)

ssh.close()
