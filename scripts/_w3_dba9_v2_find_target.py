"""找 110 prod 上有 accesscard_black_detail 大表的 instance"""
import os
import sys

sys.path.insert(0, "/dbdata/archery_v114_c9236a0")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django

django.setup()

from sql.models import Instance  # noqa: E402
import pymysql

# 试 instance 5 (prod core for etc) + 数据库 hly_accesscard
for inst_id in [5, 27, 31]:
    try:
        inst = Instance.objects.get(id=inst_id)
        user, password = inst.get_username_password()
        conn = pymysql.connect(
            host=inst.host, port=int(inst.port), user=user, password=password,
            database="hly_accesscard", connect_timeout=5, autocommit=True,
        )
        with conn.cursor() as cur:
            cur.execute("""
                SELECT TABLE_NAME, TABLE_ROWS, ROUND((DATA_LENGTH + INDEX_LENGTH)/1024/1024, 1) AS size_mb
                FROM information_schema.tables
                WHERE TABLE_SCHEMA = 'hly_accesscard' AND TABLE_ROWS >= 100000
                ORDER BY TABLE_ROWS DESC
                LIMIT 5
            """)
            print(f"=== inst={inst.id} {inst.instance_name} ===")
            rows = cur.fetchall()
            for row in rows:
                print(f"  {row[0]:50s} rows={row[1]:>10} size={row[2]} MB")
        conn.close()
    except Exception as exc:
        print(f"  inst={inst_id} skip: {str(exc)[:80]}")