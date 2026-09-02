#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D10 演练准备: 看 134 dev 环境 (instance 配置 + 演练库对 + signal handler 状态)
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

from sql.models import Instance
from sql.extensions.ddl_sync.models import DdlSyncPair, DdlSyncTable, DdlSyncHistory
from sql.extensions.ddl_sync.services.sync_trigger import workflow_passed_handler, create_target_workflow
from django.db.models.signals import post_save

print('=== 1. instance 配置 ===')
instances = Instance.objects.all().order_by('id')
for ins in instances:
    print(f'  id={ins.id} {ins.instance_name} {ins.host}:{ins.port} type={ins.type}')

print()
print('=== 2. 已配的库对 ===')
for pair in DdlSyncPair.objects.all():
    print(f'  id={pair.id} name={pair.name}')
    print(f'    source: {pair.source_instance.instance_name} / {pair.source_db}')
    print(f'    target: {pair.target_instance.instance_name} / {pair.target_db}')
    print(f'    sync_mode={pair.sync_mode} enabled={pair.enabled}')
    print(f'    tables count: {pair.tables.count()}')
    print(f'    history count: {pair.history.count()}')

print()
print('=== 3. signal handler 状态 ===')
import weakref
is_registered = False
all_handlers = []
for receiver_tuple in post_save.receivers:
    recv_ref = receiver_tuple[1]
    if hasattr(recv_ref, '__call__') and not hasattr(recv_ref, '__name__'):
        try:
            recv = recv_ref()
        except TypeError:
            recv = recv_ref
    else:
        recv = recv_ref
    if recv is None:
        continue
    name = getattr(recv, '__name__', None) or '?'
    all_handlers.append(name)
    if name == 'workflow_passed_handler':
        is_registered = True
print(f'  post_save receivers: {all_handlers}')
print(f'  workflow_passed_handler registered: {is_registered}')

print()
print('=== 4. gunicorn + 应用服务状态 ===')
import os
import time
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d10_check_env.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d10_check_env.py 2>&1',
    'rm -f /tmp/_d10_check_env.py',
    'echo "--- gunicorn 状态 ---"',
    'ps -eo pid,etime,cmd | grep "gunicorn archery" | grep -v grep | head -3',
    'echo "--- 端口 9003 ---"',
    'ss -tnlp | grep 9003 || echo "9003 端口空"',
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
