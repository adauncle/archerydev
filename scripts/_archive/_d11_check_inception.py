#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11 解决: 134 dev inception backup 配错 (业务库 #109 报 Invalid remote backup information)
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

from common.config import SysConfig
sc = SysConfig()

print('=== 1. 134 dev sys_config inception backup 配置 ===')
keys = [
    'inception_backup_host',
    'inception_backup_port',
    'inception_backup_user',
    'inception_backup_password',
    'inception_backup_db',
    'inception_remote_backup_url',
    'inception',
    'inception_host',
    'inception_port',
    'inception_user',
    'inception_password',
    'enable_backup_switch',
]
for k in keys:
    v = sc.get(k)
    print(f'  {k}: {v if v is not None else "(not set)"}')

print()
print('=== 2. 看 inception backup 走 sys_config 还是 env ===')
print(f'  archery.settings ENABLE_INCEPTION: ', end='')
from django.conf import settings
print(getattr(settings, 'INCEPTION_BACKUP_HOST', 'NOT_SET'))
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d11_inception.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d11_inception.py 2>&1',
    'rm -f /tmp/_d11_inception.py',
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
