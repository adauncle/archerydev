"""D13 实战 - 停手动 gunicorn + 让 systemd 接管"""
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)

def run(c, t=10):
    si, so, se = ssh.exec_command(c, timeout=t)
    return so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")

# 1. 看 systemd unit 文件
out, _ = run("cat /etc/systemd/system/archery-prod-gunicorn.service 2>&1")
print(f"=== unit file ===\n{out}", flush=True)

# 2. 停掉我手动拉的所有 gunicorn (1596-1600)
out, _ = run("pkill -9 -f gunicorn")
print(f"pkill: {out}", flush=True)
time.sleep(2)
out, _ = run("pgrep -f gunicorn | head -5")
empty = "无"
print(f"after pkill: {out if out else empty}", flush=True)

# 3. 看 systemd 日志为啥 fail
out, _ = run("journalctl -u archery-prod-gunicorn -n 20 --no-pager 2>&1 | tail -30")
print(f"=== journal last 20 ===\n{out}", flush=True)

# 4. systemctl reset-failed + restart
out, _ = run("systemctl reset-failed archery-prod-gunicorn")
print(f"reset-failed: {out}", flush=True)
out, _ = run("systemctl start archery-prod-gunicorn")
print(f"start: {out}", flush=True)
time.sleep(5)
out, _ = run("systemctl status archery-prod-gunicorn 2>&1 | head -15")
print(f"=== status ===\n{out}", flush=True)
out, _ = run("pgrep -f gunicorn | head -10")
print(f"new pids: {out}", flush=True)

# 5. 端点 verify
print("\n=== 端点 verify ===", flush=True)
for ep in ["/login/", "/", "/ddl_sync/pair/list/"]:
    out, _ = run("curl -sS -m 5 -o /dev/null -w 'HTTP:%{http_code}' 'http://127.0.0.1:9003" + ep + "'")
    print(f"  {ep:40s} {out.strip()}", flush=True)

ssh.close()
print("DONE", flush=True)
