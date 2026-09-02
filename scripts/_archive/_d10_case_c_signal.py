#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D10 演练 Case C: 模拟业务 RD 提 SqlWorkflow 走 PASSED, 触发 R3 workflow_passed_handler signal
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
from django.db.models.signals import post_save
from common.utils.const import WorkflowStatus
from sql.models import SqlWorkflow, SqlWorkflowContent, WorkflowAudit
from sql.extensions.ddl_sync.models import DdlSyncPair, DdlSyncHistory

# 1. 拿 superuser 当 engineer
from django.contrib.auth import get_user_model
Users = get_user_model()
admin_user = Users.objects.filter(is_superuser=True).first()

# 2. 拿 group_id + group_name (从 Instance 的 resource_group 拿, 实战 source_workflow 的 group_id)
archery_ins = SqlWorkflow._meta.get_field('instance').related_model.objects.get(id=1)
group_id = archery_ins.resource_group.first().group_id if archery_ins.resource_group.first() else 1
group_name = archery_ins.resource_group.first().group_name if archery_ins.resource_group.first() else '默认组'
print(f'1. group_id={group_id} group_name={group_name}')

# 3. 模拟业务 RD 提工单 (status=workflow_review_pass + audit PASSED)
print()
print('--- 2. 模拟业务 RD 提工单 ALTER TABLE accesscard_account ---')
sql_text = \"\"\"ALTER TABLE accesscard_account ADD COLUMN phone VARCHAR(20) DEFAULT NULL COMMENT '手机号'\"\"\"
print(f'  SQL: {sql_text}')

wf = SqlWorkflow.objects.create(
    workflow_name='[Case C 演练] accesscard_account 加 phone 字段',
    group_id=group_id,
    group_name=group_name,
    engineer='mkq',  # 业务 RD 用户名 (实战有 110 prod 用户, 134 dev 演练用 mkq 模拟)
    engineer_display='mkq 业务 RD',
    audit_auth_groups='1',  # 占位, 实战走 audit_handler.create_audit()
    status='workflow_manreviewing',  # 业务 RD 提工单初始状态
    syntax_type=1,  # DDL
    is_backup=True,
    instance=archery_ins,
    db_name='hly_accesscard',
)
SqlWorkflowContent.objects.create(
    workflow=wf, sql_content=sql_text, review_content='[]', execute_result='',
)
print(f'  workflow.id={wf.id} status={wf.status}')

# 4. 模拟 passed() 走完: 业务组审完 + audit PASSED, status 改 workflow_review_pass
print()
print('--- 3. 模拟 passed() 走完 (audit PASSED + status=workflow_review_pass) ---')
# 实战 passed() 创建 WorkflowAudit
WorkflowAudit.objects.filter(workflow_id=wf.id, workflow_type=2).delete()  # 清旧
audit = WorkflowAudit.objects.create(
    group_id=group_id,
    group_name=group_name,
    workflow_id=wf.id,
    workflow_type=2,  # SQL_REVIEW
    workflow_title=wf.workflow_name,
    audit_auth_groups='1',
    current_audit='-1',
    next_audit='-1',
    current_status=WorkflowStatus.PASSED,
    create_user='mkq',
    create_user_display='mkq 业务 RD',
)
print(f'  audit.id={audit.audit_id} current_status={audit.current_status}')

# 5. 触发 save() (实战 passed() 最后调 auditor.workflow.save())
wf.status = 'workflow_review_pass'
wf.save()
print(f'  workflow.status now: {wf.status}')

# 6. 验证 DdlSyncHistory 写入
print()
print('--- 4. 验证 DdlSyncHistory 写入 ---')
histories = DdlSyncHistory.objects.filter(source_workflow=wf).order_by('-created_at')
print(f'  DdlSyncHistory 数: {histories.count()}')
for h in histories:
    pair = h.pair
    print(f'  history.id={h.id}')
    print(f'    pair: {pair.name} (#{pair.id})')
    print(f'    source_workflow: #{h.source_workflow_id}')
    print(f'    target_workflow: #{h.target_workflow_id}')
    print(f'    table_name: {h.table_name}')
    print(f'    sync_status: {h.sync_status}')
    print(f'    ddl_text: {h.ddl_text[:80]}...')
    print(f'    transformed_ddl_text: {h.transformed_ddl_text[:80]}...')
    if h.target_workflow:
        tw = h.target_workflow
        print(f'    镜像工单: id={tw.id} name={tw.workflow_name}')
        print(f'      instance: {tw.instance.instance_name} db={tw.db_name}')
        print(f'      group: {tw.group_name}')
        print(f'      status: {tw.status}')
        print(f'      audit_auth_groups: {tw.audit_auth_groups}')
        # 拿 target 的 sql_content
        try:
            twc = tw.sqlworkflowcontent
            print(f'      sql_content: {twc.sql_content[:80]}...')
        except Exception as e:
            print(f'      sql_content 拿不到: {e}')

# 7. 看 WorkflowAudit 镜像工单是否走 audit_setting
print()
print('--- 5. 验证 audit_handler.create_audit() 走 audit_setting ---')
if h.target_workflow:
    tw = h.target_workflow
    target_audit = WorkflowAudit.objects.filter(workflow_id=tw.id, workflow_type=2).first()
    if target_audit:
        print(f'  镜像工单 audit: id={target_audit.audit_id}')
        print(f'    current_audit: {target_audit.current_audit}')
        print(f'    next_audit: {target_audit.next_audit}')
        print(f'    current_status: {target_audit.current_status}')
        print(f'    audit_auth_groups: {target_audit.audit_auth_groups}')
        print(f'  PASS: audit_handler.create_audit() 真的创建了 audit')
    else:
        print(f'  镜像工单 audit 未创建 (audit_setting 没配 或 fallback)')
"""

REMOTE_CMDS = [
    'cd /opt/archery/prod && cat > /tmp/_d10_case_c.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d10_case_c.py 2>&1',
    'rm -f /tmp/_d10_case_c.py',
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
