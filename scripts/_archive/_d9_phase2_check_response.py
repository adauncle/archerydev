#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D9 阶段 2: 看 134 dev gunicorn 实际响应 /ddl_sync/ 端点
"""
import io
import sys
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DEV_HOST = '172.20.2.134'
DEV_PORT = 22
DEV_USER = 'root'
DEV_PASS = 'CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW'

CMDS = [
    'curl -i -s http://127.0.0.1:9003/ddl_sync/pair/1/ 2>&1 | head -20',
    'echo "---"',
    'curl -i -s http://127.0.0.1:9003/ddl_sync/ 2>&1 | head -10',
    'echo "---"',
    'tail -50 /var/log/archery/gunicorn.log 2>&1 | tail -30',
]


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
        for cmd in CMDS:
            print(f'>>> {cmd}')
            out, err, rc = ssh_exec(ssh, cmd, timeout=15)
            print(out)
            print('---')
    finally:
        ssh.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
