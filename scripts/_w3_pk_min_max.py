"""查 accesscard_account 现有 id 范围"""
import sys, os, django
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()

from sql.models import Instance
import pymysql

instance = Instance.objects.get(id=2)
conn = pymysql.connect(host=instance.host, port=instance.port,
                       user=instance.user, password=instance.password,
                       database="archery_dev", charset="utf8mb4", connect_timeout=5)
with conn.cursor() as c:
    c.execute("SELECT MIN(id), MAX(id), COUNT(*) FROM `accesscard_account`")
    row = c.fetchone()
    print("MIN(id)=", row[0], "MAX(id)=", row[1], "COUNT=", row[2])
    c.execute("SELECT id FROM `accesscard_account` ORDER BY id LIMIT 5")
    print("first 5:", [r[0] for r in c.fetchall()])
conn.close()