"""D11 实战 - 直接在 134 dev 上 Django shell render detail/119 不需要 login"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)

# 134 dev gunicorn 是 sudo -u archery 跑的
# 写一个 Python 脚本到 /tmp, 用 archery 用户的 venv + archery.settings 直接 render
# 但要先知道 archery 用户的 shell

render_script = r'''
import os, sys, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
sys.path.insert(0, "/opt/archery/prod")
import django
django.setup()

from django.template.loader import render_to_string
from django.test import RequestFactory
from sql.models import SqlWorkflow

wf = SqlWorkflow.objects.get(id=119)
print(f"wf.id={wf.id} status={wf.status} db_name={wf.db_name} instance_id={wf.instance_id}", flush=True)

# 模拟 view 端实际传的 context (从 sql/views.py detail 抄关键变量)
# 简化版: 直接模拟 view 端 json.dumps 包过
from sql.views import _workflow_sql_text
ctx = {
    "workflow_detail": wf,
    "sql_content_for_diff": json.dumps(_workflow_sql_text(wf)),
    "instance_id_for_diff": wf.instance_id or 0,
    "db_name_for_diff": json.dumps(wf.db_name or ""),
}
html = render_to_string("detail.html", ctx, request=RequestFactory().get("/detail/119/"))
# 输出到 /tmp
with open("/tmp/d11_render_119.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"rendered {len(html)} bytes", flush=True)
'''

sftp = ssh.open_sftp()
with sftp.open("/tmp/render119.py", "w") as f:
    f.write(render_script)
sftp.close()

# 用 archery 用户的 venv 跑
cmd = """sudo -u archery bash -lc 'cd /opt/archery/prod && /opt/archery/prod/venv/bin/python /tmp/render119.py' 2>&1"""
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
print("STDOUT:", stdout.read().decode())
print("STDERR:", stderr.read().decode())

# 现在看 line 1948-1965
cmd2 = """awk 'NR>=1948 && NR<=1965 {print NR": "$0}' /tmp/d11_render_119.html"""
stdin, stdout, stderr = ssh.exec_command(cmd2)
print("=== Lines 1948-1965 ===")
print(stdout.read().decode())

# 找 var dbName / var sqlContent / hly_accesscard_history
cmd3 = """grep -n 'var dbName\\|var sqlContent\\|var instanceId\\|hly_accesscard_history\\|fetchColumnDiff' /tmp/d11_render_119.html | head -30"""
stdin, stdout, stderr = ssh.exec_command(cmd3)
print("=== grep var ===")
print(stdout.read().decode())

ssh.close()
