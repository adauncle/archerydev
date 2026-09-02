#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11 hotfix #4: 找 134 dev 哪些模板有 {% block extra_js %}
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
    'echo "--- 134 dev 全部 .html 模板 找 extra_js block ---"',
    'find /opt/archery/prod -name "*.html" -path "*/templates/*" -exec grep -l "extra_js" {} \\; 2>/dev/null',
    'echo "--- 134 dev 找 {{% block extra_js %}} (Django template 标签) ---"',
    'find /opt/archery/prod -name "*.html" -exec grep -l "block extra_js" {} \\; 2>/dev/null',
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
                out, err, rc = ssh_exec(ssh, cmd, timeout=30)
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
