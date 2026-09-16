"""W3 134 dev 列业务库表 + PK + count"""
import sys, os, django
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()

from sql.models import Instance
from sql.utils.pk_conflict_check import _fetch_table_pk_column

instance = Instance.objects.get(id=2)
for db in ["archery_dev", "archery_test"]:
    print(f"=== {db} ===")
    import pymysql
    conn = pymysql.connect(host=instance.host, port=instance.port,
                           user=instance.user, password=instance.password,
                           database=db, charset="utf8mb4", connect_timeout=5)
    with conn.cursor() as c:
        c.execute("SHOW TABLES")
        tables = [r[0] for r in c.fetchall()]
        for t in tables[:5]:
            pk_col = _fetch_table_pk_column(instance, db, t)
            c.execute("SELECT COUNT(*) FROM `%s`" % t)
            count = c.fetchone()[0]
            print("  %s: pk_col=%r, count=%d" % (t, pk_col, count))
    conn.close()