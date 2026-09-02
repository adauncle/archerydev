"""D11 紧急修复 - mv 失败 gunicorn 已 kill, 用 root 直接 cp + chown + 拉新"""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)

def run(cmd, t=30):
    print(f"  $ {cmd}", flush=True)
    si, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode("utf-8", errors="replace")
    err = se.read().decode("utf-8", errors="replace")
    if out.strip(): print(f"  >>> {out.strip()[:300]}", flush=True)
    if err.strip(): print(f"  ERR: {err.strip()[:300]}", flush=True)
    return out, err

# 1. 看 /tmp/_push 文件是否还在
print("\n[1] /tmp/_push 文件状态")
run("ls -la /tmp/_push_* 2>&1")

# 2. 看 /opt/archery/prod 父目录权限
print("\n[2] /opt/archery/prod 权限")
run("ls -ld /opt/archery/prod /opt/archery/prod/sql /opt/archery/prod/sql/templates 2>&1")

# 3. 用 root 直接 cp 覆盖 (避开 sudo mv 权限问题)
print("\n[3] root cp 覆盖 + chown")
run("cp /tmp/_push_detail.html /opt/archery/prod/sql/templates/detail.html && chown archery:archery /opt/archery/prod/sql/templates/detail.html && ls -la /opt/archery/prod/sql/templates/detail.html")
run("cp /tmp/_push_views.py /opt/archery/prod/sql/views.py && chown archery:archery /opt/archery/prod/sql/views.py && ls -la /opt/archery/prod/sql/views.py")

# 4. md5 验证
print("\n[4] md5 验证")
run("md5sum /opt/archery/prod/sql/templates/detail.html /opt/archery/prod/sql/views.py")

# 5. 清 __pycache__
print("\n[5] 清 __pycache__")
run("find /opt/archery/prod -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true")
out, _ = run("find /opt/archery/prod -type d -name __pycache__ 2>/dev/null | wc -l")
print(f"  剩余 __pycache__ 数: {out.strip()}")

# 6. 看 gunicorn 状态
print("\n[6] gunicorn 状态")
out, _ = run("pgrep -f 'gunicorn archery.wsgi' | head -5 || true")
print(f"  当前 gunicorn: {out.strip() or '无'}")

# 7. 拉新 gunicorn (D7 阶段 1 实战套路: setsid nohup)
print("\n[7] nohup 拉新 gunicorn")
gunicorn_cmd = (
    "cd /opt/archery/prod && "
    "setsid nohup venv/bin/gunicorn archery.wsgi:application "
    "-w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 "
    "> /tmp/gunicorn_134.log 2>&1 &"
)
run(gunicorn_cmd)
time.sleep(4)
out, _ = run("pgrep -f 'gunicorn archery.wsgi' | head -10")
print(f"  新 gunicorn pids: {out.strip()}")

# 8. 端点 verify
print("\n[8] 12 端点 verify")
endpoints = [
    ("/login/", 200),
    ("/", 302),
    ("/admin/", 302),
    ("/dbaprinciples/", 302),
    ("/sqlworkflow/", 302),
    ("/api/v1/ddl-sync/pairs/", 302),
    ("/api/v1/ddl-sync/pairs/1/", 302),
    ("/api/v1/ddl-sync/pairs/1/tables/", 302),
    ("/api/v1/ddl-sync/pairs/1/history/", 302),
    ("/api/v1/ddl-sync/diff/", 302),
    ("/static/ddl_sync/pair_detail.js", 200),
]
for ep, expect in endpoints:
    out, _ = run(f"curl -sS -o /dev/null -w 'HTTP:%{{http_code}}' 'http://127.0.0.1:9003{ep}'")
    code = out.strip().replace("HTTP:", "")
    ok = (int(code) == expect) if code.isdigit() else False
    flag = "✓" if ok else "✗"
    print(f"  {flag} {ep:50s} expect={expect} got={code}", flush=True)

# 9. Django check
print("\n[9] Django check ddl_sync")
run("cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py check ddl_sync 2>&1 | tail -5")

# 10. detail/119 实际渲染验证 var dbName 带引号
print("\n[10] detail/119 实际渲染验证")
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
ctx = {
    "workflow_detail": wf,
    "sql_content_for_diff": json.dumps(_workflow_sql_text(wf)),
    "instance_id_for_diff": wf.instance_id or 0,
    "db_name_for_diff": json.dumps(wf.db_name or ""),
}
html = render_to_string("detail.html", ctx, request=RequestFactory().get("/detail/119/"))
with open("/tmp/d11_detail119_fixed.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"rendered {len(html)} bytes", flush=True)
'''
sftp = ssh.open_sftp()
with sftp.file("/tmp/d11_render_check.py", "w") as f:
    f.write(render_script)
sftp.close()
run("sudo -u archery bash -lc 'cd /opt/archery/prod && /opt/archery/prod/venv/bin/python /tmp/d11_render_check.py'")
run("grep -n 'var dbName\\|var sqlContent\\|var instanceId\\|hly_accesscard_history' /tmp/d11_detail119_fixed.html | head -10")

ssh.close()
print("\nDONE")
