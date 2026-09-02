# -*- coding: utf-8 -*-
"""9/2 D18: 查源工单状态 + DdlSyncHistory 反查 source_workflow link."""
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

from sql.models import SqlWorkflow
from sql.extensions.ddl_sync.models import DdlSyncHistory

# 查源工单 #118 状态
print("=" * 70)
print("1. 源工单 #118 状态 (是 wf#119 的 source_workflow)")
print("=" * 70)
swf = SqlWorkflow.objects.get(id=118)
print(f"  workflow_name: {swf.workflow_name}")
print(f"  status: {swf.status}")
print(f"  group_id: {swf.group_id} group_name: {swf.group_name}")
print(f"  instance: {swf.instance.instance_name if swf.instance else None}")
print(f"  db_name: {swf.db_name}")
print(f"  create_time: {swf.create_time}")
print(f"  finish_time: {swf.finish_time}")
print()

# 查 DdlSyncHistory 跟 source_workflow 反向关联
print("=" * 70)
print("2. DdlSyncHistory 反向查询 (通过 source_workflow_id)")
print("=" * 70)
print("DdlSyncHistory._meta.get_fields():")
from django.db.models import ForeignKey
for f in DdlSyncHistory._meta.get_fields():
    if isinstance(f, ForeignKey):
        print(f"  {f.name} -> {f.related_model.__name__ if f.related_model else None}")

# 实际看 source_workflow 反查
hist_by_src = DdlSyncHistory.objects.filter(source_workflow_id=118)
print(f"\nDdlSyncHistory.filter(source_workflow_id=118) count: {hist_by_src.count()}")
for h in hist_by_src:
    print(f"  History id={h.id} target_wf#{h.target_workflow_id} sync_status={h.sync_status}")

# 实际看 target_workflow 反查
hist_by_tgt = DdlSyncHistory.objects.filter(target_workflow_id=119)
print(f"\nDdlSyncHistory.filter(target_workflow_id=119) count: {hist_by_tgt.count()}")
for h in hist_by_tgt:
    print(f"  History id={h.id} source_wf#{h.source_workflow_id} sync_status={h.sync_status}")

# SqlWorkflow 反向查询 (related_name 是什么)
print()
print("=" * 70)
print("3. SqlWorkflow 反向查询 ddl_sync_history_set (related_name 验证)")
print("=" * 70)
swf_with_hist = SqlWorkflow.objects.get(id=118)
if hasattr(swf_with_hist, "ddl_sync_history_set"):
    print(f"  swf#118.ddl_sync_history_set: {swf_with_hist.ddl_sync_history_set.count()}")
else:
    print(f"  swf#118 没有 ddl_sync_history_set 属性 (related_name 没设)")
    # 找可能的 related_name
    for attr in dir(swf_with_hist):
        if "history" in attr.lower() or "ddl_sync" in attr.lower():
            print(f"  候选属性: {attr}")

# 找 syncing 状态的 history (没 abort 的)
print()
print("=" * 70)
print("4. 现在还有 sync_status=syncing 的镜像工单吗")
print("=" * 70)
syncing = DdlSyncHistory.objects.filter(sync_status="syncing")
print(f"syncing count: {syncing.count()}")
for h in syncing[:5]:
    print(f"  hist#{h.id} source_wf#{h.source_workflow_id} target_wf#{h.target_workflow_id} table={h.table_name}")
'''

try:
    sftp = ssh.open_sftp()
    with sftp.open("/tmp/_d18_check.py", "w") as f:
        f.write(check_script)
    sftp.chmod("/tmp/_d18_check.py", 0o755)
    sftp.close()

    cmd = "cd /opt/archery/prod && sudo -u archery venv/bin/python /tmp/_d18_check.py 2>&1 | tail -80"
    out, err, code = run(cmd, timeout=60)
    print(out)
    if err and "Warning" not in err:
        print(f"[stderr] {err[:500]}")

finally:
    ssh.close()
