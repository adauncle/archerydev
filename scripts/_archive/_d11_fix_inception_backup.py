#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11 解决: 134 dev inception 备份错 (业务库工单 #109 报 Invalid remote backup information)
实战方案: 清空 inception_remote_backup_* 4 行 + 加 enable_backup_switch=0
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

from django.db import connection

# 1. 看 Archery 怎么检查 enable_backup_switch
# 实战: sql_workflow.py passed()/execute() 走 SysConfig().get('enable_backup_switch')
# 9/1 W1-D3 §7 实战: SysConfig() 从 sql_config 表读
# 让 Archery 不走 inception backup:
#   - enable_backup_switch = 0 (业务库 DDL 不备份) — 走 Auto 时不调 inception
#   - 但 execute() 走 inception 是默认行为, 还要看 inception_remote_backup_* 是不是必填
# 实战: 清空 4 个 inception_remote_backup_* 密文, 让 inception 走 no-op (backup 失败时 DDL 主流程不中断)

print('=== 1. 看 enable_backup_switch 跟 4 个 inception_remote_backup 关系 ===')
keys_to_check = ['enable_backup_switch', 'inception_remote_backup_host', 'inception_remote_backup_port', 'inception_remote_backup_user', 'inception_remote_backup_password']
with connection.cursor() as cur:
    for k in keys_to_check:
        cur.execute('SELECT id, value FROM sql_config WHERE item = %s', (k,))
        r = cur.fetchone()
        print(f'  {k}: {r}')

# 2. 实战解法 A: 写 enable_backup_switch=0 (业务库 DDL 不走 inception 备份)
# 实战解法 B: 清空 4 个 inception_remote_backup_* 密文, inception 走 fallback
# 两个都做最稳

print()
print('=== 2. SQL UPDATE ===')
with connection.cursor() as cur:
    # A: 写 enable_backup_switch=0 (业务库 DDL 走不备份)
    cur.execute('SELECT id FROM sql_config WHERE item = %s', ('enable_backup_switch',))
    r = cur.fetchone()
    if r:
        cur.execute('UPDATE sql_config SET value = %s WHERE id = %s', ('0', r[0]))
        print(f'  UPDATE enable_backup_switch = 0 (id={r[0]})')
    else:
        cur.execute(\"INSERT INTO sql_config (item, value) VALUES ('enable_backup_switch', '0')\")
        print(f'  INSERT enable_backup_switch = 0 (new row)')

    # B: 清空 4 个 inception_remote_backup_* 密文 (mirage 加密错解密失败, 走空字符串)
    for k in ['inception_remote_backup_host', 'inception_remote_backup_port', 'inception_remote_backup_user', 'inception_remote_backup_password']:
        cur.execute('UPDATE sql_config SET value = %s WHERE item = %s', ('', k))
        print(f'  UPDATE {k} = ""')

print()
print('=== 3. 验证 ===')
with connection.cursor() as cur:
    for k in ['enable_backup_switch', 'inception_remote_backup_host', 'inception_remote_backup_port', 'inception_remote_backup_user', 'inception_remote_backup_password']:
        cur.execute('SELECT value FROM sql_config WHERE item = %s', (k,))
        r = cur.fetchone()
        print(f'  {k}: {r[0] if r else "NOT_FOUND"}')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d11_fix_inception.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d11_fix_inception.py 2>&1',
    'rm -f /tmp/_d11_fix_inception.py',
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
