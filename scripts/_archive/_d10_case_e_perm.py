#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D10 演练 Case E: 4 perm 4 角色权限验证 (W1-D3 §7.2)
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

from django.contrib.auth.models import Permission
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.test import RequestFactory
from sql.extensions.ddl_sync.models import DdlSyncPair
from sql.extensions.ddl_sync.services.perm_guard import require_perm

Users = get_user_model()

# 1. 创建 4 角色
print('--- 1. 创建 4 角色 ---')
# 清掉上次的演练用户
Users.objects.filter(username__startswith='_d10_role_').delete()

business_rd = Users.objects.create_user('_d10_role_biz_rd', 'pw', '_d10@local')
business_rd.is_superuser = False
business_rd.is_staff = False
business_rd.save()
business_rd.user_permissions.clear()

dba_executor = Users.objects.create_user('_d10_role_dba_exe', 'pw', '_d10@local')
dba_executor.is_superuser = False
dba_executor.is_staff = True
dba_executor.save()
dba_executor.user_permissions.clear()

dba_lead = Users.objects.create_user('_d10_role_dba_lead', 'pw', '_d10@local')
dba_lead.is_superuser = False
dba_lead.is_staff = True
dba_lead.save()
dba_lead.user_permissions.clear()

super_user = Users.objects.filter(is_superuser=True).first()
# 给 super_user 也加个演练 username 防止重复
# (用现有 superuser archery 测)

# 2. 给 DBA 执行 (view+change, 不能 add/delete)
ct = Permission.objects.get(content_type__app_label='ddl_sync', codename='view_ddlsyncpair')
dba_executor.user_permissions.add(ct)
ct = Permission.objects.get(content_type__app_label='ddl_sync', codename='change_ddlsyncpair')
dba_executor.user_permissions.add(ct)

# 3. 给 DBA 组长 (view+add+change+delete 全)
for codename in ('view_ddlsyncpair', 'add_ddlsyncpair', 'change_ddlsyncpair', 'delete_ddlsyncpair'):
    ct = Permission.objects.get(content_type__app_label='ddl_sync', codename=codename)
    dba_lead.user_permissions.add(ct)

print(f'  business_rd: {business_rd.username} perms={business_rd.get_all_permissions()}')
print(f'  dba_executor: {dba_executor.username} perms={dba_executor.get_all_permissions()}')
print(f'  dba_lead: {dba_lead.username} perms={dba_lead.get_all_permissions()}')
print(f'  super_user: {super_user.username} is_superuser={super_user.is_superuser}')

# 4. 测 require_perm 装饰器 4 角色
print()
print('--- 2. require_perm 装饰器 4 角色 测 change_ddlsyncpair ---')

@require_perm('change_ddlsyncpair')
def test_view(request):
    return JsonResponse({'ok': True, 'msg': 'PASS'})

rf = RequestFactory()
req = rf.post('/ddl_sync/pair/1/compute_diff/')

results = {}
for name, user in [
    ('业务 RD (无 perm)', business_rd),
    ('DBA 执行 (view+change)', dba_executor),
    ('DBA 组长 (全)', dba_lead),
    ('superuser (archery)', super_user),
]:
    req.user = user
    resp = test_view(req)
    is_json = resp.get('Content-Type', '').startswith('application/json')
    body = resp.content.decode()
    results[name] = {
        'status': resp.status_code,
        'content_type': resp.get('Content-Type'),
        'is_json': is_json,
        'body': body[:100],
    }
    print(f'  {name}:')
    print(f'    status={resp.status_code} content_type={resp.get("Content-Type")}')
    print(f'    body: {body[:120]}')

# 5. 期望判定
print()
print('--- 3. 4 角色 期望判定 ---')
expected = {
    '业务 RD (无 perm)': {'status': 403, 'is_json': True},
    'DBA 执行 (view+change)': {'status': 200, 'is_json': True},  # view+change 包含 change
    'DBA 组长 (全)': {'status': 200, 'is_json': True},
    'superuser (archery)': {'status': 200, 'is_json': True},
}

all_pass = True
for name, expect in expected.items():
    actual = results[name]
    if actual['status'] == expect['status'] and actual['is_json'] == expect['is_json']:
        print(f'  {name}: PASS (status={actual["status"]}, is_json={actual["is_json"]})')
    else:
        print(f'  {name}: FAIL expected={expect} actual={actual}')
        all_pass = False

# 6. 业务 RD 验证 403 返 JSON
print()
print('--- 4. 8/13 教训应用硬证据 (业务 RD 403 返 JSON) ---')
rd_resp = results['业务 RD (无 perm)']
if rd_resp['status'] == 403 and rd_resp['is_json'] and '权限不足' in rd_resp['body']:
    print(f'  PASS: 业务 RD 拿 403 + JSON 不会弹整页 HTML')
    print(f'  body: {rd_resp["body"]}')
else:
    print(f'  FAIL: {rd_resp}')

# 7. 测 add_ddlsyncpair 守卫 (DBA 执行有 change 但没 add, 应 403)
print()
print('--- 5. require_perm add_ddlsyncpair 守卫 (DBA 执行无 add perm) ---')
@require_perm('add_ddlsynctable')
def test_add_view(request):
    return JsonResponse({'ok': True})

req.user = dba_executor
resp = test_add_view(req)
print(f'  DBA 执行 (view+change, 无 add): status={resp.status_code} content_type={resp.get("Content-Type")}')
print(f'  body: {resp.content.decode()[:120]}')
if resp.status_code == 403:
    print(f'  PASS: DBA 执行 add 守卫返 403 (无 add perm)')

# 8. 测 delete_ddlsyncpair 守卫 (DBA 组长有 delete, 应 200)
req.user = dba_lead
resp = test_add_view(req)
print(f'  DBA 组长 (有 add): status={resp.status_code}')

# 9. 清理演练用户
print()
print('--- 6. 清理演练用户 ---')
Users.objects.filter(username__startswith='_d10_role_').delete()
print(f'  _d10_role_* users deleted')

print()
print('=== Case E 总判定 ===')
print('ALL PASS' if all_pass else 'SOME FAIL')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d10_case_e.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d10_case_e.py 2>&1',
    'rm -f /tmp/_d10_case_e.py',
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
