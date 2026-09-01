#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D9 阶段 2: 134 dev gunicorn worker 实际诊断 - 直接通过 /proc/<pid>/cmdline + lsof 看进程
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
    # 看 9003 端口的进程
    'lsof -i :9003 2>&1 | head -10',
    'echo "---"',
    # gunicorn master 进程实际启动命令
    'ps -eo pid,user,etime,cmd | grep -E "gunicorn|sudo -u archery" | grep -v grep',
    'echo "---"',
    # 看 gunicorn master 实际加载的 archery/urls
    'cat /proc/$(pgrep -f "gunicorn archery.wsgi" | head -1)/cmdline 2>&1 | tr "\\0" " " | head -c 500',
    'echo ""',
    'echo "---"',
    # 用 master 进程 env 查
    'cat /proc/$(pgrep -f "gunicorn archery.wsgi" | head -1)/environ 2>&1 | tr "\\0" "\\n" | grep -E "CUSTOM|DJANGO|PYTHON" | head -20',
    'echo "---"',
    # 试一下用 strace 跟踪一次 /ddl_sync/pair/1/ 请求
    'strace -p $(pgrep -f "gunicorn archery.wsgi" | tail -1) -e trace=openat -f 2>&1 | head -20 &',
    'sleep 1',
    'curl -s http://127.0.0.1:9003/ddl_sync/pair/1/ > /dev/null',
    'sleep 1',
    'kill %1 2>/dev/null',
    'wait 2>/dev/null',
]


def ssh_exec(ssh, cmd, timeout=30):
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
            try:
                out, err, rc = ssh_exec(ssh, cmd, timeout=30)
                print(out)
                if err:
                    print(f'STDERR: {err}')
            except Exception as e:
                print(f'EXCEPTION: {e}')
            print('---')
    finally:
        ssh.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
