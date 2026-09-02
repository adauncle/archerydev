"""D11 实战 - 上传 one_shot.sh + 上传 render 脚本 + 单次执行"""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)
sftp = ssh.open_sftp()

# 上传 one_shot.sh
local_sh = "G:/MiniMax工作空间/archery_dev/scripts/_archive/_d11_one_shot.sh"
sftp.put(local_sh, "/tmp/d11_one_shot.sh")
sftp.chmod("/tmp/d11_one_shot.sh", 0o755)

# 上传 render 脚本
render_script = r'''
import os, sys, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
sys.path.insert(0, "/opt/archery/prod")
import django
django.setup()
from django.template.loader import render_to_string
from django.test import RequestFactory
from sql.models import SqlWorkflow
from sql.views import _workflow_sql_text
wf = SqlWorkflow.objects.get(id=119)
print(f"wf.id={wf.id} db_name={wf.db_name} status={wf.status}", flush=True)
ctx = {
    "workflow_detail": wf,
    "sql_content_for_diff": json.dumps(_workflow_sql_text(wf)),
    "instance_id_for_diff": wf.instance_id or 0,
    "db_name_for_diff": json.dumps(wf.db_name or ""),
}
html = render_to_string("detail.html", ctx, request=RequestFactory().get("/detail/119/"))
with open("/tmp/d11_detail119_render.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"rendered {len(html)} bytes", flush=True)
'''
with sftp.file("/tmp/d11_render_v2.py", "w") as f:
    f.write(render_script)
sftp.close()

# 单次 bash 执行
print("=== exec one_shot ===", flush=True)
si, so, se = ssh.exec_command("bash /tmp/d11_one_shot.sh 2>&1", timeout=120)
out = so.read().decode("utf-8", errors="replace")
err = se.read().decode("utf-8", errors="replace")
print(out)
if err: print("ERR:", err, flush=True)

ssh.close()
print("DONE")
