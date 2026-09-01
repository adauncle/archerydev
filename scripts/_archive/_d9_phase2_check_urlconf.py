#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D9 阶段 2: 检查 134 dev settings 是不是真让 ddl_sync urls include 了
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
print('1. settings.CUSTOM_DDL_SYNC_ENABLED:', getattr(settings, 'CUSTOM_DDL_SYNC_ENABLED', 'NOT SET'))
print('2. settings.INSTALLED_APPS 中含 ddl_sync:', any('ddl_sync' in app for app in settings.INSTALLED_APPS))

# 3. 看 archery.urls 实际加载时的 urlpatterns
import archery.urls
print('3. archery.urls.urlpatterns 类型:', type(archery.urls.urlpatterns))
for p in archery.urls.urlpatterns:
    s = str(p.pattern)
    print(f'   pattern: {s}')

# 4. 关键: 看 ROOT_URLCONF 实际 urlpatterns 里是不是有 ddl_sync
from django.urls import get_resolver
print('4. get_resolver().url_patterns:')
for p in get_resolver().url_patterns:
    print(f'   {p.pattern}')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d9_check_urlconf.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d9_check_urlconf.py 2>&1',
    'rm -f /tmp/_d9_check_urlconf.py',
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
