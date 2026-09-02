#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D10 演练 Case B: 一键配 5 张表 (compute_diff 差集 + one_click_setup bulk_create)
"""
import io
import sys
import time
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DEV_HOST = '172.20.2.134'
DEV_PORT = 22
DEV_USER = 'root'
DEV_PASS = 'CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW'

TEST_CODE = """
import django
django.setup()

from sql.extensions.ddl_sync.models import DdlSyncPair, DdlSyncTable
from sql.extensions.ddl_sync.services.compute_diff import compute_diff
from sql.extensions.ddl_sync.services.one_click_setup import one_click_setup

pair = DdlSyncPair.objects.get(id=1)
print(f'库对: {pair.name}')
print(f'  source: {pair.source_instance.instance_name}/{pair.source_db}')
print(f'  target: {pair.target_instance.instance_name}/{pair.target_db}')
print(f'  sync_mode: {pair.sync_mode}')
print()

# 1. compute_diff 差集
import time
print('--- 1. compute_diff 差集 ---')
t0 = time.time()
diff = compute_diff(pair)
duration = time.time() - t0
print(f'  耗时: {duration*1000:.0f}ms')
print(f'  whitelist (源+目标都有的): {diff["whitelist"]}')
print(f'  blacklist (源独有): {diff["blacklist"]}')
print(f'  orphans (目标独有): {diff["orphans"]}')

# 2. one_click_setup 配 whitelist (5 张源+目标都有)
print()
print('--- 2. one_click_setup bulk_create ---')
t0 = time.time()
result = one_click_setup(pair, accept_whitelist=diff['whitelist'], accept_blacklist=diff['blacklist'])
duration = time.time() - t0
print(f'  耗时: {duration*1000:.0f}ms')
print(f'  whitelist_count: {result["whitelist_count"]}')
print(f'  blacklist_count: {result["blacklist_count"]}')
print(f'  duration_ms (服务报告): {result["duration_ms"]}')

# 3. 验证
print()
print('--- 3. 验证 DdlSyncTable ---')
print(f'  DdlSyncTable 总数: {DdlSyncTable.objects.count()}')
print(f'  pair.tables.count(): {pair.tables.count()}')
for t in pair.tables.all():
    print(f'    {t.table_name} sync_type={t.sync_type}')

# 4. 5 张表演练数据对得上
expected = {'accesscard_account', 'accesscard_black_detail', 'accesscard_groupuser', 'accesscard_test_diff', 'accesscard_test_rollback'}
actual = set(t.table_name for t in pair.tables.all())
print()
print(f'--- 4. 5 张表匹配验证 ---')
print(f'  期望: {sorted(expected)}')
print(f'  实际: {sorted(actual)}')
print(f'  匹配: {expected == actual}')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d10_case_b.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d10_case_b.py 2>&1',
    'rm -f /tmp/_d10_case_b.py',
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
