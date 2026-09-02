#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D10 演练 Case D: 业务 RD 提的表在 pair 黑名单 → skipped (业务库 DDL 跳过同步)
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

from django.utils import timezone
from common.utils.const import WorkflowStatus
from sql.models import SqlWorkflow, SqlWorkflowContent, WorkflowAudit
from sql.extensions.ddl_sync.models import DdlSyncPair, DdlSyncTable, DdlSyncHistory

# 1. 给 pair 加 1 个 blacklist (DBA 显式排除 accesscard_test_diff)
pair = DdlSyncPair.objects.get(id=1)
DdlSyncTable.objects.filter(pair=pair, table_name='accesscard_test_diff', sync_type='blacklist').delete()
DdlSyncTable.objects.create(
    pair=pair, table_name='accesscard_test_diff', sync_type='blacklist',
)
print(f'1. 配 blacklist: accesscard_test_diff (DBA 显式排除)')
print(f'   pair.tables:')
for t in pair.tables.all():
    print(f'     {t.table_name} sync_type={t.sync_type}')

# 2. 业务 RD 提 ALTER TABLE accesscard_test_diff (在黑名单里)
archery_ins = SqlWorkflow._meta.get_field('instance').related_model.objects.get(id=1)
group_id = archery_ins.resource_group.first().group_id
group_name = archery_ins.resource_group.first().group_name

sql_text = \"\"\"ALTER TABLE accesscard_test_diff ADD COLUMN blocked_field VARCHAR(50) DEFAULT NULL\"\"\"

wf = SqlWorkflow.objects.create(
    workflow_name='[Case D 演练] 黑名单表 - DBA 显式排除',
    group_id=group_id, group_name=group_name,
    engineer='mkq', engineer_display='mkq 业务 RD',
    audit_auth_groups='1',
    status='workflow_manreviewing',
    syntax_type=1, is_backup=True,
    instance=archery_ins, db_name='hly_accesscard',
)
SqlWorkflowContent.objects.create(workflow=wf, sql_content=sql_text, review_content='[]', execute_result='')
print()
print(f'2. 业务 RD 提工单: id={wf.id} SQL={sql_text}')

# 3. 模拟 passed() 走完
audit = WorkflowAudit.objects.create(
    group_id=group_id, group_name=group_name,
    workflow_id=wf.id, workflow_type=2,
    workflow_title=wf.workflow_name,
    audit_auth_groups='1',
    current_audit='-1', next_audit='-1',
    current_status=WorkflowStatus.PASSED,
    create_user='mkq', create_user_display='mkq 业务 RD',
)
wf.status = 'workflow_review_pass'
wf.save()
print(f'3. 业务 RD 工单: status={wf.status}')

# 4. 验证 DdlSyncHistory 写入 skipped
print()
print('--- 4. 验证 DdlSyncHistory skipped ---')
histories = DdlSyncHistory.objects.filter(source_workflow=wf).order_by('-created_at')
print(f'  DdlSyncHistory 数: {histories.count()}')
for h in histories:
    print(f'  history.id={h.id}')
    print(f'    pair: #{h.pair_id}')
    print(f'    source_workflow: #{h.source_workflow_id}')
    print(f'    target_workflow: {h.target_workflow_id} (None = skipped, 不创建镜像工单)')
    print(f'    table_name: {h.table_name}')
    print(f'    sync_status: {h.sync_status}')
    print(f'    error_message: {h.error_message}')
    print(f'    finished_at: {h.finished_at}')

# 5. 验证源表没被改 (因为 _should_sync 返 False, signal 跳过了)
import pymysql
ins = archery_ins
user, password = ins.get_username_password() if hasattr(ins, 'get_username_password') else (ins.user, ins.password)
conn = pymysql.connect(host=ins.host, port=ins.port, user=user, password=password, connect_timeout=5, autocommit=True)
with conn.cursor() as cur:
    cur.execute('USE hly_accesscard')
    cur.execute('DESCRIBE accesscard_test_diff')
    cols = cur.fetchall()
    print()
    print('--- 5. 验证 hly_accesscard.accesscard_test_diff 字段 (期望无 blocked_field) ---')
    has_blocked = False
    for col in cols:
        print(f'    {col[0]} {col[1]}')
        if col[0] == 'blocked_field':
            has_blocked = True
    print(f'  has blocked_field: {has_blocked} (期望 False)')

conn.close()
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d10_case_d.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d10_case_d.py 2>&1',
    'rm -f /tmp/_d10_case_d.py',
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
