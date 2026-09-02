"""D11 实战 - 修 cwd 问题, 验证 detail/119 var dbName"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)
print("connected", flush=True)

# 关键: cd /opt/archery/prod 再 sudo -u archery python (cwd 决定 logs 相对路径)
cmd = "sudo -u archery bash -lc 'cd /opt/archery/prod && /opt/archery/prod/venv/bin/python /tmp/d11_render_v3.py' 2>&1"
print(f"cmd: {cmd}", flush=True)
si, so, se = ssh.exec_command(cmd, timeout=60)
out = so.read().decode("utf-8", errors="replace")
err = se.read().decode("utf-8", errors="replace")
print("STDOUT:", out, flush=True)
if err: print("ERR:", err, flush=True)

# grep var dbName
si, so, se = ssh.exec_command("grep -n 'var dbName\\|var sqlContent\\|var instanceId\\|hly_accesscard_history' /tmp/d11_detail119_render.html | head -10", timeout=10)
print("GREP:", so.read().decode("utf-8", errors="replace"), flush=True)

# 看 line 1730 附近
si, so, se = ssh.exec_command("awk 'NR>=1725 && NR<=1735 {print NR\": \"$0}' /tmp/d11_detail119_render.html", timeout=10)
print("Line 1725-1735:", so.read().decode("utf-8", errors="replace"), flush=True)

ssh.close()
print("DONE", flush=True)
