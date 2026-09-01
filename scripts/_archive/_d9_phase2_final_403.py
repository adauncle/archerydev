#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D9 阶段 2: 8/13 教训最终验证 — manage.py runserver 临时跑 + curl 测 403
"""
import io
import sys
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DEV_HOST = '172.20.2.134'
DEV_PORT = 22
DEV_USER = 'root'
DEV_PASS = 'CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW'

# 直接走 urls 路由 (134 dev archery/urls.py 已经 include ddl_sync)
TEST_CODE = """
import django
django.setup()

from django.urls import reverse, resolve
from django.test import Client
from django.contrib.auth import get_user_model

# 1. 查 ddl_sync urls 真注册了
from archery import urls as archery_urls
print('--- 134 dev urls 注册情况 ---')
ddl_sync_in_urls = any('ddl_sync' in str(p.pattern) for p in archery_urls.urlpatterns)
print(f'  ddl_sync in archery/urls.py: {ddl_sync_in_urls}')

# 2. 看 urls include 怎么写的
for p in archery_urls.urlpatterns:
    if hasattr(p, 'urlconf_module'):
        # include 路由
        ucm = p.urlconf_module
        if isinstance(ucm, list):
            print(f'  include: {p.pattern} -> list (nested urls)')
        else:
            print(f'  include: {p.pattern} -> {ucm.__name__}')

# 3. 用 Client(SERVER_NAME='127.0.0.1') + force_login 普通用户 测 403
Users = get_user_model()
Users.objects.filter(username='_test_403_user').delete()
user = Users.objects.create_user(
    username='_test_403_user',
    password='_test_pwd_xxx',
    email='_test@local',
)
user.is_superuser = False
user.is_staff = False
user.save()
user.user_permissions.clear()

c = Client(SERVER_NAME='127.0.0.1')
c.force_login(user)
print(f'  test user: {user.username} perms={user.get_all_permissions()}')

# 4. 找 ddl_sync urls 的真 url 路径
from sql.extensions.ddl_sync import urls as ddl_sync_urls
print('--- ddl_sync urls 列表 ---')
for p in ddl_sync_urls.urlpatterns:
    print(f'  {p.pattern}')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d9_final_403.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d9_final_403.py 2>&1',
    'rm -f /tmp/_d9_final_403.py',
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
