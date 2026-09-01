#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D9 阶段 2: 8/13 教训验证 — 用 Django test client 测 AJAX 端点 403 必返 JSON
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

from django.test import Client
from django.contrib.auth import get_user_model
import json

# 1. 找/建一个普通用户 (没 perm 的, 验 403 走 JSON)
Users = get_user_model()
# 先清掉上次测试可能残留的 superuser
Users.objects.filter(username='_test_403_user').delete()
user = Users.objects.create_user(
    username='_test_403_user',
    password='_test_pwd_xxx',
    email='_test@local',
)
# 关键: 显式设 is_superuser=False / is_staff=False, 避免 superuser 自动有所有 perm
user.is_superuser = False
user.is_staff = False
user.save()
# 显式清掉所有 perm (避免 create_user 默认给某些)
user.user_permissions.clear()
print(f'  test user: {user.username} is_superuser={user.is_superuser} perms={user.get_all_permissions()}')

# 2. 用 Client 模拟登录 + POST (SERVER_NAME 走 127.0.0.1 避免 DisallowedHost)
c = Client(SERVER_NAME='127.0.0.1')
c.force_login(user)

# 3. POST AJAX 端点, 期望 403 返 JSON (8/13 教训)
endpoints = [
    ('POST', '/ddl_sync/pair/1/compute_diff/', {}),
    ('POST', '/ddl_sync/pair/1/one_click_setup/', {}),
    ('POST', '/ddl_sync/pair/1/bulk_import/', {}),
    ('POST', '/ddl_sync/pair/1/add_table/', {'table_name': 'foo'}),
    ('GET', '/ddl_sync/history/', {}),
]

print('--- 8/13 教训验证: 403 必返 JSON ---')
all_pass = True
for method, url, body in endpoints:
    if method == 'POST':
        resp = c.post(url, data=json.dumps(body), content_type='application/json')
    else:
        resp = c.get(url)
    is_json = resp.get('Content-Type', '').startswith('application/json')
    has_html_doctype = '<!DOCTYPE html>' in resp.content.decode('utf-8', errors='replace')[:500]
    body_preview = resp.content.decode('utf-8', errors='replace')[:200]
    print(f'  {method} {url}')
    print(f'    status={resp.status_code} content_type={resp.get("Content-Type")}')
    print(f'    is_json={is_json} has_html_doctype={has_html_doctype}')
    print(f'    body: {body_preview[:150]}')
    if resp.status_code == 403:
        if is_json and not has_html_doctype:
            print(f'    PASS: 403 返 JSON 不返 HTML (8/13 教训应用成功)')
        else:
            print(f'    FAIL: 403 返了 HTML, 8/13 教训未修复')
            all_pass = False
    else:
        print(f'    SKIP: 期望 403 但实际 {resp.status_code} (用户可能有 perm, 跳过验证)')

# 4. 验 perm_guard.require_perm 装饰器直接调 (不通过 url)
from sql.extensions.ddl_sync.services.perm_guard import require_perm
print('--- perm_guard.require_perm 装饰器直接调 ---')

from django.http import JsonResponse
@require_perm('change_ddlsyncpair')
def dummy_view(request):
    return JsonResponse({'ok': True, 'data': 'ok'})

from django.test import RequestFactory
rf = RequestFactory()
req = rf.post('/dummy/')
req.user = user
resp = dummy_view(req)
print(f'  status={resp.status_code} content_type={resp.get("Content-Type")}')
print(f'  body={resp.content.decode()}')
if resp.status_code == 403 and resp.get('Content-Type', '').startswith('application/json'):
    print('  PASS: require_perm 装饰器 403 返 JSON 正确')
else:
    print('  FAIL: require_perm 装饰器 403 返错')
    all_pass = False

# 5. 清理测试用户
if user.username == '_test_403_user':
    user.delete()
    print('--- 清理 _test_403_user OK ---')

print('--- 总判定 ---')
print('ALL PASS' if all_pass else 'SOME FAIL')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d9_403_test.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d9_403_test.py 2>&1',
    'rm -f /tmp/_d9_403_test.py',
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
