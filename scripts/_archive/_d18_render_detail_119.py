# -*- coding: utf-8 -*-
"""9/2 D18: 134 dev Django shell 模拟登录, 直接 render /detail/119/ 看实际内容."""
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

# Django shell 模拟登录, render /detail/119/
render_script = r'''
import os, sys
sys.path.insert(0, "/opt/archery/prod")
os.environ["DJANGO_SETTINGS_MODULE"] = "archery.settings"
import django
django.setup()

from django.test import Client
from sql.models import Users as User
from sql.models import SqlWorkflow

# 用 archery user (superuser)
archery = User.objects.get(username="archery")
client = Client(SERVER_NAME="127.0.0.1")
client.force_login(archery, backend="django.contrib.auth.backends.ModelBackend")

# render /detail/119/
resp = client.get("/detail/119/")
print(f"Status: {resp.status_code}")
print(f"Content-Type: {resp.get('Content-Type')}")
print(f"Content length: {len(resp.content)}")
print()

# 关键内容 grep
content = resp.content.decode("utf-8", errors="replace")
import re
checks = [
    ("镜像 关键词", r"\[镜像\]|镜像工单|ddl_sync"),
    ("workflow_name test", r"workflow_name|\[镜像\]"),
    ("SQL 内容 test1", r"add COLUMN test\d+|VARCHAR\(256\)"),
    ("目标库 hly_accesscard_history", r"hly_accesscard_history"),
    ("源库 hly_accesscard (前)", r"hly_accesscard(?![_a-z])"),
    ("源工单 link", r"/detail/11\d+/"),
    ("status 关键词", r"workflow_(manreviewing|abort|finish|review_pass|queuing)"),
    ("测试 MySQL 8.0", r"测试 MySQL 8.0"),
    ("audit_auth_groups 14,3", r"14,3|14,15,3"),
    ("workflow_detail id", r"workflow_detail.*119|workflow_id.*119|workflow_id.{0,20}119"),
    ("column_diff_result", r"column-diff-result|column_diff"),
    ("DdlSyncHistory tag", r"DdlSyncHistory|ddl_sync_history|target_workflow"),
    ("sla_todo / abort 链接", r"/cancel/|abort|todo"),
    ("table_name", r"accesscard_black_detail"),
]
for label, pat in checks:
    matches = re.findall(pat, content)
    print(f"  {label:35s} count={len(matches):3d} sample={matches[:2]}")

# 看 workflow_detail context
print()
print("=" * 70)
print("workflow_detail context 关键字段")
print("=" * 70)
import re
# 找 id / status / workflow_name / instance / db_name / group_name
for pat, label in [
    (r"workflow_id.{0,50}", "workflow_id"),
    (r"workflow_name.{0,100}", "workflow_name"),
    (r"status.{0,30}", "status"),
    (r"db_name.{0,50}", "db_name"),
    (r"group_name.{0,30}", "group_name"),
    (r"instance.{0,80}", "instance"),
]:
    matches = re.findall(pat, content)
    print(f"  {label}: {matches[:3]}")

# 看 SQL 显示块 (detail.html 的 sql_content 渲染区)
print()
print("=" * 70)
print("SQL 内容显示")
print("=" * 70)
# 找 add COLUMN 的整行
m = re.search(r"ALTER TABLE [^\"<>]+", content)
if m:
    print(f"SQL line: {m.group()[:200]}")
else:
    print("No ALTER TABLE in content")

# 找 sql_content / workflow-detail-sql 区域
m = re.search(r"<pre[^>]*>.*?ALTER TABLE.*?</pre>", content, re.DOTALL)
if m:
    print(f"SQL in <pre>: {m.group()[:300]}")
else:
    print("No <pre> with SQL")

# 找 source workflow 关联 (是否有跳回原工单的 link)
print()
print("=" * 70)
print("源工单关联显示")
print("=" * 70)
# 找 wf#118 链接 (源工单)
m = re.findall(r'href="(/detail/11[0-9]+/)"', content)
print(f"  内部 detail link: {m[:5]}")
# 找 source / 源 / 原工单
m = re.findall(r"(源|原|source).{0,30}工单|工单.{0,30}(源|原|source)", content)
print(f"  源/原/source 工单: {m[:3]}")

# status badge
print()
print("=" * 70)
print("status 徽章 / 链接")
print("-" * 70)
m = re.findall(r"workflow_(manreviewing|abort|finish|review_pass|queuning)", content)
print(f"status 出现: {m}")
'''

try:
    print("=" * 70)
    print("D18: 134 dev Django test client render /detail/119/")
    print("=" * 70)

    sftp = ssh.open_sftp()
    with sftp.open("/tmp/_d18_render.py", "w") as f:
        f.write(render_script)
    sftp.chmod("/tmp/_d18_render.py", 0o755)
    sftp.close()

    cmd = "cd /opt/archery/prod && sudo -u archery venv/bin/python /tmp/_d18_render.py 2>&1 | tail -150"
    out, err, code = run(cmd, timeout=60)
    print(out)
    if err and "Warning" not in err:
        print(f"[stderr] {err[:500]}")

finally:
    ssh.close()
