#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11: 134 dev 查 CUSTOM_DDL_SYNC_ENABLED 实际状态 + namespace 注册情况
"""
import io
import sys
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DEV_HOST = '172.20.2.134'
DEV_PORT = 22
DEV_USER = 'root'
DEV_PASS = 'CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW'

TEST_CODE = """
import django
django.setup()

from django.conf import settings

# 1. settings 实际 CUSTOM_DDL_SYNC_ENABLED
print('1. settings.CUSTOM_DDL_SYNC_ENABLED:', repr(getattr(settings, 'CUSTOM_DDL_SYNC_ENABLED', 'NOT_SET')))

# 2. INSTALLED_APPS 含 ddl_sync?
print('2. ddl_sync in INSTALLED_APPS:', any('ddl_sync' in app for app in settings.INSTALLED_APPS))

# 3. archery.urls.urlpatterns 实际内容
import archery.urls
ddl_sync_in_urls = False
ddl_sync_namespace = False
for p in archery.urls.urlpatterns:
    s = str(p.pattern)
    if 'ddl_sync' in s:
        ddl_sync_in_urls = True
        # namespace 检查
        if hasattr(p, 'namespace') and p.namespace == 'ddl_sync':
            ddl_sync_namespace = True
print('3. ddl_sync in archery.urls.urlpatterns:', ddl_sync_in_urls)
print('4. ddl_sync namespace registered:', ddl_sync_namespace)

# 5. ROOT_URLCONF 解析
from django.urls import get_resolver
all_urlpatterns = get_resolver().url_patterns
print('5. ROOT_URLCONF url_patterns:')
for p in all_urlpatterns:
    print(f'   {p.pattern}')

# 6. 看 134 dev .env 实际内容
import os
env_path = '/opt/archery/prod/.env'
print()
print(f'6. /opt/archery/prod/.env 含 CUSTOM_DDL_SYNC_ENABLED: ', end='')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if 'CUSTOM_DDL_SYNC' in line:
                print(repr(line.strip()))
                break
        else:
            print('NO')
else:
    print('FILE NOT EXIST')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d11_check.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d11_check.py 2>&1',
    'rm -f /tmp/_d11_check.py',
]


def ssh_exec(ssh, cmd, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    rc = stdout.channel.recv_exit_status()
    return out, err, rc


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=DEV_HOST, port=DEV_PORT,
        username=DEV_USER, password=DEV_PASS,
        look_for_keys=False, allow_agent=False,
    )
    try:
        for i, cmd in enumerate(REMOTE_CMDS, 1):
            print(f'\n=== CMD #{i} ===')
            try:
                out, err, rc = ssh_exec(ssh, cmd, timeout=60)
                print(f'--- RC={rc} ---')
                if out.strip():
                    print('STDOUT:')
                    print(out.rstrip())
                if err.strip():
                    print('STDERR:')
                    print(err.rstrip())
            except Exception as e:
                print(f'EXCEPTION: {e}')
    finally:
        ssh.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
