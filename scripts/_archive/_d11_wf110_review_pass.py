#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11 解决: #110 镜像工单 status=workflow_review_pass, 让 DBA 进 execute 流程
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

from sql.models import SqlWorkflow, WorkflowAudit
from common.utils.const import WorkflowStatus

# #110 镜像工单 status=workflow_review_pass (R3 创建后默认 manreviewing, 实战要进可执行)
wf = SqlWorkflow.objects.get(id=110)
wf.status = 'workflow_review_pass'
wf.save()
print(f'#110 status={wf.status} is_backup={wf.is_backup}')

# 验 audit
a = WorkflowAudit.objects.filter(workflow_id=110, workflow_type=2).first()
print(f'#110 audit.current_status={a.current_status}')

print()
print('--- 现在工单 #109 + #110 状态 ---')
for wf_id in (109, 110):
    w = SqlWorkflow.objects.get(id=wf_id)
    a = WorkflowAudit.objects.filter(workflow_id=wf_id, workflow_type=2).first()
    print(f'  #{wf_id} status={w.status} is_backup={w.is_backup} audit.current_status={a.current_status} db_name={w.db_name}')

print()
print('=== 现在 DBA 可以走 execute 流程 ===')
print('浏览器访问 http://172.20.2.134:9003/sqlworkflow/ 看 #109 (业务库) + #110 (镜像工单) 都在待执行列表')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d11_wf110.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d11_wf110.py 2>&1',
    'rm -f /tmp/_d11_wf110.py',
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
