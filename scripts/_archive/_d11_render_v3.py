"""D11 实战 - archery 用户跑 detail/119 render + 验证"""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)
sftp = ssh.open_sftp()

# render 脚本 (改成 archery 用户跑)
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
with sftp.file("/tmp/d11_render_v3.py", "w") as f:
    f.write(render_script)
sftp.close()

# 上传 one_shot 改用 archery 跑
one_shot = r'''#!/bin/bash
# detail/119 render (archery 用户)
sudo -u archery /opt/archery/prod/venv/bin/python /tmp/d11_render_v3.py 2>&1
echo "---grep var dbName---"
grep -n 'var dbName\|var sqlContent\|var instanceId\|hly_accesscard_history' /tmp/d11_detail119_render.html | head -10
echo "---Django check---"
cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py check ddl_sync 2>&1 | tail -5
echo "---md5---"
md5sum /opt/archery/prod/sql/templates/detail.html /opt/archery/prod/sql/views.py
echo "---gunicorn---"
ps -eo pid,ppid,etime,cmd | grep gunicorn | grep -v grep
echo "DONE"
'''
with sftp.file("/tmp/d11_one_shot_v2.sh", "w") as f:
    f.write(one_shot)
sftp.chmod("/tmp/d11_one_shot_v2.sh", 0o755)
sftp.close()

print("=== exec one_shot v2 ===", flush=True)
si, so, se = ssh.exec_command("bash /tmp/d11_one_shot_v2.sh 2>&1", timeout=60)
out = so.read().decode("utf-8", errors="replace")
err = se.read().decode("utf-8", errors="replace")
print(out, flush=True)
if err: print("ERR:", err, flush=True)

ssh.close()
print("DONE")
