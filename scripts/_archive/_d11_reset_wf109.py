#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11 解决: 重置工单 #109 is_backup=False + status=workflow_manreviewing + 清空 error
实战: 4 个 inception_remote_backup_* 已清空, 让工单重新 execute 走 no-op backup
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
from django.utils import timezone

# 1. 重置工单 #109
wf = SqlWorkflow.objects.get(id=109)
print(f'重置前: status={wf.status} is_backup={wf.is_backup}')

# 实战: 让 execute() 走 --backup=1 但 inception 内部 backup_conn 失败 (4 个 host/port/user/password 空)
# 实战更稳: is_backup=False 不走 --backup=1
wf.is_backup = False
wf.status = 'workflow_manreviewing'  # 改回待审, 业务组+DBA 重审
wf.finish_time = None

# 清空 error_message (execute_result 跟 review_content 也清)
try:
    wc = wf.sqlworkflowcontent
    wc.execute_result = ''
    wc.save()
except SqlWorkflowContent.DoesNotExist:
    pass

wf.save()
print(f'重置后: status={wf.status} is_backup={wf.is_backup}')

# 2. 同步重置 audit.current_status (改回待审状态, 让业务组+DBA 重新审)
audit = WorkflowAudit.objects.filter(workflow_id=109, workflow_type=2).first()
if audit:
    audit.current_status = WorkflowStatus.WAITING  # 待审
    audit.save()
    print(f'audit 重置: current_status={audit.current_status}')

# 3. 同步重置 DdlSyncHistory id=3 (R3 已经触发了, 但工单 #110 镜像工单也重置)
# 不重置 DdlSyncHistory — 它是 R3 的产物, 真实记录, 不能改
histories = [3]
print()
print('--- DdlSyncHistory id=3 (R3 触发的历史) ---')
for h_id in histories:
    from sql.extensions.ddl_sync.models import DdlSyncHistory
    h = DdlSyncHistory.objects.get(id=h_id)
    print(f'  history.id={h.id} sync_status={h.sync_status} target_workflow_id={h.target_workflow_id}')

# 4. 同步 #110 镜像工单 (R3 创建的镜像工单) 也重置
mirror_wf = SqlWorkflow.objects.filter(id=110).first()
if mirror_wf:
    print()
    print(f'--- 镜像工单 #110 (R3 创建) ---')
    print(f'重置前: status={mirror_wf.status} is_backup={mirror_wf.is_backup}')
    mirror_wf.is_backup = False  # 同步关 backup
    mirror_wf.status = 'workflow_manreviewing'
    mirror_wf.finish_time = None
    try:
        mwc = mirror_wf.sqlworkflowcontent
        mwc.execute_result = ''
        mwc.save()
    except SqlWorkflowContent.DoesNotExist:
        pass
    mirror_wf.save()
    print(f'重置后: status={mirror_wf.status} is_backup={mirror_wf.is_backup}')

    # 镜像工单 audit
    mirror_audit = WorkflowAudit.objects.filter(workflow_id=110, workflow_type=2).first()
    if mirror_audit:
        mirror_audit.current_status = WorkflowStatus.WAITING
        mirror_audit.save()
        print(f'镜像工单 audit 重置: current_status={mirror_audit.current_status}')

print()
print('=== 重置完成 ===')
print(f'工单 #109 (业务库) + #110 (镜像工单) 都重置到 workflow_manreviewing + is_backup=False')
print(f'请重新走 1 次 execute (DBA 手动审 + 选 auto/manual 模式)')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d11_reset.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d11_reset.py 2>&1',
    'rm -f /tmp/_d11_reset.py',
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
