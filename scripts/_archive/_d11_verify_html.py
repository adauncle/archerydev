#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11 验证: 134 dev gunicorn 实际响应 /ddl_sync/ 跟 /config/ 都不再 500
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
    'curl -i -s -o /tmp/_d11_resp.html -w "STATUS=%{http_code}\\n" http://127.0.0.1:9003/config/ 2>&1',
    'head -3 /tmp/_d11_resp.html',
    'echo "--- body 前 200 字符 ---"',
    'head -c 200 /tmp/_d11_resp.html',
    'echo ""',
    'echo "--- 是否含 NoReverseMatch ---"',
    'grep -c "NoReverseMatch" /tmp/_d11_resp.html || echo "OK"',
    'rm -f /tmp/_d11_resp.html',
    'echo "--- 验证 /ddl_sync/pair/list/ (登录拦截 302 是正常的) ---"',
    'curl -i -s -o /tmp/_d11_resp2.html -w "STATUS=%{http_code}\\n" http://127.0.0.1:9003/ddl_sync/pair/list/ 2>&1',
    'head -8 /tmp/_d11_resp2.html',
    'rm -f /tmp/_d11_resp2.html',
    'echo "--- 验证 /ddl_sync/ (根 URL) ---"',
    'curl -i -s -o /tmp/_d11_resp3.html -w "STATUS=%{http_code}\\n" http://127.0.0.1:9003/ddl_sync/ 2>&1',
    'head -8 /tmp/_d11_resp3.html',
    'rm -f /tmp/_d11_resp3.html',
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
            print(f'>>> {cmd[:200]}')
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
