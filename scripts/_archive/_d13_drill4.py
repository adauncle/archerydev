"""D13 实战演练 v4 - 用 Django 内部 connection 建演练表 + 实战 column_diff"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)

def run(c, t=10):
    si, so, se = ssh.exec_command(c, timeout=t)
    return so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")

drill_script = r'''
import os, sys, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
sys.path.insert(0, "/opt/archery/prod")
import django
django.setup()

from sql.models import Instance, Users
from django.db import connection
from django.test import Client

# 1. 用 instance 1 (archery) 的连接建演练表
instance = Instance.objects.filter(instance_name__contains="archery").first() or Instance.objects.first()
print(f"using instance {instance.id} {instance.instance_name}", flush=True)

# 2. 走 Archery 自带的连接 (跟 gh-ost / column_diff 一样)
from archery import settings as dj_settings
# 走 instance.get_username_password 拿 dbops user / pwd
user, password = instance.get_username_password()
print(f"user={user}", flush=True)

import pymysql
conn = pymysql.connect(host=instance.host, port=instance.port, user=user, password=password, connect_timeout=5)
cur = conn.cursor()

# 3. 造 5 张演练表 (如果已存在先 DROP)
create_sql = [
    "USE hly_accesscard",
    "DROP TABLE IF EXISTS accesscard_test_diff1",
    "DROP TABLE IF EXISTS accesscard_test_diff2",
    "DROP TABLE IF EXISTS accesscard_test_diff3",
    "DROP TABLE IF EXISTS accesscard_test_diff4",
    "DROP TABLE IF EXISTS accesscard_test_diff5",
    """CREATE TABLE accesscard_test_diff1 (
        id INT(11) NOT NULL AUTO_INCREMENT,
        name VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL,
        old_col VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE accesscard_test_diff2 (
        id INT(11) NOT NULL AUTO_INCREMENT,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE accesscard_test_diff3 (
        id INT(11) NOT NULL AUTO_INCREMENT,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE accesscard_test_diff4 (
        id INT(11) NOT NULL AUTO_INCREMENT,
        old_col VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE accesscard_test_diff5 (
        id INT(11) NOT NULL AUTO_INCREMENT,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    "SHOW TABLES LIKE 'accesscard_test_diff%'",
]
for s in create_sql:
    cur.execute(s)
conn.commit()
cur.execute("SHOW TABLES LIKE 'accesscard_test_diff%'")
print("created tables:", [r[0] for r in cur.fetchall()], flush=True)
conn.close()

# 4. 5 张表演练 - 模拟汪银和风格的多表 DDL
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

# 5. 直接调 column_diff_full
from sql.extensions.ddl_gh_ost.services.column_diff import column_diff_full
result = column_diff_full(instance, "hly_accesscard", drill_sql)
print("=" * 60, flush=True)
print("实战 1: column_diff_full 多表 DDL dryrun", flush=True)
print("=" * 60, flush=True)
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
            print(f"    + {c.get('name')} (新列, 无冲突)", flush=True)
        elif n_diff == 0:
            print(f"    {c.get('operation')} {c.get('name')}: 无 diff", flush=True)
        else:
            print(f"    {c.get('operation')} {c.get('name')}: {n_diff} diff", flush=True)
            for d in c.get("diffs", []):
                print(f"      · {d.get('field')}: {d.get('risk')} - {d.get('reason')[:60]}", flush=True)
            if c.get("suggested_sql"):
                print(f"      [SUGGESTED] {c['suggested_sql'][:80]}", flush=True)

# 6. 走端点 /gh_ost/column_diff/
print("---", flush=True)
print("=" * 60, flush=True)
print("实战 2: 走端点 /gh_ost/column_diff/", flush=True)
print("=" * 60, flush=True)
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
    for t in data.get("tables", []):
        if not t.get("ok"):
            print(f"  [ERROR] {t.get('table_name')}: {t.get('error')}", flush=True)
        else:
            print(f"  [{t.get('table_name')}] high={t.get('high_risk_count')} mid={t.get('mid_risk_count')} low={t.get('low_risk_count')}", flush=True)
except Exception as e:
    print(f"parse err: {e}", flush=True)
    print(r.content[:500], flush=True)
'''
sftp = ssh.open_sftp()
with sftp.file("/tmp/d13_drill4.py", "w") as f:
    f.write(drill_script)
sftp.close()

print("=== 跑演练脚本 ===", flush=True)
out, _ = run("sudo -u archery bash -lc 'cd /opt/archery/prod && /opt/archery/prod/venv/bin/python /tmp/d13_drill4.py' 2>&1 | tail -80")
print(out, flush=True)

ssh.close()
print("DONE", flush=True)
