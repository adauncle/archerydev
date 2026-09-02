#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11 hotfix #4: 134 dev pair_detail.html 实际 block 情况
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
    'echo "--- 134 dev pair_detail.html 实际内容 (最后 20 行) ---"',
    'tail -20 /opt/archery/prod/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html',
    'echo "--- 所有 block 标签 ---"',
    'grep -n "block " /opt/archery/prod/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html',
    'echo "--- base.html 实际 block ---"',
    'grep -n "block " /opt/archery/prod/common/templates/base.html',
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
        for i, cmd in enumerate(CMDS, 1):
            print(f'\n=== CMD #{i} ===')
            try:
                out, err, rc = ssh_exec(ssh, cmd, timeout=15)
                print(f'--- RC={rc} ---')
                if out.strip():
                    print('STDOUT:')
                    print(out.rstrip())
                if err.strip():
                    print('STDERR:')
                    print(err.rstrip())
            except Exception as e:
                print(f'EXCEPTION: {e}')
    finally:
        ssh.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
