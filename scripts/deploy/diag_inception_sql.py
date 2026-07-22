"""打印 Archery 实际发给 goInception 的 SQL"""
import os
import sys

sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()

from sql.engines.goinception import GoInceptionEngine, get_session_variables
from sql.models import Instance
from common.config import SysConfig

inst = Instance.objects.get(instance_name="测试 MySQL 8.0")
engine = GoInceptionEngine(instance=inst)

# 模拟 execute_check 内部的 SQL 构造
host, port, user, password = engine.remote_instance_conn(inst)
print(f"remote_host={host}, remote_port={port}, remote_user={user!r}")
print(f"remote_password set: {bool(password)}")
print()

real_row_count = SysConfig().get("real_row_count", False)
real_row_count_option = "--real_row_count=true;" if real_row_count else ""
variables, set_session_sql = get_session_variables(inst)
print(f"set_session_sql: {set_session_sql!r}")
print()

db_name = "archery_dev"
sql = "CREATE TABLE test (id bigint NOT NULL, PRIMARY KEY (id))"
inception_sql = f"""/*--user='{user}';--password='{password}';--host='{host}';--port={port};--check=1;{real_row_count_option}*/
                    inception_magic_start;
                    {set_session_sql}
                    use `{db_name}`;
                    {sql.rstrip(';')};
                    inception_magic_commit;"""

print("=" * 70)
print("实际发到 goInception 的 SQL:")
print("=" * 70)
print(inception_sql)
print()
print("=" * 70)
print("直接 MySQLdb 连 goInception 执行")
print("=" * 70)
import MySQLdb
try:
    conn = MySQLdb.connect(
        host="127.0.0.1", port=4000, user="root", passwd="", connect_timeout=5,
    )
    cur = conn.cursor()
    cur.execute(inception_sql)
    rows = cur.fetchall()
    print(f"✓ 收到 {len(rows)} 行结果")
    for r in rows[:20]:
        print(f"  {r}")
    conn.close()
except Exception as e:
    print(f"✗ {type(e).__name__}: {e}")
