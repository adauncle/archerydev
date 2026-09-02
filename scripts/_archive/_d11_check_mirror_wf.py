#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11 排查: 业务库工单 #109 R3 触发了没, 镜像工单 (应该 #110) 创建了没
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

from sql.models import SqlWorkflow, SqlWorkflowContent
from sql.extensions.ddl_sync.models import DdlSyncHistory

# 1. 业务库工单 #109 详情
print('--- 1. 业务库工单 #109 ---')
wf109 = SqlWorkflow.objects.filter(id=109).first()
if wf109:
    print(f'  id=109 engineer={wf109.engineer} status={wf109.status}')
    print(f'  instance={wf109.instance.instance_name} db_name={wf109.db_name}')
    print(f'  syntax_type={wf109.syntax_type} (1=DDL 2=DML)')
    try:
        print(f'  sql_content: {wf109.sqlworkflowcontent.sql_content[:200]}')
    except Exception as e:
        print(f'  sql_content err: {e}')

# 2. 业务库工单 #109 的 DdlSyncHistory
print()
print('--- 2. DdlSyncHistory for #109 ---')
histories = DdlSyncHistory.objects.filter(source_workflow_id=109).order_by('-created_at')
print(f'  DdlSyncHistory count: {histories.count()}')
for h in histories:
    pair = h.pair
    print(f'  history.id={h.id}')
    print(f'    pair: {pair.name} (#{pair.id}) source_db={pair.source_db} target_db={pair.target_db}')
    print(f'    target_workflow: {h.target_workflow_id}')
    print(f'    table_name: {h.table_name}')
    print(f'    sync_status: {h.sync_status}')
    print(f'    error_message: {h.error_message[:200] if h.error_message else ""}')
    print(f'    ddl_text: {h.ddl_text[:120] if h.ddl_text else ""}')

# 3. 最近 5 个工单 (看 #110/#111 是不是 R3 创建的镜像工单)
print()
print('--- 3. 最近 5 个 SqlWorkflow (找 R3 镜像工单) ---')
recent = SqlWorkflow.objects.all().order_by('-id')[:5]
for wf in recent:
    print(f'  id={wf.id} status={wf.status} engineer={wf.engineer}')
    print(f'    instance={wf.instance.instance_name} db_name={wf.db_name}')
    print(f'    workflow_name={wf.workflow_name}')
    print(f'    audit_auth_groups={wf.audit_auth_groups!r}')

# 4. 全部 DdlSyncHistory
print()
print('--- 4. 全部 DdlSyncHistory ---')
all_h = DdlSyncHistory.objects.all().order_by('-id')
for h in all_h:
    print(f'  id={h.id} pair_id={h.pair_id} source_wf={h.source_workflow_id} target_wf={h.target_workflow_id} table={h.table_name} status={h.sync_status} created={h.created_at}')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d11_check_wf.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d11_check_wf.py 2>&1',
    'rm -f /tmp/_d11_check_wf.py',
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
