# -*- coding: utf-8 -*-
"""9/3 D19: 查 wf#121 镜像工单 sql_content + 实战演练."""
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

check_script = r'''
import os, sys
sys.path.insert(0, "/opt/archery/prod")
os.environ["DJANGO_SETTINGS_MODULE"] = "archery.settings"
import django
django.setup()

from sql.models import SqlWorkflow, SqlWorkflowContent
from sql.extensions.ddl_sync.models import DdlSyncHistory

# 查 wf#121 镜像工单
print("=" * 70)
print("wf#121 镜像工单 sql_content")
print("=" * 70)
swf = SqlWorkflow.objects.get(id=121)
print(f"  workflow_name: {swf.workflow_name}")
print(f"  status: {swf.status}")
print(f"  group_name: {swf.group_name}")
print(f"  instance: {swf.instance.instance_name if swf.instance else None}")
print(f"  db_name: {swf.db_name}")
try:
    content = swf.sqlworkflowcontent
    sql = content.sql_content if content else None
    print(f"  sqlworkflowcontent exists: {content is not None}")
    print(f"  sql_content length: {len(sql) if sql else 0}")
    print(f"  sql_content:")
    print(f"    >>>{sql}<<<")
except Exception as e:
    print(f"  sqlworkflowcontent ERROR: {e}")

print()
print("=" * 70)
print("wf#120 源工单 sql_content (对比)")
print("=" * 70)
swf2 = SqlWorkflow.objects.get(id=120)
print(f"  workflow_name: {swf2.workflow_name}")
print(f"  status: {swf2.status}")
try:
    content2 = swf2.sqlworkflowcontent
    sql2 = content2.sql_content if content2 else None
    print(f"  sql_content length: {len(sql2) if sql2 else 0}")
    print(f"  sql_content:")
    print(f"    >>>{sql2}<<<")
except Exception as e:
    print(f"  sqlworkflowcontent ERROR: {e}")

print()
print("=" * 70)
print("DdlSyncHistory 跟 wf#121 关联")
print("=" * 70)
hist = DdlSyncHistory.objects.filter(target_workflow_id=121).first()
if hist:
    print(f"  hist#{hist.id} source_wf#{hist.source_workflow_id} target_wf#{hist.target_workflow_id} sync_status={hist.sync_status}")
    print(f"  pair: {hist.pair.name if hist.pair else None}")
    print(f"  table_name: {hist.table_name}")
    print(f"  error_message: {(hist.error_message or '')[:200]}")
else:
    print("  No DdlSyncHistory for wf#121")

# 也查 wf#119 (D18 实战那个) 对比
print()
print("=" * 70)
print("wf#119 镜像工单 sql_content (D18 实战那个)")
print("=" * 70)
try:
    swf3 = SqlWorkflow.objects.get(id=119)
    try:
        content3 = swf3.sqlworkflowcontent
        sql3 = content3.sql_content if content3 else None
        print(f"  sql_content length: {len(sql3) if sql3 else 0}")
        print(f"  sql_content:")
        print(f"    >>>{sql3}<<<")
    except Exception as e:
        print(f"  sqlworkflowcontent ERROR: {e}")
except Exception as e:
    print(f"  wf#119 not found: {e}")
'''

try:
    print("=" * 70)
    print("D19: 查 wf#121 镜像工单 sql_content + 源工单 + DdlSyncHistory")
    print("=" * 70)

    sftp = ssh.open_sftp()
    with sftp.open("/tmp/_d19_check.py", "w") as f:
        f.write(check_script)
    sftp.chmod("/tmp/_d19_check.py", 0o755)
    sftp.close()

    cmd = "cd /opt/archery/prod && sudo -u archery venv/bin/python /tmp/_d19_check.py 2>&1 | tail -60"
    out, err, code = run(cmd, timeout=60)
    print(out)
    if err and "Warning" not in err:
        print(f"[stderr] {err[:500]}")

finally:
    ssh.close()
