#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11 验证: 134 dev 12 端点 (用 Python SSH 跑, 不走 bash for)
"""
import io
import sys
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DEV_HOST = '172.20.2.134'
DEV_PORT = 22
DEV_USER = 'root'
DEV_PASS = 'CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW'

URLS = [
    '/login/',
    '/ddl_sync/pair/list/',
    '/ddl_sync/pair/create/',
    '/ddl_sync/pair/1/',
    '/ddl_sync/pair/1/edit/',
    '/ddl_sync/pair/1/compute_diff/',
    '/ddl_sync/pair/1/one_click_setup/',
    '/ddl_sync/pair/1/bulk_import/',
    '/ddl_sync/pair/1/add_table/',
    '/ddl_sync/history/',
    '/static/ddl_sync/pair_detail.js',
    '/admin/sql/workflowauditsetting/',
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
        print('--- 12 端点 verify ---')
        for url in URLS:
            cmd = f'curl -I -s -o /dev/null -w "%{{http_code}}" "http://127.0.0.1:9003{url}"'
            out, err, rc = ssh_exec(ssh, cmd, timeout=10)
            status = out.strip() or '?'
            status_label = 'FAIL' if status == '500' else ('OK' if status in ('200', '302') else '?')
            print(f'  {status_label}: {url} -> {status}')
    finally:
        ssh.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
