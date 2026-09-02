# -*- coding: utf-8 -*-
"""9/2 D15: SFTP 推演练脚本到 134 dev 跑."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    hostname="172.20.2.134", port=22, username="root",
    password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW",
    timeout=10,
)
try:
    sftp = ssh.open_sftp()
    sftp.put(
        r"G:\MiniMax工作空间\archery_dev\scripts\_archive\_d15_drill_v1.py",
        "/tmp/d15_drill_v1.py",
    )
    sftp.chmod("/tmp/d15_drill_v1.py", 0o755)
    sftp.close()
    print("Pushed: /tmp/d15_drill_v1.py")

    # 走 sudo -u archery 走 systemd 一致 env
    cmd = "cd /opt/archery/prod && sudo -u archery /opt/archery/prod/venv/bin/python /tmp/d15_drill_v1.py"
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print("STDOUT:")
    print(out)
    if err:
        print("STDERR (first 5KB):")
        print(err[:5000])
finally:
    ssh.close()
