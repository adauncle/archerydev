# -*- coding: utf-8 -*-
"""9/2 D16: 推 D15 修复后 column_diff.py 到 110 prod c9236a0.

实战套路 (D11 4 步 + D12 md5 + D13 systemctl + D14 c9236a0 实战新发现):
1. 验证 systemd EnvironmentFile/WorkingDirectory 实际指向 c9236a0
2. 备份 110 prod c9236a0 column_diff.py 现场
3. SFTP 推本地 column_diff.py -> /tmp
4. md5 验证一致性
5. root cp + chown + 清 __pycache__
6. kill gunicorn + systemctl reset-failed + start
7. gunicorn 拉新 pids verify
"""
import os
import sys
import paramiko
import hashlib

LOCAL = r"G:\MiniMax工作空间\archery_dev\sql\extensions\ddl_gh_ost\services\column_diff.py"
REMOTE = "/dbdata/archery_v114_c9236a0/sql/extensions/ddl_gh_ost/services/column_diff.py"
BACKUP_DIR = "/backup/upgrade_v114"
BACKUP_NAME = "d16_20260902_211000"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    hostname="172.20.2.110", port=22, username="root",
    password="lAqfb8uEmQYsnGNQwIHtGPwukjCz6J",
    timeout=15,
)

def run(cmd, timeout=30):
    """执行命令, 返 (out, err, exit_code)."""
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out, err, stdout.channel.recv_exit_status()

try:
    # ========== 步骤 1: 验证 systemd 指向 c9236a0 (D14 实战新发现) ==========
    print("=" * 60)
    print("步骤 1: 验证 systemd EnvironmentFile/WorkingDirectory")
    print("=" * 60)
    out, err, _ = run("systemctl cat archery-v114-gunicorn | grep -E 'EnvironmentFile|WorkingDirectory|ExecStart'")
    print(out)
    if "c9236a0" not in out:
        print("[FATAL] systemd 没指向 c9236a0, 实战前先排查")
        sys.exit(1)
    print("OK: systemd 实战指向 c9236a0")

    # ========== 步骤 2: 备份 110 prod c9236a0 现场 ==========
    print("\n" + "=" * 60)
    print(f"步骤 2: 备份 {REMOTE}")
    print("=" * 60)
    backup_path = f"{BACKUP_DIR}/{BACKUP_NAME}/column_diff.py.bak"
    out, err, _ = run(f"mkdir -p {BACKUP_DIR}/{BACKUP_NAME}")
    if err and "Warning" not in err:
        print(f"mkdir ERR: {err}")
    out, err, _ = run(f"cp {REMOTE} {backup_path}")
    print(f"cp: {out or 'OK'}")
    if err and "Warning" not in err:
        print(f"cp ERR: {err}")
    out, err, _ = run(f"ls -la {backup_path} && md5sum {backup_path}")
    print(out)

    # ========== 步骤 3: SFTP 推本地 column_diff.py -> /tmp ==========
    print("\n" + "=" * 60)
    print("步骤 3: SFTP 推本地 column_diff.py -> /tmp")
    print("=" * 60)
    sftp = ssh.open_sftp()
    sftp.put(LOCAL, "/tmp/column_diff.py")
    sftp.chmod("/tmp/column_diff.py", 0o644)
    sftp.close()
    print("Pushed: /tmp/column_diff.py")

    # ========== 步骤 4: md5 验证一致性 ==========
    print("\n" + "=" * 60)
    print("步骤 4: md5 验证本地 vs 远端")
    print("=" * 60)
    local_md5 = hashlib.md5(open(LOCAL, "rb").read()).hexdigest()
    out, err, _ = run("md5sum /tmp/column_diff.py")
    remote_md5 = out.split()[0] if out else ""
    print(f"local md5:  {local_md5}")
    print(f"remote md5: {remote_md5}")
    if local_md5 != remote_md5:
        print("[FATAL] md5 不一致, 实战 推送实战 实战")
        sys.exit(1)
    print("OK: md5 一致")

    # ========== 步骤 5: root cp + chown + 清 __pycache__ ==========
    print("\n" + "=" * 60)
    print("步骤 5: root cp + chown + 清 __pycache__")
    print("=" * 60)
    cmds = [
        f"cp /tmp/column_diff.py {REMOTE}",
        f"chown archery:archery {REMOTE}",
        f"find /dbdata/archery_v114_c9236a0 -name __pycache__ -type d -exec rm -rf {{}} + 2>/dev/null",
    ]
    for cmd in cmds:
        out, err, _ = run(cmd)
        print(f"[{cmd}]")
        if out.strip():
            print(f"  out: {out.strip()}")
        if err and "Warning" not in err:
            print(f"  err: {err.strip()}")
    print("OK: 文件替换 + chown + 清 __pycache__")

    # ========== 步骤 6: kill gunicorn + systemctl reset-failed + start ==========
    print("\n" + "=" * 60)
    print("步骤 6: kill gunicorn + systemctl reset-failed + start")
    print("=" * 60)
    cmds = [
        "pkill -9 gunicorn",
        "sleep 2",
        "systemctl reset-failed archery-v114-gunicorn",
        "systemctl start archery-v114-gunicorn",
        "sleep 3",
    ]
    for cmd in cmds:
        out, err, _ = run(cmd)
        print(f"[{cmd}] -> {out.strip() or '(无输出)'}")
        if err and "Warning" not in err:
            print(f"  err: {err.strip()}")

    # ========== 步骤 7: gunicorn 拉新 pids verify ==========
    print("\n" + "=" * 60)
    print("步骤 7: gunicorn 拉新 pids verify")
    print("=" * 60)
    out, err, _ = run("pgrep -f gunicorn | head -5")
    print(f"gunicorn pids: {out.strip()}")

    out, err, _ = run("ss -tlnp 2>/dev/null | grep 9123")
    print(f"9123 端口: {out.strip()}")

    out, err, _ = run("systemctl is-active archery-v114-gunicorn")
    print(f"systemd status: {out.strip()}")

    out, err, _ = run(f"md5sum {REMOTE}")
    remote_final_md5 = out.split()[0] if out else ""
    print(f"实战后 110 c9236a0 md5: {remote_final_md5}")
    if remote_final_md5 == local_md5:
        print("OK: 实战后 110 c9236a0 md5 一致")
    else:
        print("[FATAL] 实战后 md5 不一致, 实战排查")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("D16 实战 110 prod c9236a0 推送完成!")
    print("=" * 60)
finally:
    ssh.close()
