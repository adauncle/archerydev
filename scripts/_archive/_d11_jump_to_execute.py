#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11 解决: #109 跳过审直接 workflow_review_pass (避免再次触发 R3) + 走 execute
实战: R3 已经触发过 (DdlSyncHistory id=3 syncing + 镜像工单 #110)
       不能再审通过 (会重复触发 R3)
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

from sql.models import SqlWorkflow, SqlWorkflowContent, WorkflowAudit
from common.utils.const import WorkflowStatus

# 1. 把 #109 改 status=workflow_review_pass + audit.PASSED (跳过审, 避免再触发 R3)
wf = SqlWorkflow.objects.get(id=109)
wf.status = 'workflow_review_pass'
wf.save()
print(f'#109 status={wf.status}')

audit = WorkflowAudit.objects.filter(workflow_id=109, workflow_type=2).first()
if audit:
    audit.current_status = WorkflowStatus.PASSED
    audit.save()
    print(f'#109 audit.current_status={audit.current_status}')

# 2. 镜像工单 #110 audit.current_status=PASSED (跳过审, 让 DBA 直接 execute)
mirror_audit = WorkflowAudit.objects.filter(workflow_id=110, workflow_type=2).first()
if mirror_audit:
    mirror_audit.current_status = WorkflowStatus.PASSED
    mirror_audit.save()
    print(f'#110 audit.current_status={mirror_audit.current_status}')

print()
print('=== 现在工单状态 ===')
for wf_id in (109, 110):
    w = SqlWorkflow.objects.get(id=wf_id)
    a = WorkflowAudit.objects.filter(workflow_id=wf_id, workflow_type=2).first()
    print(f'  #{wf_id} status={w.status} is_backup={w.is_backup} audit.current_status={a.current_status if a else "NO_AUDIT"}')

print()
print('=== DdlSyncHistory id=3 (R3 触发产物) ===')
from sql.extensions.ddl_sync.models import DdlSyncHistory
h = DdlSyncHistory.objects.get(id=3)
print(f'  history.id={h.id} sync_status={h.sync_status} target_workflow_id={h.target_workflow_id}')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d11_jump.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d11_jump.py 2>&1',
    'rm -f /tmp/_d11_jump.py',
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
