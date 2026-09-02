#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D11 hotfix #6: 推 sync_trigger.py 加 workflow_terminal_handler + restart gunicorn + 演练 1 次
"""
import io
import sys
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DEV_HOST = '172.20.2.134'
DEV_PORT = 22
DEV_USER = 'root'
DEV_PASS = 'CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW'

LOCAL_BASE = 'G:\\MiniMax工作空间\\archery_dev'
REMOTE_BASE = '/opt/archery/prod'

TEST_CODE = """
import django
django.setup()

from sql.models import SqlWorkflow, SqlWorkflowContent
from sql.extensions.ddl_sync.models import DdlSyncHistory
from django.utils import timezone
from common.utils.const import WorkflowStatus

print('=== 演练 workflow_terminal_handler ===')
# 1. 实战场景: 源工单 #109 已经 status=workflow_review_pass + R3 已触发 (#110 + DdlSyncHistory id=3)
# 实战设计: 模拟源工单 #109 失败 → 联动 #110 终止
# 实战: 模拟触发 workflow_terminal_handler
from django.db.models.signals import post_save
from sql.extensions.ddl_sync.services.sync_trigger import workflow_terminal_handler

# 1.1 实战状态确认
wf109 = SqlWorkflow.objects.get(id=109)
print(f'演练前 #109: status={wf109.status}')

wf110 = SqlWorkflow.objects.get(id=110)
print(f'演练前 #110: status={wf110.status}')

h3 = DdlSyncHistory.objects.get(id=3)
print(f'演练前 DdlSyncHistory #3: sync_status={h3.sync_status} target_workflow_id={h3.target_workflow_id}')

# 1.2 模拟源工单 #109 失败 (workflow_exception)
wf109.status = 'workflow_exception'
wf109.save()  # post_save signal 触发 workflow_terminal_handler
print()
print(f'演练中: 模拟 #109 save() → status=workflow_exception')
print('  ↑ 实战 workflow_terminal_handler 应该联动终止 #110 + DdlSyncHistory #3')

# 1.3 实战状态确认
wf110 = SqlWorkflow.objects.get(id=110)
print(f'演练后 #110: status={wf110.status} (期望 workflow_exception)')

h3 = DdlSyncHistory.objects.get(id=3)
print(f'演练后 DdlSyncHistory #3:')
print(f'  sync_status={h3.sync_status} (期望 failed)')
print(f'  error_message={h3.error_message}')
print(f'  finished_at={h3.finished_at}')

# 2. reset (用户后续还能演练)
wf109.status = 'workflow_review_pass'
wf109.save()
wf110.status = 'workflow_review_pass'
wf110.save()
h3.sync_status = 'syncing'
h3.error_message = ''
h3.finished_at = None
h3.save()
print()
print('=== 演练后 reset 到原始状态, 用户可继续演练 ===')
print(f'  #109 reset: status={wf109.status}')
print(f'  #110 reset: status={wf110.status}')
print(f'  DdlSyncHistory #3 reset: sync_status={h3.sync_status}')
"""

REMOTE_CMDS = [
    # 1. 备份
    'cp /opt/archery/prod/sql/extensions/ddl_sync/services/sync_trigger.py /opt/archery/prod/sql/extensions/ddl_sync/services/sync_trigger.py.bak_20260902_1545',
    # 2. chown
    'chown -R archery:archery /opt/archery/prod/sql/extensions/ddl_sync/',
    # 3. 清 __pycache__
    'find /opt/archery/prod -name "__pycache__" -type d 2>/dev/null | xargs rm -rf 2>/dev/null || true',
    # 4. kill gunicorn + nohup 拉新
    'pkill -9 -f gunicorn || true',
    'sleep 2',
    'bash -c "cd /opt/archery/prod && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn.log 2>&1 &"',
    'sleep 5',
    'ps -eo pid,etime,cmd | grep "gunicorn archery" | grep -v grep | head -3',
    'ss -tnlp | grep 9003 || echo "9003 端口空"',
    # 5. 演练 workflow_terminal_handler
    'cd /opt/archery/prod && cat > /tmp/_d11_cascade.py << "PYEOF"\n' + TEST_CODE + '\nPYEOF',
    'cd /opt/archery/prod && sudo -u archery venv/bin/python manage.py shell < /tmp/_d11_cascade.py 2>&1',
    'rm -f /tmp/_d11_cascade.py',
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
        # SFTP 推 sync_trigger.py
        sftp = ssh.open_sftp()
        local_path = LOCAL_BASE + chr(92) + 'sql' + chr(92) + 'extensions' + chr(92) + 'ddl_sync' + chr(92) + 'services' + chr(92) + 'sync_trigger.py'
        remote_path = f'{REMOTE_BASE}/sql/extensions/ddl_sync/services/sync_trigger.py'
        print(f'PUT sync_trigger.py -> {remote_path}')
        with open(local_path, 'rb') as f:
            data = f.read()
        with sftp.open(remote_path, 'wb') as rf:
            rf.write(data)
        print(f'  size={len(data)} OK')
        sftp.close()

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
