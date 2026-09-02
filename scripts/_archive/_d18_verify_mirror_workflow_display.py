# -*- coding: utf-8 -*-
"""9/2 D18: 验证镜像工单 detail 页内容显示是否正常."""
import os
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    hostname="172.20.2.134", port=22, username="root",
    password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW",
    timeout=15,
)

def run(cmd, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out, err, stdout.channel.recv_exit_status()

# Step 1: 找最近的镜像工单
find_script = r'''
import os, sys
sys.path.insert(0, "/opt/archery/prod")
os.environ["DJANGO_SETTINGS_MODULE"] = "archery.settings"
import django
django.setup()

from sql.extensions.ddl_sync.models import DdlSyncHistory
from sql.models import SqlWorkflow

# 找最近的镜像工单 (DdlSyncHistory.target_workflow 关联的)
histories = DdlSyncHistory.objects.select_related(
    "pair", "target_workflow", "source_workflow"
).order_by("-created_at")[:5]

print(f"Recent DdlSyncHistory count: {histories.count()}")
for h in histories:
    print("=" * 60)
    print(f"History id={h.id} pair_id={h.pair_id} table={h.table_name}")
    print(f"  source_workflow_id={h.source_workflow_id} target_workflow_id={h.target_workflow_id}")
    print(f"  sync_status={h.sync_status} finished_at={h.finished_at}")
    print(f"  error_message={((h.error_message or '')[:150])}")
    if h.target_workflow_id:
        twf = h.target_workflow
        try:
            sql = twf.sqlworkflowcontent.sql_content
        except Exception as e:
            sql = f"(error: {e})"
        print(f"  TARGET wf#{twf.id}:")
        print(f"    workflow_name={twf.workflow_name}")
        print(f"    status={twf.status}")
        print(f"    group_id={twf.group_id} group_name={twf.group_name}")
        print(f"    instance={twf.instance.instance_name if twf.instance else None}")
        print(f"    db_name={twf.db_name}")
        print(f"    audit_auth_groups={twf.audit_auth_groups}")
        print(f"    SQL (200 chars): {((sql or '')[:200])}")
    else:
        print(f"  TARGET = None (skipped or not yet generated)")
    print()
'''

try:
    print("=" * 70)
    print("D18: 134 dev 找最近 5 个 DdlSyncHistory 看镜像工单")
    print("=" * 70)

    # 把脚本写远端临时文件
    sftp = ssh.open_sftp()
    with sftp.open("/tmp/_d18_find.py", "w") as f:
        f.write(find_script)
    sftp.chmod("/tmp/_d18_find.py", 0o755)
    sftp.close()

    cmd = "cd /opt/archery/prod && sudo -u archery venv/bin/python /tmp/_d18_find.py 2>&1 | tail -120"
    out, err, code = run(cmd, timeout=60)
    print(out)
    if err and "Warning" not in err:
        print(f"[stderr] {err[:500]}")

    print()
    print("=" * 70)
    print("Step 2: SSH 134 dev 查镜像工单的 audit_handler 状态")
    print("=" * 70)

    audit_script = r'''
import os, sys
sys.path.insert(0, "/opt/archery/prod")
os.environ["DJANGO_SETTINGS_MODULE"] = "archery.settings"
import django
django.setup()

from sql.models import SqlWorkflow, WorkflowAudit, SqlWorkflowContent
from sql.extensions.ddl_sync.models import DdlSyncHistory

# 找最近有 target_workflow 的 history
recent = DdlSyncHistory.objects.exclude(target_workflow__isnull=True).order_by("-created_at")[:3]
for h in recent:
    twf = h.target_workflow
    print(f"Mirror wf#{twf.id}:")
    print(f"  audit set: {WorkflowAudit.objects.filter(workflow_id=twf.id).count()}")
    audits = WorkflowAudit.objects.filter(workflow_id=twf.id)
    for a in audits:
        print(f"    audit#{a.audit_id} current_audit={a.current_audit} current_status={a.current_status} next_audit={a.next_audit}")
    print()
'''

    sftp = ssh.open_sftp()
    with sftp.open("/tmp/_d18_audit.py", "w") as f:
        f.write(audit_script)
    sftp.chmod("/tmp/_d18_audit.py", 0o755)
    sftp.close()

    cmd = "cd /opt/archery/prod && sudo -u archery venv/bin/python /tmp/_d18_audit.py 2>&1 | tail -40"
    out, err, code = run(cmd, timeout=60)
    print(out)
    if err and "Warning" not in err:
        print(f"[stderr] {err[:500]}")

finally:
    ssh.close()
