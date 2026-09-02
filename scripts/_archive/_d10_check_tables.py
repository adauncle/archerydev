#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D10 演练准备: 看 hly_accesscard + archery_dev 实际表 + 找演练用的源+目标
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

# 1. hly_accesscard 业务库 (0 张表, 演练要模拟 1589 张)
print('=== hly_accesscard 业务库 ===')
with conn.cursor() as cur:
    cur.execute('USE hly_accesscard')
    cur.execute('SHOW TABLES')
    rows = cur.fetchall()
    print(f'  实际表数: {len(rows)}')
    for r in rows[:10]:
        print(f'    {r[0]}')

# 2. archery_dev 演练库 7 张表
print('=== archery_dev 演练库 ===')
with conn.cursor() as cur:
    cur.execute('USE archery_dev')
    cur.execute('SHOW TABLES')
    rows = cur.fetchall()
    print(f'  实际表数: {len(rows)}')
    for r in rows:
        print(f'    {r[0]}')

# 3. test_archery 33 张表 (有数据, 不动)
print('=== test_archery 测试库 ===')
with conn.cursor() as cur:
    cur.execute('USE test_archery')
    cur.execute('SHOW TABLES')
    rows = cur.fetchall()
    print(f'  实际表数: {len(rows)}')
    for r in rows[:5]:
        print(f'    {r[0]}')

# 4. 看 hly_accesscard 有没有 ddl_sync 演练表 (避免误伤)
print('=== 检查 ddl_sync 演练残留 ===')
for db in ('hly_accesscard', 'archery_dev', 'archery', 'archery_staging'):
    with conn.cursor() as cur:
        cur.execute(f'USE {db}')
        cur.execute(\"SHOW TABLES LIKE 'ext_ddl_sync%' OR SHOW TABLES LIKE 'ddl_sync%' OR SHOW TABLES LIKE '_test%' OR SHOW TABLES LIKE 'sync_%'\")
        rows = cur.fetchall()
        if rows:
            print(f'  {db} 演练残留: {rows}')
        else:
            print(f'  {db} 干净')

conn.close()
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d10_check_tables.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d10_check_tables.py 2>&1',
    'rm -f /tmp/_d10_check_tables.py',
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
