#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D9 阶段 1 最终验证: 修 weakref dereference 重新查 receivers
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

from django.db.models.signals import post_save

# 1. 查 workflow_passed_handler 是否注册 (用 weakref dereference)
is_registered = False
all_handlers = []
for receiver_tuple in post_save.receivers:
    recv_ref = receiver_tuple[1]
    # weakref 需要 () 拿真函数
    if hasattr(recv_ref, '__call__') and not hasattr(recv_ref, '__name__'):
        # 像 weakref: 调它拿目标
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
print('1. workflow_passed_handler is in post_save receivers:', is_registered)
print('1. all handlers:', all_handlers)

# 2. 查 SqlWorkflow._signal_backrefs (Django 内部 signal 反向查)
from sql.models import SqlWorkflow
signal_list = [s for s in post_save.receivers if callable(s[1]) and getattr(s[1], '__name__', None) == 'workflow_passed_handler']
print('2. direct count via callable check:', len(signal_list))

# 3. 模拟一次业务库 DDL PASSED, 验证 signal 触发完整链路
# 不实际写库, 只查 DdlSyncPair 找配对
from sql.extensions.ddl_sync.models import DdlSyncPair
print('3. DdlSyncPair 数量:', DdlSyncPair.objects.count())

# 4. 查 DdlSyncHistory (应为空, signal 还没实际触发)
from sql.extensions.ddl_sync.models import DdlSyncHistory
print('4. DdlSyncHistory 数量:', DdlSyncHistory.objects.count())

# 5. 验 sync_trigger 跟 models 都能 import
from sql.extensions.ddl_sync.services.sync_trigger import workflow_passed_handler, create_target_workflow
print('5. workflow_passed_handler:', workflow_passed_handler)
print('5. create_target_workflow:', create_target_workflow)
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d9_signal_ok.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d9_signal_ok.py 2>&1',
    'rm -f /tmp/_d9_signal_ok.py',
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
