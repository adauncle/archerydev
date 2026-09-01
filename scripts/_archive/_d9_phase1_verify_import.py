#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D9 阶段 1 验证: manage.py shell 跑 sync_trigger import + _extract_table_name + signal 注册
"""
import io
import sys
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DEV_HOST = '172.20.2.134'
DEV_PORT = 22
DEV_USER = 'root'
DEV_PASS = 'CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW'

# 用 here-doc 避免 bash 引号问题
TEST_CODE = """
import django
django.setup()

# 1. import sync_trigger 模块
from sql.extensions.ddl_sync.services.sync_trigger import (
    workflow_passed_handler, create_target_workflow,
    _extract_table_name, _should_sync, _apply_transform_rule,
)
print('1. sync_trigger imports OK')

# 2. _extract_table_name 解析 ALTER TABLE
print('2. _extract_table_name 测试:')
print('  ALTER TABLE accesscard_black_detail:', repr(_extract_table_name('ALTER TABLE `accesscard_black_detail` ADD COLUMN x INT;')))
print('  ALTER TABLE hly_doc.foo:', repr(_extract_table_name('ALTER TABLE hly_doc.foo ADD COLUMN y INT;')))
print('  空:', repr(_extract_table_name('')))
print('  CREATE TABLE:', repr(_extract_table_name('CREATE TABLE foo (x INT);')))
print('  ALTER TABLE 带 schema 跟表名:', repr(_extract_table_name('ALTER TABLE hly_activity.log_2024 ENGINE=InnoDB;')))

# 3. signal handler 已经被注册
from django.db.models.signals import post_save
from sql.models import SqlWorkflow
is_registered = False
for receiver_tuple in post_save.receivers:
    if len(receiver_tuple) >= 2:
        recv = receiver_tuple[1]
        if callable(recv) and getattr(recv, '__name__', None) == 'workflow_passed_handler':
            is_registered = True
            break
print('3. workflow_passed_handler is in post_save receivers:', is_registered)
"""

REMOTE_CMDS = [
    # 写测试代码到文件 + manage.py shell 执行
    f'cd /opt/archery/prod && cat > /tmp/_d9_verify.py << "PYEOF"\n{TEST_CODE}\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d9_verify.py 2>&1',
    'rm -f /tmp/_d9_verify.py',
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
