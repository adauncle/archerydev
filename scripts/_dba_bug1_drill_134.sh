#!/bin/bash
# DBA-bug-1 134 dev 演练: 造一个审批中工单 wf#9999 (wf#4803 同款 SQL)
set -e
cd /opt/archery/prod
export DJANGO_SETTINGS_MODULE=archery.settings

# 1. reload gunicorn (清缓存)
echo "=== [1/5] reload gunicorn ==="
ps -ef | grep gunicorn | head -3
sudo -u archery bash -c "kill -HUP \$(cat /opt/archery/prod/gunicorn.pid 2>/dev/null) 2>/dev/null || pkill -HUP -f 'gunicorn archery.wsgi' 2>/dev/null; sleep 2"
ps -ef | grep gunicorn | head -3

# 2. 造审批中工单 wf#9999
echo ""
echo "=== [2/5] 造审批中工单 wf#9999 (wf#4803 同款 drop index SQL) ==="
sudo -u archery bash -c "/opt/archery/prod/venv/bin/python -c '
import sys, os, django
sys.path.insert(0, \"/opt/archery/prod\")
os.environ.setdefault(\"DJANGO_SETTINGS_MODULE\", \"archery.settings\")
django.setup()
from sql.models import SqlWorkflow, Users
from django.contrib.auth.models import Group
import datetime

# 找一个实例 (hly_platform 在 110 prod, 134 dev 找任意一个)
from sql.models import Instance
ins = Instance.objects.filter(db_type=\"mysql\").first()
print(\"instance:\", ins.instance_name, ins.host, ins.port)

# 找一个提交人
u = Users.objects.filter(username=\"archery\").first()
print(\"engineer:\", u.username)

# wf#4803 同款 SQL
sql_content = \"use hly_platform;\n-- 删除无用索引 idx_show_flag\n-- 删除无用索引 idx_sync_flag\nALTER TABLE waybill_union_carrier drop index idx_way_bill_id\"

wf, created = SqlWorkflow.objects.get_or_create(
    id=9999,
    defaults={
        \"workflow_name\": \"DBA-bug-1 演练 审批中工单 (drop index)\",
        \"group_id\": 1,
        \"group_name\": u.group.group_name if u.group else \"DBA\",
        \"engineer\": u.username,
        \"engineer_display\": u.display,
        \"audit_auth_groups\": \"研发组长,研发负责人,副总,DBA\",
        \"create_time\": datetime.datetime.now(),
        \"status\": \"workflow_manreviewing\",  # 审批中!
        \"is_backup\": False,
        \"instance\": ins,
        \"instance_id\": ins.id,
        \"db_name\": \"hly_platform\",
        \"sql_content\": sql_content,
        \"sql_backup_content\": \"\",
    },
)
if not created:
    wf.status = \"workflow_manreviewing\"
    wf.sql_content = sql_content
    wf.save()
print(\"wf.id=\", wf.id, \"status=\", wf.status)
print(\"SQL=\", wf.sql_content)
' 2>&1"
