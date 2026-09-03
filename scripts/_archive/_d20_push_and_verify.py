# -*- coding: utf-8 -*-
"""D20: SFTP 推 detail.html 134 dev + 演练 render /detail/123/."""
import os
import paramiko
import hashlib

LOCAL = r"G:\MiniMax工作空间\archery_dev\sql\templates\detail.html"
REMOTE_DIR = "/opt/archery/prod"
REMOTE = f"{REMOTE_DIR}/sql/templates/detail.html"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    hostname="172.20.2.134", port=22, username="root",
    password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW",
    timeout=15,
)

def run(cmd, timeout=120):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out, err, stdout.channel.recv_exit_status()

try:
    print("=" * 70)
    print("D20: 备份 + 推 + 拉新 + 演练")
    print("=" * 70)
    ts = "20260903_1105"
    run(f"mkdir -p /backup/d20_{ts} && cp {REMOTE} /backup/d20_{ts}/detail.html.bak && ls -la /backup/d20_{ts}/")

    local_md5 = hashlib.md5(open(LOCAL, "rb").read()).hexdigest()
    out, _, _ = run(f"md5sum {REMOTE}")
    print(out)
    print(f"local md5: {local_md5}")

    sftp = ssh.open_sftp()
    sftp.put(LOCAL, REMOTE)
    out, _, _ = run(f"chown archery:archery {REMOTE} && md5sum {REMOTE}")
    print(out)
    sftp.close()

    out, _, _ = run(f"pkill -9 -f 'gunicorn.*archery.*9003' || true; sleep 2; echo done")
    print("kill gunicorn:", out.strip())

    cmd_start = f"cd {REMOTE_DIR} && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn_d20.log 2>&1 & disown"
    stdin, stdout, stderr = ssh.exec_command(cmd_start, timeout=5)
    try:
        out = stdout.read().decode("utf-8", errors="replace")
        print(f"gunicorn: {out.strip() or '(detached)'}")
    except Exception:
        print("gunicorn detach OK")
    out, _, _ = run("sleep 4; pgrep -fa gunicorn | head -6")
    print(f"gunicorn pids: {out.strip()}")

    print("\n" + "=" * 70)
    print("演练 /detail/123/ 验证 (新镜像工单 wf#123)")
    print("=" * 70)
    render = r'''
import os, sys
sys.path.insert(0, "/opt/archery/prod")
os.environ["DJANGO_SETTINGS_MODULE"] = "archery.settings"
import django
django.setup()

from django.test import Client
from sql.models import Users as User

archery = User.objects.get(username="archery")
client = Client(SERVER_NAME="127.0.0.1")
client.force_login(archery, backend="django.contrib.auth.backends.ModelBackend")

resp = client.get("/detail/123/")
print(f"Status: {resp.status_code}  Content length: {len(resp.content)}")
content = resp.content.decode("utf-8", errors="replace")
import re

# D20 关键验证
checks = [
    (r"DDL 跨库同步 - 镜像工单", "🤖 镜像工单 alert (D18 标识)"),
    (r"自动生成的 SQL \(镜像工单实际内容\)", "D19 alert 块 SQL 标题 (应该不存在, 已撤回)"),
    (r"镜像工单 SQL 内容", "D20 镜像工单 SQL 块 (新位置)"),
    (r"📝", "📝 emoji 块标题"),
    (r"<pre[^>]*>(ALTER TABLE[^<]+)</pre>", "完整 SQL pre 块"),
    (r"test3", "test3 SQL 关键字"),
    (r"wf#122", "源工单 wf#122 link"),
    (r"column-diff-result", "8/26 inline 区域"),
    (r"hly_accesscard_history", "目标库"),
]
for pat, label in checks:
    matches = re.findall(pat, content, re.DOTALL)
    print(f"  {label:50s} count={len(matches)}")

# 找 SQL 位置
print("\n--- SQL 块位置验证 ---")
# 找 column-diff-result 之后, SQL 块之前 是不是挨着
m = re.search(r'<div id="column-diff-result"[^>]*></div>\s*<div[^>]*margin-top: 14px[^"]*"[^>]*>\s*<strong>📝 镜像工单 SQL 内容', content, re.DOTALL)
if m:
    print("✓ SQL 块在 column-diff-result 之后, 挨着 8/26 inline 区域")
else:
    print("✗ SQL 块位置不对")

# 找 alert 块里有没有 SQL 块
m = re.search(r'alert-info[^"]*"[^>]*>.*?自动生成的 SQL', content, re.DOTALL)
if m:
    print("✗ alert 块里还有 SQL 块 (D19 没撤回干净)")
else:
    print("✓ alert 块里没 SQL 块 (D19 已撤回)")
'''
    sftp = ssh.open_sftp()
    with sftp.open("/tmp/_d20_render.py", "w") as f:
        f.write(render)
    sftp.chmod("/tmp/_d20_render.py", 0o755)
    sftp.close()
    out, err, _ = run(f"cd {REMOTE_DIR} && sudo -u archery venv/bin/python /tmp/_d20_render.py 2>&1 | tail -40")
    print(out)
    if err and "Warning" not in err:
        print(f"[stderr] {err[:500]}")

finally:
    ssh.close()
