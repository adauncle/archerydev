"""D11 实战 - kill 老 gunicorn + 拉新 + 验证"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)
print("connected", flush=True)

def run(cmd, t=15):
    si, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode("utf-8", errors="replace")
    err = se.read().decode("utf-8", errors="replace")
    return out, err

# 1. 看现状
out, _ = run("pgrep -f gunicorn | head -10")
print(f"old pids: {out.strip()}", flush=True)

# 2. kill 老 gunicorn
print("\nkill old gunicorn...", flush=True)
out, _ = run("pkill -9 -f gunicorn; sleep 3; pgrep -f gunicorn | head -5")
print(f"after kill: {out.strip() or '无'}", flush=True)

# 3. 拉新 gunicorn (D7 阶段 1 实战套路)
print("\nstart new gunicorn...", flush=True)
run("cd /opt/archery/prod && setsid nohup venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 > /tmp/gunicorn_134.log 2>&1 &")
out, _ = run("sleep 5 && pgrep -f gunicorn | head -10")
print(f"new pids: {out.strip()}", flush=True)

# 4. 端点 verify
print("\n=== 5 端点 verify ===", flush=True)
for ep in ["/login/", "/", "/admin/", "/ddl_sync/pair/list/", "/static/ddl_sync/pair_detail.js"]:
    out, _ = run(f"curl -sS -m 5 -o /dev/null -w 'HTTP:%{{http_code}}' 'http://127.0.0.1:9003{ep}'")
    print(f"  {ep:40s} {out.strip()}", flush=True)

# 5. detail/119 实际渲染
print("\n=== detail/119 实际渲染 (新 gunicorn 跑过的) ===", flush=True)
out, _ = run("sudo -u archery bash -lc 'cd /opt/archery/prod && /opt/archery/prod/venv/bin/python /tmp/d11_render_v3.py' 2>&1 | tail -3")
print(out, flush=True)
out, _ = run("grep -n 'var dbName\\|var sqlContent\\|hly_accesscard_history' /tmp/d11_detail119_render.html | head -10")
print("grep:", out, flush=True)

# 6. 9003 端口
out, _ = run("ss -tlnp 2>/dev/null | grep 9003 || netstat -tlnp 2>/dev/null | grep 9003")
print(f"\n9003 port: {out.strip()}", flush=True)

ssh.close()
print("\nDONE", flush=True)
