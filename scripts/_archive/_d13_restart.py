"""D13 实战 - kill gunicorn 拉新"""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)
print("connected", flush=True)

def run(c, t=15):
    si, so, se = ssh.exec_command(c, timeout=t)
    return so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")

# kill
run("pkill -9 -f gunicorn")
time.sleep(3)
out, _ = run("pgrep -f gunicorn | head -5")
print(f"after kill: {out or '无'}", flush=True)

# 拉新 - 用 disown 脱钩
si, so, se = ssh.exec_command(
    "bash -c 'cd /opt/archery/prod && nohup venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 > /tmp/gunicorn_134.log 2>&1 & disown; echo done'",
    timeout=8
)
print(f"start: {so.read().decode('utf-8', errors='replace')}", flush=True)
time.sleep(5)

# 验证
out, _ = run("pgrep -f gunicorn | head -10")
print(f"new pids: {out.strip()}", flush=True)
out, _ = run("ss -tlnp 2>/dev/null | grep 9003")
print(f"9003 port: {out.strip()}", flush=True)

# 端点 verify
print("\n=== 5 端点 verify ===", flush=True)
for ep in ["/login/", "/", "/admin/", "/ddl_sync/pair/list/", "/static/ddl_sync/pair_detail.js"]:
    out, _ = run(f"curl -sS -m 5 -o /dev/null -w 'HTTP:%{{http_code}}' 'http://127.0.0.1:9003{ep}'")
    print(f"  {ep:40s} {out.strip()}", flush=True)

# Django check ddl_sync
print("\n=== Django check ddl_sync ===", flush=True)
out, _ = run("cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py check ddl_sync 2>&1 | tail -3")
print(out, flush=True)

# 看 gunicorn 启动日志
print("\n=== gunicorn 启动日志 ===", flush=True)
out, _ = run("tail -10 /tmp/gunicorn_134.log")
print(out, flush=True)

ssh.close()
print("\nDONE", flush=True)
