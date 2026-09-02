"""D11 实战 - kill + 拉新 + 端点 + render"""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)
print("connected", flush=True)

# 拉新 gunicorn (用 disown 脱钩)
cmd = "cd /opt/archery/prod && nohup venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 > /tmp/gunicorn_134.log 2>&1 & disown"
print("starting gunicorn (disown)...", flush=True)
si, so, se = ssh.exec_command(cmd, timeout=5)
print("start ok", flush=True)

time.sleep(5)

# 验证
def run(c, t=10):
    si, so, se = ssh.exec_command(c, timeout=t)
    return so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")

out, _ = run("pgrep -f gunicorn | head -10")
print(f"new pids: {out.strip()}", flush=True)
out, _ = run("ss -tlnp 2>/dev/null | grep 9003 || netstat -tlnp 2>/dev/null | grep 9003")
print(f"9003 port: {out.strip()}", flush=True)

# 端点 verify
print("\n=== 5 端点 verify ===", flush=True)
for ep in ["/login/", "/", "/admin/", "/ddl_sync/pair/list/", "/static/ddl_sync/pair_detail.js"]:
    out, _ = run(f"curl -sS -m 5 -o /dev/null -w 'HTTP:%{{http_code}}' 'http://127.0.0.1:9003{ep}'")
    print(f"  {ep:40s} {out.strip()}", flush=True)

# detail/119 实际渲染
print("\n=== detail/119 渲染 (新 gunicorn) ===", flush=True)
out, _ = run("sudo -u archery bash -lc 'cd /opt/archery/prod && /opt/archery/prod/venv/bin/python /tmp/d11_render_v3.py' 2>&1")
print(out[-500:], flush=True)
out, _ = run("grep -n 'var dbName\\|var sqlContent' /tmp/d11_detail119_render.html | head -5")
print(f"grep: {out.strip()}", flush=True)

# Django check
print("\n=== Django check ddl_sync ===", flush=True)
out, _ = run("cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py check ddl_sync 2>&1 | tail -3")
print(out, flush=True)

ssh.close()
print("\nDONE", flush=True)
