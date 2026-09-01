#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D9 阶段 2: 134 dev archery/urls.py 实际内容
"""
import io
import sys
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DEV_HOST = '172.20.2.134'
DEV_PORT = 22
DEV_USER = 'root'
DEV_PASS = 'CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW'


def ssh_exec(ssh, cmd, timeout=15):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    rc = stdout.channel.recv_exit_status()
    return out, err, rc


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=DEV_HOST, port=DEV_PORT,
        username=DEV_USER, password=DEV_PASS,
        look_for_keys=False, allow_agent=False,
    )
    try:
        out, err, rc = ssh_exec(ssh, 'cat /opt/archery/prod/archery/urls.py', timeout=15)
        print('=== 134 dev /opt/archery/prod/archery/urls.py ===')
        print(out)
    finally:
        ssh.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
