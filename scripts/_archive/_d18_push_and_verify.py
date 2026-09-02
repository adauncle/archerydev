# -*- coding: utf-8 -*-
"""D18: SFTP 推 2 文件到 134 dev + 演练 render /detail/119/ + render /detail/118/."""
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
    print("D18: 备份 134 prod 现场")
    print("=" * 70)
    ts = "20260902_2225"
    out, _, _ = run(f"mkdir -p /backup/d18_{ts} && cp {REMOTE_VIEWS} /backup/d18_{ts}/views.py.bak && cp {REMOTE_DETAIL} /backup/d18_{ts}/detail.html.bak && ls -la /backup/d18_{ts}/")
    print(out)

    # 2. md5 比对
    print("\n--- md5 一致性 ---")
    local_views_md5 = hashlib.md5(open(LOCAL_VIEWS, "rb").read()).hexdigest()
    local_detail_md5 = hashlib.md5(open(LOCAL_DETAIL, "rb").read()).hexdigest()
    out, _, _ = run(f"md5sum {REMOTE_VIEWS} {REMOTE_DETAIL}")
    print(out)
    print(f"local views.py md5:   {local_views_md5}")
    print(f"local detail.html md5: {local_detail_md5}")

    # 3. SFTP 推
    print("\n--- SFTP 推 2 文件 ---")
    sftp = ssh.open_sftp()
    sftp.put(LOCAL_VIEWS, REMOTE_VIEWS)
    sftp.put(LOCAL_DETAIL, REMOTE_DETAIL)
    out, _, _ = run(f"chown archery:archery {REMOTE_VIEWS} {REMOTE_DETAIL} && md5sum {REMOTE_VIEWS} {REMOTE_DETAIL}")
    print(out)
    sftp.close()

    # 4. 清 pycache
    out, _, _ = run(f"find {REMOTE_DIR} -name __pycache__ -type d -exec rm -rf {{}} + 2>/dev/null; echo 'pycache cleared'")
    print(out)

    # 5. kill gunicorn 拉新 (D12 实战套路: nohup 立即脱钩, 不等 paramiko channel)
    print("\n--- kill gunicorn 拉新 ---")
    out, _, _ = run("pkill -9 -f 'gunicorn.*archery.*9003' || true; sleep 2")
    print(out)
    # 启动 gunicorn (用 setsid + nohup + &, 5s timeout 让它跑后台)
    cmd_start = f"cd {REMOTE_DIR} && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn_d18.log 2>&1 & disown"
    stdin, stdout, stderr = ssh.exec_command(cmd_start, timeout=5)
    try:
        out = stdout.read().decode("utf-8", errors="replace")
        print(f"gunicorn 启动返回: {out.strip() or '(detached)'}")
    except Exception:
        print("gunicorn 启动已 detach (timeout OK)")
    # 等启动完成
    out, _, _ = run("sleep 4; pgrep -fa gunicorn | head -6")
    print(f"gunicorn pids: {out.strip()}")
    out, _, _ = run("ss -tlnp 2>/dev/null | grep 9003")
    print(f"9003 端口: {out.strip() or '(无)'}")
    out, _, _ = run("systemctl is-active archery-prod-gunicorn")
    print(f"systemd status: {out.strip()}")

    # 6. 演练 render
    print("\n" + "=" * 70)
    print("演练 render /detail/119/ (镜像工单) + /detail/118/ (源工单)")
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

for wid, label in [(119, "镜像工单"), (118, "源工单")]:
    print(f"\n=== /detail/{wid}/ ({label}) ===")
    resp = client.get(f"/detail/{wid}/")
    print(f"Status: {resp.status_code}  Content length: {len(resp.content)}")
    content = resp.content.decode("utf-8", errors="replace")
    import re
    # 找 ddl_sync alert 块
    for marker in [
        r"DDL 跨库同步 - 镜像工单",
        r"DDL 跨库同步 - 已配置",
        r"ddl_sync",
        r"v0\.5\.0 自动生成",
        r"v0\.5\.0 联动中",
        r"wf#1\d{2}",
    ]:
        cnt = len(re.findall(marker, content))
        if cnt:
            sample = re.findall(marker, content)[:2]
            print(f"  marker={marker:35s} count={cnt:2d} sample={sample}")

    # 找 wf#118 / wf#119 链接
    links = re.findall(r'href="(/detail/(11[78]|11[89])/)"', content)
    print(f"  /detail/ link: {links[:3]}")
'''

    sftp = ssh.open_sftp()
    with sftp.open("/tmp/_d18_render2.py", "w") as f:
        f.write(render_script)
    sftp.chmod("/tmp/_d18_render2.py", 0o755)
    sftp.close()

    out, err, code = run(f"cd {REMOTE_DIR} && sudo -u archery venv/bin/python /tmp/_d18_render2.py 2>&1 | tail -50")
    print(out)
    if err and "Warning" not in err:
        print(f"[stderr] {err[:500]}")

finally:
    ssh.close()
