"""D13 实战 - 看现状"""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)
print("connected", flush=True)

def run(c, t=10):
    si, so, se = ssh.exec_command(c, timeout=t)
    return so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")

out, _ = run("pgrep -f gunicorn | head -10")
print(f"pids: {out}", flush=True)
out, _ = run("ss -tlnp 2>/dev/null | grep 9003")
print(f"9003: {out}", flush=True)
out, _ = run("ps -eo pid,etime,cmd | grep gunicorn | grep -v grep | head -10")
print(f"ps: {out}", flush=True)

# kill
out, _ = run("pkill -9 -f gunicorn")
print(f"kill: {out}", flush=True)
time.sleep(3)
out, _ = run("pgrep -f gunicorn | head -5")
empty = "无"
print(f"after kill: {out if out else empty}", flush=True)
out, _ = run("ss -tlnp 2>/dev/null | grep 9003")
print(f"9003 after kill: {out}", flush=True)

# 拉新 (用 nohup + & + exit 0 让 exec_command 立即返回)
cmd = (
    "cd /opt/archery/prod && "
    "(nohup venv/bin/gunicorn archery.wsgi:application "
    "-w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 "
    "> /tmp/gunicorn_134.log 2>&1 &) && echo 'spawned'"
)
si, so, se = ssh.exec_command(cmd, timeout=8)
print(f"start cmd: {cmd}", flush=True)
print(f"start out: {so.read().decode('utf-8', errors='replace')}", flush=True)
err = se.read().decode("utf-8", errors="replace")
if err:
    print(f"start err: {err[:200]}", flush=True)
time.sleep(5)

out, _ = run("pgrep -f gunicorn | head -10")
print(f"new pids: {out}", flush=True)
out, _ = run("ss -tlnp 2>/dev/null | grep 9003")
print(f"9003 new: {out}", flush=True)

ssh.close()
print("DONE", flush=True)
