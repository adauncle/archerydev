"""D13 实战 - 看 134 dev 端点 + systemd"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)

def run(c, t=10):
    si, so, se = ssh.exec_command(c, timeout=t)
    return so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")

# systemd unit
out, _ = run("systemctl list-units --type=service 2>&1 | grep -i gunicorn | head -10")
print(f"systemd gunicorn units: {out}", flush=True)
out, _ = run("systemctl cat archery-gunicorn 2>&1 | head -30")
print(f"unit cat: {out}", flush=True)

# 端点 verify
for ep in ["/login/", "/", "/ddl_sync/pair/list/"]:
    out, _ = run("curl -sS -m 5 -o /dev/null -w 'HTTP:%{http_code}' 'http://127.0.0.1:9003" + ep + "'")
    print(f"  {ep:40s} {out.strip()}", flush=True)

ssh.close()
print("DONE", flush=True)
