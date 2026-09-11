#!/bin/bash
# 134 dev 造审批中工单 wf#9999 (SqlWorkflow + SqlWorkflowContent)
set -e
cd /opt/archery/prod
export DJANGO_SETTINGS_MODULE=archery.settings
sudo -u archery /opt/archery/prod/venv/bin/python <<'PYEOF'
import sys, os, django
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()
from sql.models import SqlWorkflow, SqlWorkflowContent, Users, Instance
import datetime

ins = Instance.objects.filter(db_type="mysql").first()
u = Users.objects.filter(username="archery").first()
print("instance:", ins.instance_name if ins else None, ins.host if ins else None, ins.port if ins else None)
print("engineer:", u.username if u else None)

if not ins or not u:
    print("MISSING, ABORT")
    sys.exit(1)

# wf#4803 同款 SQL 形态 (use + 注释 + ALTER), 134 dev 上用 archery_prod 库 + sql_workflow 表 (大表)
# sql_workflow 上有 group_id 索引 (Django auto_add)
sql_content = "use archery_prod;\n-- 删除无用索引 idx_show_flag\n-- 删除无用索引 idx_sync_flag\nALTER TABLE waybill_union_carrier_dba_bug1 drop index idx_way_bill_id"

wf, created = SqlWorkflow.objects.update_or_create(
    id=9999,
    defaults={
        "workflow_name": "DBA-bug-1 演练 审批中工单 (drop index)",
        "group_id": 1,
        "group_name": "DBA",
        "engineer": u.username,
        "engineer_display": u.display,
        "audit_auth_groups": "研发组长,研发负责人,副总,DBA",
        "create_time": datetime.datetime.now(),
        "finish_time": None,
        "status": "workflow_manreviewing",  # 审批中!
        "is_backup": False,
        "instance": ins,
        "instance_id": ins.id,
        "db_name": "archery_prod",
    },
)
print("wf.id=", wf.id, "status=", wf.status, "created=", created)

# 单独存 SQL
content, _ = SqlWorkflowContent.objects.update_or_create(
    workflow=wf,
    defaults={
        "sql_content": sql_content,
        "review_content": "",
        "execute_result": "",
    },
)
print("content.id=", content.id, "SQL=", repr(sql_content[:120]))
PYEOF
