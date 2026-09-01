#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D9 阶段 2: 134 dev gunicorn 实际 settings.CUSTOM_DDL_SYNC_ENABLED + archery/urls 实际 include 状况
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
print('settings.CUSTOM_DDL_SYNC_ENABLED:', repr(getattr(settings, 'CUSTOM_DDL_SYNC_ENABLED', 'NOT SET')))

# 2. settings 实际 INSTALLED_APPS
print('ddl_sync in INSTALLED_APPS:', any('ddl_sync' in app for app in settings.INSTALLED_APPS))

# 3. 查 archery/urls.py 53 行 if 条件怎么 eval
val = getattr(settings, 'CUSTOM_DDL_SYNC_ENABLED', False)
print(f'getattr default False: {val}')
print(f'bool({val}): {bool(val)}')

# 4. 看 archery.urls 实际 urlpatterns (已经 loaded)
import archery.urls
ddl_sync_in_urlpatterns = False
for p in archery.urls.urlpatterns:
    if 'ddl_sync' in str(p.pattern):
        ddl_sync_in_urlpatterns = True
        print(f'  found: {p.pattern}')
print(f'ddl_sync in archery.urls.urlpatterns: {ddl_sync_in_urlpatterns}')

# 5. archery.settings 源码 53 行附近
import inspect
src = inspect.getsource(archery.urls)
import re
m = re.search(r'(if getattr.*CUSTOM_DDL_SYNC_ENABLED.*?)(?=\\n\\n|\\Z)', src, re.DOTALL)
if m:
    print('archery.urls L53-56:')
    print(m.group(1)[:500])
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d9_settings.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d9_settings.py 2>&1',
    'rm -f /tmp/_d9_settings.py',
]


def ssh_exec(ssh, cmd, timeout=30):
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
                out, err, rc = ssh_exec(ssh, cmd, timeout=30)
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
