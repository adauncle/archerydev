# -*- coding: utf-8 -*-
"""查 accesscard_black_detail 实际有 auto_increment 字段"""
import os, sys
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django; django.setup()
from sql.models import Instance
import pymysql

inst = Instance.objects.get(pk=2)
u, p = inst.get_username_password()
c = pymysql.connect(host=inst.host, port=inst.port, user=u, password=p, database="archery_dev", autocommit=True)
with c.cursor() as cur:
    cur.execute("""SELECT COLUMN_NAME, COLUMN_TYPE, CHARACTER_SET_NAME, COLLATION_NAME,
                          IS_NULLABLE, COLUMN_DEFAULT, EXTRA
                   FROM information_schema.columns
                   WHERE TABLE_SCHEMA='archery_dev' AND TABLE_NAME='accesscard_black_detail'
                       AND EXTRA LIKE '%auto_increment%'""")
    print("=== 演练表有 auto_increment 的字段 ===")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]} charset={r[2] or '-'} coll={r[3] or '-'} nullable={r[4]} default={r[5]} extra={r[6]}")
c.close()
