# -*- coding: utf-8 -*-
"""建测试表 accesscard_test_diff"""
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
    cur.execute("DROP TABLE IF EXISTS accesscard_test_diff")
    cur.execute("""
        CREATE TABLE accesscard_test_diff (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            status VARCHAR(2) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL,
            biz_type VARCHAR(2) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL,
            operator_id BIGINT NULL,
            name VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT '' COMMENT '用户名'
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cur.execute("INSERT INTO accesscard_test_diff (status, biz_type, operator_id, name) VALUES ('01', '02', 100, 'test1')")
    cur.execute("INSERT INTO accesscard_test_diff (status, biz_type, operator_id, name) VALUES (NULL, '03', 200, 'test2')")
    cur.execute("SELECT COUNT(*) FROM accesscard_test_diff")
    print("rows:", cur.fetchone()[0])
    cur.execute("SELECT COLUMN_NAME, COLUMN_TYPE, CHARACTER_SET_NAME, COLLATION_NAME, IS_NULLABLE, COLUMN_DEFAULT, EXTRA FROM information_schema.columns WHERE TABLE_SCHEMA='archery_dev' AND TABLE_NAME='accesscard_test_diff' ORDER BY ORDINAL_POSITION")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]} charset={r[2] or '-'} coll={r[3] or '-'} nullable={r[4]} default={r[5]} extra={r[6] or '-'}")
c.close()
