#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D8 阶段 2: 推 5 前端文件 (3 modal + pair_detail + pair_detail.js) + chown + kill gunicorn + 12 端点 verify
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

FILES = [
    ('sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html',
     f'{REMOTE_BASE}/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html'),
    ('sql/extensions/ddl_sync/templates/ddl_sync/partials/_bulk_import_modal.html',
     f'{REMOTE_BASE}/sql/extensions/ddl_sync/templates/ddl_sync/partials/_bulk_import_modal.html'),
    ('sql/extensions/ddl_sync/templates/ddl_sync/partials/_one_click_modal.html',
     f'{REMOTE_BASE}/sql/extensions/ddl_sync/templates/ddl_sync/partials/_one_click_modal.html'),
    ('sql/extensions/ddl_sync/templates/ddl_sync/partials/_add_table_modal.html',
     f'{REMOTE_BASE}/sql/extensions/ddl_sync/templates/ddl_sync/partials/_add_table_modal.html'),
    ('sql/extensions/ddl_sync/static/ddl_sync/pair_detail.js',
     f'{REMOTE_BASE}/sql/extensions/ddl_sync/static/ddl_sync/pair_detail.js'),
]

REMOTE_CMDS = [
    # 0. mkdir 2 个子目录 (D7 阶段 1 教训)
    'mkdir -p /opt/archery/prod/sql/extensions/ddl_sync/templates/ddl_sync/partials',
    'mkdir -p /opt/archery/prod/sql/extensions/ddl_sync/static/ddl_sync',
    # 1. chown
    'chown -R archery:archery /opt/archery/prod/sql/extensions/ddl_sync/',
    # 2. 清 __pycache__
    'find /opt/archery/prod -name "__pycache__" -type d 2>/dev/null | xargs rm -rf 2>/dev/null || true',
    # 3. kill gunicorn + nohup 拉新
    'pkill -9 -f gunicorn || true',
    'sleep 2',
    'bash -c "cd /opt/archery/prod && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn.log 2>&1 &"',
    'sleep 5',
    # 4. 验证 gunicorn 起来
    'ps -eo pid,etime,cmd | grep gunicorn | grep -v grep | head -3',
    'ss -tnlp | grep 9003 || echo "9003 端口空"',
    # 5. 端点 verify (12 个)
    'curl -I -s -o /dev/null -w "/login/=%{http_code}\\n" http://127.0.0.1:9003/login/',
    'curl -I -s -o /dev/null -w "/ddl_sync/pair/list/=%{http_code}\\n" http://127.0.0.1:9003/ddl_sync/pair/list/',
    'curl -I -s -o /dev/null -w "/ddl_sync/pair/create/=%{http_code}\\n" http://127.0.0.1:9003/ddl_sync/pair/create/',
    'curl -I -s -o /dev/null -w "/ddl_sync/pair/1/=%{http_code}\\n" http://127.0.0.1:9003/ddl_sync/pair/1/',
    'curl -I -s -o /dev/null -w "/ddl_sync/pair/1/edit/=%{http_code}\\n" http://127.0.0.1:9003/ddl_sync/pair/1/edit/',
    # AJAX 端点
    'curl -I -s -o /dev/null -w "/ddl_sync/pair/1/compute_diff/=%{http_code}\\n" http://127.0.0.1:9003/ddl_sync/pair/1/compute_diff/',
    'curl -I -s -o /dev/null -w "/ddl_sync/pair/1/one_click_setup/=%{http_code}\\n" http://127.0.0.1:9003/ddl_sync/pair/1/one_click_setup/',
    'curl -I -s -o /dev/null -w "/ddl_sync/pair/1/bulk_import/=%{http_code}\\n" http://127.0.0.1:9003/ddl_sync/pair/1/bulk_import/',
    'curl -I -s -o /dev/null -w "/ddl_sync/pair/1/add_table/=%{http_code}\\n" http://127.0.0.1:9003/ddl_sync/pair/1/add_table/',
    'curl -I -s -o /dev/null -w "/ddl_sync/history/=%{http_code}\\n" http://127.0.0.1:9003/ddl_sync/history/',
    # 静态资源
    'curl -I -s -o /dev/null -w "/static/ddl_sync/pair_detail.js=%{http_code}\\n" http://127.0.0.1:9003/static/ddl_sync/pair_detail.js',
    # 6. Django check
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py check ddl_sync 2>&1',
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
        print('=== mkdir 2 个子目录 (templates/.../partials/ + static/ddl_sync/) ===')
        out, err, rc = ssh_exec(ssh,
            'mkdir -p /opt/archery/prod/sql/extensions/ddl_sync/templates/ddl_sync/partials '
            '/opt/archery/prod/sql/extensions/ddl_sync/static/ddl_sync',
            timeout=10)
        print(f'RC={rc}')
        if err.strip():
            print('STDERR:', err.rstrip())
        print('OK')

        sftp = ssh.open_sftp()
        for local_rel, remote_path in FILES:
            local_path = LOCAL_BASE + chr(92) + local_rel.replace("/", chr(92))
            print(f'\nPUT {local_rel} -> {remote_path}')
            with open(local_path, 'rb') as f:
                data = f.read()
            with sftp.open(remote_path, 'wb') as rf:
                rf.write(data)
            print(f'  size={len(data)} OK')
        sftp.close()

        for i, cmd in enumerate(REMOTE_CMDS, 1):
            print(f'\n=== CMD #{i} ===')
            print(f'>>> {cmd[:200]}')
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
