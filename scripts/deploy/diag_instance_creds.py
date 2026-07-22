"""诊断: 测试 MySQL 8.0 实例的实际 user/password 是什么。"""
import os
import sys

sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()

from sql.models import Instance

inst = Instance.objects.get(instance_name="测试 MySQL 8.0")
print("=" * 70)
print(f"Instance: {inst.instance_name} (id={inst.id})")
print("=" * 70)
print(f"  type:        {inst.type}")
print(f"  db_type:     {inst.db_type}")
print(f"  host:port:   {inst.host}:{inst.port}")
print(f"  user:        {inst.user!r}")
print(f"  password:    {'<set>' if inst.password else '<empty>'}")
print(f"  db_name:     {inst.db_name!r}")

# Check direct MySQL connection
print()
print("=" * 70)
print("直接用 dbops 连接测试 MySQL 8.0")
print("=" * 70)
import MySQLdb
from django.conf import settings
print(f"  HOST: {inst.host}, PORT: {inst.port}, USER: {inst.user}")
try:
    conn = MySQLdb.connect(
        host=inst.host, port=inst.port,
        user=inst.user, passwd=inst.password,
        connect_timeout=5,
    )
    cur = conn.cursor()
    cur.execute("SELECT USER(), VERSION()")
    user, ver = cur.fetchone()
    print(f"  ✓ 连接成功 USER={user!r} VERSION={ver!r}")
    cur.execute("SHOW DATABASES")
    print(f"  databases: {[r[0] for r in cur.fetchall()]}")
    conn.close()
except Exception as e:
    print(f"  ✗ {type(e).__name__}: {e}")
