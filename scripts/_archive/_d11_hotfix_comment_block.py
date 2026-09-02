#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11 hotfix #4: 推 pair_detail.html 修注释 (用 {# #} 不用 ##) + restart gunicorn
"""
import io
import sys
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DEV_HOST = '172.20.2.134'
DEV_PORT = 22
DEV_USER = 'root'
DEV_PASS = 'CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW'

LOCAL_BASE = 'G:\\MiniMax工作空间\\archery_dev'
REMOTE_BASE = '/opt/archery/prod'

REMOTE_CMDS = [
    # 1. 备份
    'cp /opt/archery/prod/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html /opt/archery/prod/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html.bak_20260902_1415',
    # 2. chown
    'chown -R archery:archery /opt/archery/prod/sql/extensions/ddl_sync/',
    # 3. 清 __pycache__
    'find /opt/archery/prod -name "__pycache__" -type d 2>/dev/null | xargs rm -rf 2>/dev/null || true',
    # 4. kill gunicorn + nohup 拉新
    'pkill -9 -f gunicorn || true',
    'sleep 2',
    'bash -c "cd /opt/archery/prod && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn.log 2>&1 &"',
    'sleep 5',
    'ps -eo pid,etime,cmd | grep "gunicorn archery" | grep -v grep | head -3',
    'ss -tnlp | grep 9003 || echo "9003 端口空"',
    # 5. 验证 134 dev 实际文件无 {% block extra_js %}
    'echo "--- 134 dev pair_detail.html block 标签 ---"',
    'grep -n "{% block\\|block extra" /opt/archery/prod/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html',
    # 6. 验证 /ddl_sync/pair/1/ 端点不 500
    'curl -I -s -o /dev/null -w "/ddl_sync/pair/1/=%{http_code}\\n" http://127.0.0.1:9003/ddl_sync/pair/1/',
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
        sftp = ssh.open_sftp()
        local_path = LOCAL_BASE + chr(92) + 'sql' + chr(92) + 'extensions' + chr(92) + 'ddl_sync' + chr(92) + 'templates' + chr(92) + 'ddl_sync' + chr(92) + 'pair_detail.html'
        remote_path = f'{REMOTE_BASE}/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html'
        print(f'PUT pair_detail.html -> {remote_path}')
        with open(local_path, 'rb') as f:
            data = f.read()
        with sftp.open(remote_path, 'wb') as rf:
            rf.write(data)
        print(f'  size={len(data)} OK')
        sftp.close()

        for i, cmd in enumerate(REMOTE_CMDS, 1):
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
