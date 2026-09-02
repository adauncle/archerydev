#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D10 演练 Case A: 配 1 个真实库对 hly_accesscard → archery_dev (DBA 视角)
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

from django.contrib.auth import get_user_model
from sql.models import Instance
from sql.extensions.ddl_sync.models import DdlSyncPair, DdlSyncTable, DdlSyncHistory

# 1. 找 superuser 当 created_by
Users = get_user_model()
admin_user = Users.objects.filter(is_superuser=True).first()
if not admin_user:
    admin_user = Users.objects.first()
print(f'1. created_by: {admin_user.username}')

# 2. 拿 instance 1
archery_ins = Instance.objects.get(id=1)
print(f'2. instance: {archery_ins.instance_name} {archery_ins.host}:{archery_ins.port}')

# 3. 看是否已配过 (避免重复)
existing = DdlSyncPair.objects.filter(
    source_instance=archery_ins,
    source_db='hly_accesscard',
    target_instance=archery_ins,
    target_db='archery_dev',
).first()
if existing:
    print(f'3. 已存在库对 id={existing.id}, 删除重来')
    existing.delete()

# 4. 配新库对 (sync_mode=blacklist R1 默认)
pair = DdlSyncPair.objects.create(
    name='accesscard 库对 (134 dev 演练)',
    source_instance=archery_ins,
    source_db='hly_accesscard',
    target_instance=archery_ins,
    target_db='archery_dev',
    sync_mode='blacklist',  # R1 默认
    enabled=True,
    created_by=admin_user,
)
print(f'4. 库对创建: id={pair.id} name={pair.name}')
print(f'   source: {pair.source_instance.instance_name}/{pair.source_db}')
print(f'   target: {pair.target_instance.instance_name}/{pair.target_db}')
print(f'   sync_mode={pair.sync_mode} enabled={pair.enabled}')

# 5. 验证库对 + form 校验
print()
print('--- Case A 验证 ---')
print(f'  库对总数: {DdlSyncPair.objects.count()}')
print(f'  pair.id: {pair.id}')
print(f'  pair.tables.count() (配后空): {pair.tables.count()}')
print(f'  pair.history.count() (无历史): {pair.history.count()}')

# 6. 业务/历史库不能同 instance+db 校验 (D7 forms.py 实战)
from sql.extensions.ddl_sync.forms import DdlSyncPairForm
print()
print('--- Case A forms 校验 ---')
# 同 instance+db 业务+历史库应该 raise ValidationError
form_data = {
    'name': '错误: 同库对',
    'source_instance': archery_ins.id,
    'source_db': 'archery_dev',
    'target_instance': archery_ins.id,
    'target_db': 'archery_dev',  # 同 db
    'sync_mode': 'blacklist',
    'enabled': True,
}
form = DdlSyncPairForm(data=form_data)
if not form.is_valid():
    print(f'  校验失败 (期望): {form.errors}')
else:
    print('  校验通过 (意外, 应该报错同库!)')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d10_case_a.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d10_case_a.py 2>&1',
    'rm -f /tmp/_d10_case_a.py',
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
