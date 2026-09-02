# -*- coding: utf-8 -*-
"""9/2 D15: 推 column_diff.py 到 134 dev + 走 systemd 拉新 gunicorn."""
import paramiko
import os
import sys
import hashlib

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    hostname="172.20.2.134", port=22, username="root",
    password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW",
    timeout=10,
)
LOCAL = r"G:\MiniMax工作空间\archery_dev\sql\extensions\ddl_gh_ost\services\column_diff.py"
REMOTE = "/opt/archery/prod/sql/extensions/ddl_gh_ost/services/column_diff.py"

try:
    sftp = ssh.open_sftp()

    # 1. 备份
    stdin, stdout, stderr = ssh.exec_command(
        f"cp {REMOTE} {REMOTE}.bak_$(date +%Y%m%d_%H%M%S)"
    )
    stdout.read()
    print("Backup OK")

    # 2. SFTP 推
    sftp.put(LOCAL, "/tmp/column_diff.py")
    print("Pushed /tmp/column_diff.py")

    # 3. root cp + chown + clear __pycache__
    sftp.close()
    cmds = [
        f"cp /tmp/column_diff.py {REMOTE}",
        f"chown archery:archery {REMOTE}",
        f"find /opt/archery/prod -name __pycache__ -type d -exec rm -rf {{}} + 2>/dev/null",
    ]
    for cmd in cmds:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if err:
            print(f"CMD [{cmd}] STDERR: {err.strip()}")
    print("File replaced")

    # 4. md5 验证
    local_md5 = hashlib.md5(open(LOCAL, "rb").read()).hexdigest()
    stdin, stdout, stderr = ssh.exec_command(f"md5sum {REMOTE}")
    remote_md5_out = stdout.read().decode("utf-8", errors="replace")
    remote_md5 = remote_md5_out.split()[0] if remote_md5_out else ""
    print(f"local md5:  {local_md5}")
    print(f"remote md5: {remote_md5}")
    if local_md5 == remote_md5:
        print("MD5 OK")
    else:
        print("MD5 MISMATCH!")
        sys.exit(1)

    # 5. systemctl reset-failed + restart 接管 gunicorn
    cmds = [
        "pkill -9 gunicorn",
        "sleep 2",
        "systemctl reset-failed archery-prod-gunicorn",
        "systemctl start archery-prod-gunicorn",
        "sleep 3",
        "pgrep -f gunicorn | head -5",
    ]
    for cmd in cmds:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        print(f"[{cmd}] -> {out.strip()}")
        if err and "Warning" not in err:
            print(f"  STDERR: {err.strip()}")
finally:
    ssh.close()
