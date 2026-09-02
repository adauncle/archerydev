"""D13 实战演练 - 134 dev 5 张表演练 + 实战多表 DDL column_diff 端点"""
import paramiko
import json
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)

def run(c, t=10):
    si, so, se = ssh.exec_command(c, timeout=t)
    return so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")

# 上传演练脚本
drill_script = r'''
import os, sys, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
sys.path.insert(0, "/opt/archery/prod")
import django
django.setup()

from sql.models import SqlWorkflow, Instance, Users
from django.test import Client

# 1. 找 instance
instance = Instance.objects.filter(type="test").first() or Instance.objects.first()
print(f"using instance {instance.id} {instance.instance_name}", flush=True)

# 2. 实战汪银和风格的多表 DDL (7 张表)
multi_table_sql = """ALTER TABLE project_config ADD use_waybill_protocol int DEFAULT 2 NULL COMMENT '是否使用运单协议1: 是 2: 否';
ALTER TABLE project_config ADD wh_waybill_ignore_protocol int DEFAULT 1 NULL COMMENT '网页运单是否免责协议1: 是 2: 否';
ALTER TABLE company_info ADD waybill_protocol_service int DEFAULT 1 NULL COMMENT '运单协议服务开通状态（1：未开通 2 已开通）';
ALTER TABLE team ADD logo_open_status int DEFAULT '2' COMMENT '品牌露出服务1 已开通 2 未开通';
ALTER TABLE team ADD logo_open_time datetime DEFAULT NULL COMMENT '品牌露出服务开通时间';
ALTER TABLE order_penalty MODIFY penalty_item varchar(200) null comment '扣罚项';
ALTER TABLE waybill_penalty MODIFY penalty_item varchar(200) null comment '扣罚项';"""

# 3. 直接调 column_diff_full (不走 HTTP, 实战 dryrun)
from sql.extensions.ddl_gh_ost.services.column_diff import column_diff_full
result = column_diff_full(instance, "hly_platform", multi_table_sql)
print(f"ok={result.get('ok')}", flush=True)
print(f"tables: {len(result.get('tables', []))} 张", flush=True)
print(f"high={result.get('high_risk_count')} mid={result.get('mid_risk_count')} low={result.get('low_risk_count')}", flush=True)
print(f"summary: {result.get('summary')}", flush=True)
print("---", flush=True)
for t in result.get("tables", []):
    if not t.get("ok"):
        print(f"  [ERROR] {t.get('table_name')}: {t.get('error')}", flush=True)
        continue
    print(f"  [{t.get('table_name')}] high={t.get('high_risk_count')} mid={t.get('mid_risk_count')} low={t.get('low_risk_count')}", flush=True)
    for c in t.get("columns", []):
        n_diff = len(c.get("diffs", []))
        if c.get("operation") == "ADD" and n_diff == 0:
            print(f"    + {c.get('name')} (新列)", flush=True)
        else:
            print(f"    {c.get('operation')} {c.get('name')}: {n_diff} diff", flush=True)
            for d in c.get("diffs", []):
                print(f"      · {d.get('field')}: {d.get('risk')} - {d.get('reason')[:60]}", flush=True)

# 4. 测端点 (走 HTTP /gh_ost/column_diff/)
print("---", flush=True)
print("=== 走端点 /gh_ost/column_diff/ ===", flush=True)
c = Client(SERVER_NAME="127.0.0.1")
# 找 admin
admin = Users.objects.filter(is_superuser=True).first()
c.force_login(admin) if admin else None
r = c.post("/gh_ost/column_diff/", {
    "instance_id": instance.id,
    "db_name": "hly_platform",
    "sql_content": multi_table_sql,
})
print(f"status={r.status_code}", flush=True)
try:
    data = json.loads(r.content)
    print(f"ok={data.get('ok')} tables={len(data.get('tables', []))} high={data.get('high_risk_count')}", flush=True)
except Exception as e:
    print(f"parse err: {e}", flush=True)
    print(r.content[:500], flush=True)
'''
sftp = ssh.open_sftp()
with sftp.file("/tmp/d13_drill.py", "w") as f:
    f.write(drill_script)
sftp.close()

# 用 archery 用户跑 (走 systemd env, mirage key 不 assert)
out, _ = run("sudo -u archery bash -lc 'cd /opt/archery/prod && /opt/archery/prod/venv/bin/python /tmp/d13_drill.py' 2>&1")
print("=== 演练输出 ===", flush=True)
print(out, flush=True)

# 看 mysql 端点实战 (汪银和工单是在 110 prod, 134 dev 没法模拟, 但 column_diff 端点只需要 SQL+instance_id, 不需要真工单)
# 端点 200 OK 就 OK

ssh.close()
print("DONE", flush=True)
