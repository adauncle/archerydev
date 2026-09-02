#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D10 验 sync_trigger 修后 import OK
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

from sql.extensions.ddl_sync.services.sync_trigger import (
    _should_sync, create_target_workflow,
    _extract_table_name, _apply_transform_rule, workflow_passed_handler,
)
print('5 函数 import OK')

# 验 _should_sync 修后能 import
from sql.extensions.ddl_sync.models import DdlSyncPair
pair = DdlSyncPair.objects.first()
if pair:
    r1 = _should_sync(pair, 'accesscard_account')
    r2 = _should_sync(pair, 'nonexistent_table')
    print(f'_should_sync test 1 (白名单 accesscard_account): {r1}')
    print(f'_should_sync test 2 (不在任何名单 nonexistent): {r2}')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d10_verify.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d10_verify.py 2>&1',
    'rm -f /tmp/_d10_verify.py',
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
