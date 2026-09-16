"""看 134 dev archery_dev 库有哪些表 + 多少行"""
import os
import sys

sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django

django.setup()

from sql.models import Instance  # noqa: E402

inst = Instance.objects.get(id=1)
user, password = inst.get_username_password()
import pymysql

conn = pymysql.connect(
    host=inst.host, port=int(inst.port), user=user, password=password,
    database="archery_dev", connect_timeout=5, autocommit=True,
)
with conn.cursor() as cur:
    cur.execute("""
        SELECT TABLE_NAME, TABLE_ROWS, ROUND((DATA_LENGTH + INDEX_LENGTH)/1024/1024, 1) AS size_mb
        FROM information_schema.tables
        WHERE TABLE_SCHEMA = 'archery_dev' AND TABLE_ROWS >= 100000
        ORDER BY TABLE_ROWS DESC
        LIMIT 10
    """)
    print("=== 134 dev archery_dev 大表 (≥10w 行) ===")
    for row in cur.fetchall():
        print(f"  {row[0]:50s} rows={row[1]:>10} size={row[2]} MB")
conn.close()