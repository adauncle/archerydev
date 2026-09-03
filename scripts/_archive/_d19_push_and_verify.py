# -*- coding: utf-8 -*-
"""D19: SFTP 推 2 文件到 134 dev + 演练 render /detail/121/ 看 SQL 显示."""
import os
import paramiko
import hashlib

LOCAL_VIEWS = r"G:\MiniMax工作空间\archery_dev\sql\views.py"
LOCAL_DETAIL = r"G:\MiniMax工作空间\archery_dev\sql\templates\detail.html"

REMOTE_DIR = "/opt/archery/prod"
REMOTE_VIEWS = f"{REMOTE_DIR}/sql/views.py"
REMOTE_DETAIL = f"{REMOTE_DIR}/sql/templates/detail.html"

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
    # 1. 备份
    print("=" * 70)
    print("D19: 备份 + md5 对比 + SFTP 推 + 拉新 gunicorn")
    print("=" * 70)
    ts = "20260903_1005"
    out, _, _ = run(f"mkdir -p /backup/d19_{ts} && cp {REMOTE_VIEWS} /backup/d19_{ts}/views.py.bak && cp {REMOTE_DETAIL} /backup/d19_{ts}/detail.html.bak && ls -la /backup/d19_{ts}/")
    print(out)

    # 2. md5
    local_views_md5 = hashlib.md5(open(LOCAL_VIEWS, "rb").read()).hexdigest()
    local_detail_md5 = hashlib.md5(open(LOCAL_DETAIL, "rb").read()).hexdigest()
    out, _, _ = run(f"md5sum {REMOTE_VIEWS} {REMOTE_DETAIL}")
    print(out)
    print(f"local views.py md5:   {local_views_md5}")
    print(f"local detail.html md5: {local_detail_md5}")

    # 3. SFTP
    sftp = ssh.open_sftp()
    sftp.put(LOCAL_VIEWS, REMOTE_VIEWS)
    sftp.put(LOCAL_DETAIL, REMOTE_DETAIL)
    out, _, _ = run(f"chown archery:archery {REMOTE_VIEWS} {REMOTE_DETAIL} && md5sum {REMOTE_VIEWS} {REMOTE_DETAIL}")
    print(out)
    sftp.close()

    # 4. 清 pycache + kill gunicorn + 拉新 (D12 实战套路)
    out, _, _ = run(f"find {REMOTE_DIR} -name __pycache__ -type d -exec rm -rf {{}} + 2>/dev/null; pkill -9 -f 'gunicorn.*archery.*9003' || true; sleep 2; echo cleanup done")
    print("清理 pycache + kill gunicorn:", out.strip())

    # 5. 拉新 (D12 实战 nohup & disown + timeout=5 立即脱钩)
    cmd_start = f"cd {REMOTE_DIR} && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn_d19.log 2>&1 & disown"
    stdin, stdout, stderr = ssh.exec_command(cmd_start, timeout=5)
    try:
        out = stdout.read().decode("utf-8", errors="replace")
        print(f"gunicorn 启动返回: {out.strip() or '(detached)'}")
    except Exception:
        print("gunicorn 启动已 detach (timeout OK)")
    out, _, _ = run("sleep 4; pgrep -fa gunicorn | head -6")
    print(f"gunicorn pids: {out.strip()}")

    # 6. 演练
    print("\n" + "=" * 70)
    print("演练 render /detail/121/ (新镜像工单, 验证 SQL 显示)")
    print("=" * 70)
    render_script = r'''
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

# 演练 /detail/121/ (D19 用户报告的那个镜像工单)
print("\n=== /detail/121/ (新镜像工单 wf#121, 等审批) ===")
resp = client.get("/detail/121/")
print(f"Status: {resp.status_code}  Content length: {len(resp.content)}")
content = resp.content.decode("utf-8", errors="replace")
import re

checks = [
    (r"DDL 跨库同步 - 镜像工单", "🤖 镜像工单 alert"),
    (r"自动生成的 SQL \(镜像工单实际内容\)", "SQL 块标题"),
    (r"<pre[^>]*>.+?ALTER TABLE.+?</pre>", "完整 SQL pre 块"),
    (r"ALTER TABLE accesscard_black_detail add COLUMN test2", "test2 SQL 关键字"),
    (r"VARCHAR\(256\)", "VARCHAR(256)"),
    (r"wf#120", "源工单 wf#120 link"),
    (r"hly_accesscard_history", "目标库 hly_accesscard_history"),
    (r"hly_accesscard(?!_)", "源库 hly_accesscard"),
    (r"accesscard 库对 \(134 dev 演练\)", "库对 accesscard 库对 (134 dev 演练)"),
    (r"同步中 \(镜像工单已生成, 还没执行\)", "同步状态 同步中"),
    (r"label-info", "同步状态蓝色徽章 (syncing 用 info)"),
]
for pat, label in checks:
    matches = re.findall(pat, content, re.DOTALL)
    print(f"  {label:40s} count={len(matches)}")

# 找 pre 块内容
print("\n--- pre 块内容 (镜像工单 SQL 完整内容) ---")
m = re.search(r"<pre[^>]*>(.+?)</pre>", content, re.DOTALL)
if m:
    sql_in_pre = m.group(1)
    print(f"  pre 长度: {len(sql_in_pre)}")
    print(f"  pre 内容: {sql_in_pre[:300]}")

# 找 SQL 块附近
m = re.search(r"自动生成的 SQL.*?</pre>", content, re.DOTALL)
if m:
    print(f"\n  '自动生成的 SQL' 到 </pre> 区间:")
    print(f"  {m.group()[:400]}")
'''
    sftp = ssh.open_sftp()
    with sftp.open("/tmp/_d19_render.py", "w") as f:
        f.write(render_script)
    sftp.chmod("/tmp/_d19_render.py", 0o755)
    sftp.close()
    out, err, code = run(f"cd {REMOTE_DIR} && sudo -u archery venv/bin/python /tmp/_d19_render.py 2>&1 | tail -60")
    print(out)
    if err and "Warning" not in err:
        print(f"[stderr] {err[:500]}")

finally:
    ssh.close()
