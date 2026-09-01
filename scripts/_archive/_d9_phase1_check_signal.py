#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D9 阶段 1 验证: apps.ready() 是不是真的跑过 + signal 注册流程
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

# 1. 看 DdlSyncConfig.ready 是从哪 import
from sql.extensions.ddl_sync.apps import DdlSyncConfig
print('1. DdlSyncConfig name:', DdlSyncConfig.name)
print('1. DdlSyncConfig ready source:')
import inspect
print(inspect.getsource(DdlSyncConfig.ready))

# 2. 看 apps.get_app_configs 是不是 DdlSyncConfig 真的注册了
from django.apps import apps
ddl_sync_config = apps.get_app_config('ddl_sync')
print('2. apps.get_app_config(ddl_sync):', ddl_sync_config)
print('2. config.__class__:', ddl_sync_config.__class__)

# 3. 强制调 ready() 看 import 跑没跑
try:
    ddl_sync_config.ready()
    print('3. ready() called, no exception')
except Exception as e:
    print('3. ready() exception:', e)

# 4. 再查 post_save receivers
from django.db.models.signals import post_save
from sql.models import SqlWorkflow
is_registered = False
for receiver_tuple in post_save.receivers:
    if len(receiver_tuple) >= 2:
        recv = receiver_tuple[1]
        if callable(recv) and getattr(recv, '__name__', None) == 'workflow_passed_handler':
            is_registered = True
            break
print('4. workflow_passed_handler in post_save receivers:', is_registered)

# 5. 看 post_save.receivers 全部内容
print('5. post_save.receivers count:', len(post_save.receivers))
for r in post_save.receivers[:5]:
    print('   ', r)
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d9_check_signal.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d9_check_signal.py 2>&1',
    'rm -f /tmp/_d9_check_signal.py',
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
