"""D13 实战演练 v2 - 134 dev 造 5 张表 + 实战 column_diff 端点"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)

def run(c, t=10):
    si, so, se = ssh.exec_command(c, timeout=t)
    return so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")

# 实战:在 134 dev 测试 MySQL (127.0.0.1:3306) 造 5 张表 (演练用,不破坏 134 dev 实际数据)
# 134 dev instance 2 = 测试 MySQL 8.0 (从 instance type=test)
# 但 9/1+9/2 已经在 134 dev 演练库 hly_accesscard 造了 5 张表演练表 (D10 实战)

# 实战 9/1 D10 已经在 134 dev hly_accesscard 造了 accesscard_test_diff 等表, 直接用
drill_script = r'''
import os, sys, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
sys.path.insert(0, "/opt/archery/prod")
import django
django.setup()

from sql.models import SqlWorkflow, Instance, Users
from django.test import Client

# 1. 找 instance (archery 134 dev 的 instance 1 是 172.20.2.134:3306)
instance = Instance.objects.filter(instance_name__contains="archery").first()
if not instance:
    instance = Instance.objects.first()
print(f"using instance {instance.id} {instance.instance_name} host={instance.host}:{instance.port}", flush=True)

# 2. 列出现有 db
import pymysql
user, password = instance.user, instance.password
# mirage 加密的解密 (跟 column_diff 一样)
try:
    user = instance.get_username_password()[0]
    password = instance.get_username_password()[1]
except Exception:
    pass
print(f"user={user}", flush=True)

# 3. 看 134 dev 实际有什么库 + accesscard_test_diff 表
conn = pymysql.connect(host=instance.host, port=instance.port, user=user, password=password, connect_timeout=5)
cur = conn.cursor()
cur.execute("SHOW DATABASES")
dbs = [r[0] for r in cur.fetchall()]
print(f"dbs: {dbs}", flush=True)

# 4. 找演练库 - 134 dev W2 D10 实战已经在 hly_accesscard 造了 accesscard_test_diff1/2/3/4/5
# 看 accesscard_test_diff 表 list
cur.execute("USE hly_accesscard")
cur.execute("SHOW TABLES LIKE 'accesscard_test%'")
tables = [r[0] for r in cur.fetchall()]
print(f"accesscard_test tables: {tables}", flush=True)

# 5. 实战 5 张表演练 - 改各表的列, 模拟多表 DDL
drill_sql = """ALTER TABLE accesscard_test_diff1
    MODIFY name varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'test' COMMENT '新名称';
ALTER TABLE accesscard_test_diff1
    ADD new_col varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '新列';
ALTER TABLE accesscard_test_diff2
    MODIFY id bigint(20) NOT NULL AUTO_INCREMENT COMMENT 'BIGINT id';
ALTER TABLE accesscard_test_diff3
    ADD col3 varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'x' COMMENT 'col3';
ALTER TABLE accesscard_test_diff4
    DROP old_col;
ALTER TABLE accesscard_test_diff5
    MODIFY id int(11) NOT NULL DEFAULT 0 COMMENT 'ID';"""

# 6. 直接调 column_diff_full
from sql.extensions.ddl_gh_ost.services.column_diff import column_diff_full
result = column_diff_full(instance, "hly_accesscard", drill_sql)
print("---", flush=True)
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
        elif n_diff == 0:
            print(f"    {c.get('operation')} {c.get('name')}: 无 diff", flush=True)
        else:
            print(f"    {c.get('operation')} {c.get('name')}: {n_diff} diff", flush=True)
            for d in c.get("diffs", []):
                print(f"      · {d.get('field')}: {d.get('risk')} - {d.get('reason')[:60]}", flush=True)

# 7. 测端点 /gh_ost/column_diff/
print("---", flush=True)
print("=== 走端点 /gh_ost/column_diff/ ===", flush=True)
c = Client(SERVER_NAME="127.0.0.1")
admin = Users.objects.filter(is_superuser=True).first()
c.force_login(admin) if admin else None
r = c.post("/gh_ost/column_diff/", {
    "instance_id": instance.id,
    "db_name": "hly_accesscard",
    "sql_content": drill_sql,
})
print(f"status={r.status_code}", flush=True)
try:
    data = json.loads(r.content)
    print(f"ok={data.get('ok')} tables={len(data.get('tables', []))} high={data.get('high_risk_count')} mid={data.get('mid_risk_count')} low={data.get('low_risk_count')}", flush=True)
    print(f"summary: {data.get('summary')}", flush=True)
    for t in data.get("tables", [])[:3]:
        print(f"  sample: {t.get('table_name')} high={t.get('high_risk_count')}", flush=True)
except Exception as e:
    print(f"parse err: {e}", flush=True)
    print(r.content[:500], flush=True)
'''
sftp = ssh.open_sftp()
with sftp.file("/tmp/d13_drill2.py", "w") as f:
    f.write(drill_script)
sftp.close()

# 跑
out, _ = run("sudo -u archery bash -lc 'cd /opt/archery/prod && /opt/archery/prod/venv/bin/python /tmp/d13_drill2.py' 2>&1 | tail -60")
print("=== 演练输出 (tail 60) ===", flush=True)
print(out, flush=True)

ssh.close()
print("DONE", flush=True)
