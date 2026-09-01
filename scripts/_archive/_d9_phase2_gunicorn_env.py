#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D9 阶段 2: 134 dev gunicorn master (pid 64735) 实际 environ + cwd
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
    # 1. gunicorn master (pid 64735) 的 environ
    'cat /proc/64735/environ 2>&1 | tr "\\0" "\\n" | grep -E "CUSTOM|DJANGO|PYTHON" | head -20',
    'echo "---"',
    # 2. cwd + exe
    'ls -la /proc/64735/cwd /proc/64735/exe 2>&1',
    'echo "---"',
    # 3. master 进程实际加载的 archery.urls (通过 py-spy 或 gdb 太复杂, 用简单的 inspect)
    # 看 gunicorn worker 实际服务请求时的 url 解析 — 通过 mangled path
    'curl -i -s "http://127.0.0.1:9003/ddl_sync/" 2>&1 | head -5',
    'echo "---"',
    # 4. 看 nginx/Apache 是不是有 reverse proxy 改写路径
    'cat /etc/nginx/conf.d/*.conf 2>&1 | grep -A 3 "9003" | head -30',
    'echo "---"',
    # 5. 直接 gunicorn master 加载时 import 的模块
    'ls -la /proc/64735/maps 2>&1 | head -3',
    # 6. 用 py-spy 看 master 实际加载的 urlpatterns
    'sudo -u archery venv/bin/python -c "import sys; sys.path.insert(0, \"/opt/archery/prod\"); import os; os.chdir(\"/opt/archery/prod\"); import django; os.environ.setdefault(\"DJANGO_SETTINGS_MODULE\", \"archery.settings\"); django.setup(); from django.conf import settings; print(\"CUSTOM_DDL_SYNC_ENABLED:\", getattr(settings, \"CUSTOM_DDL_SYNC_ENABLED\", \"NOT_SET\"))"',
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
            print(f'>>> {cmd[:200]}')
            try:
                out, err, rc = ssh_exec(ssh, cmd, timeout=15)
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
