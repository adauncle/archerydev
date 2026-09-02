#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D10 演练准备: 134 dev instance 1 实际数据库列表
"""
import io
import sys
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DEV_HOST = '172.20.2.134'
DEV_PORT = 22
DEV_USER = 'root'
DEV_PASS = 'CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW'

TEST_CODE = """
import django
django.setup()

from sql.models import Instance
import pymysql

# 用 134 dev 演练库 (archery instance 1)
ins = Instance.objects.get(id=1)
user, password = ins.get_username_password() if hasattr(ins, 'get_username_password') else (ins.user, ins.password)
host = ins.host
port = ins.port

print(f'=== instance 1 ({ins.instance_name}) {host}:{port} ===')
print(f'  user: {user[:20] if user else "None"}...')
print(f'  password: {password[:30] if password else "None"}...')

# PyMySQL 直连
try:
    conn = pymysql.connect(
        host=host, port=port, user=user, password=password,
        connect_timeout=5, autocommit=True,
    )
    with conn.cursor() as cur:
        cur.execute('SHOW DATABASES')
        rows = cur.fetchall()
        print(f'  databases ({len(rows)}):')
        for r in rows:
            db_name = r[0]
            if db_name in ('information_schema', 'mysql', 'performance_schema', 'sys'):
                continue
            # 拿每张库的表数
            try:
                cur.execute(f'SELECT COUNT(*) FROM information_schema.TABLES WHERE table_schema = %s', (db_name,))
                table_count = cur.fetchone()[0]
                print(f'    {db_name} ({table_count} 张表)')
            except Exception as e:
                print(f'    {db_name} (error: {e})')
    conn.close()
except Exception as e:
    print(f'  connect error: {e}')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d10_list_dbs.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d10_list_dbs.py 2>&1',
    'rm -f /tmp/_d10_list_dbs.py',
]


def ssh_exec(ssh, cmd, timeout=60):
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
        for i, cmd in enumerate(REMOTE_CMDS, 1):
            print(f'\n=== CMD #{i} ===')
            try:
                out, err, rc = ssh_exec(ssh, cmd, timeout=60)
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
