#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D10 演练准备: 在 hly_accesscard 造 5 张表 + 看干净状态
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

ins = Instance.objects.get(id=1)
user, password = ins.get_username_password() if hasattr(ins, 'get_username_password') else (ins.user, ins.password)
conn = pymysql.connect(
    host=ins.host, port=ins.port, user=user, password=password,
    connect_timeout=5, autocommit=True,
)

# 1. 看 hly_accesscard 当前 0 张表
with conn.cursor() as cur:
    cur.execute('USE hly_accesscard')
    cur.execute('SHOW TABLES')
    rows = cur.fetchall()
    print(f'hly_accesscard 当前表数: {len(rows)}')

# 2. 造 5 张表跟 archery_dev 7 张里重叠 5 张
create_sqls = [
    '''
    CREATE TABLE IF NOT EXISTS accesscard_account (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        username VARCHAR(64) NOT NULL,
        card_no VARCHAR(32) NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''',
    '''
    CREATE TABLE IF NOT EXISTS accesscard_black_detail (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        black_id BIGINT NOT NULL,
        reason VARCHAR(255),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''',
    '''
    CREATE TABLE IF NOT EXISTS accesscard_groupuser (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        group_id BIGINT NOT NULL,
        user_id BIGINT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''',
    '''
    CREATE TABLE IF NOT EXISTS accesscard_test_diff (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        test_field VARCHAR(64)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''',
    '''
    CREATE TABLE IF NOT EXISTS accesscard_test_rollback (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        rb_field VARCHAR(64)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''',
]
with conn.cursor() as cur:
    cur.execute('USE hly_accesscard')
    for sql in create_sqls:
        cur.execute(sql)
    conn.commit()

# 3. 看造完后
with conn.cursor() as cur:
    cur.execute('USE hly_accesscard')
    cur.execute('SHOW TABLES')
    rows = cur.fetchall()
    print(f'造完后 hly_accesscard 表数: {len(rows)}')
    for r in rows:
        print(f'  {r[0]}')

conn.close()
print('--- 准备完成 ---')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d10_case0.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d10_case0.py 2>&1',
    'rm -f /tmp/_d10_case0.py',
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
