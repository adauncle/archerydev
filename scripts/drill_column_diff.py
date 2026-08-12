# -*- coding: utf-8 -*-
"""v0.3.x 字段 diff 5 Case 端到端演练 @ 134 dev.

5 Case:
  A. 字符集丢失 (用户事故): status VARCHAR(50) 没带 CHARSET
  B. NULL→NOT NULL 无 DEFAULT: operator_id BIGINT NOT NULL
  C. 自增被改: id BIGINT (删 AUTO_INCREMENT)
  D. 类型缩短: name VARCHAR(50) NOT NULL DEFAULT ''
  E. 变长 + 改 COMMENT (无风险): remark VARCHAR(500) COMMENT '...'
"""
import os, sys, json
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django; django.setup()

from django.test import Client
from django.conf import settings
if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]

from sql.models import Users, Instance
from sql.extensions.ddl_gh_ost.services.column_diff import column_diff_full

# 拿 instance id=2 (测试 MySQL 8.0)
instance = Instance.objects.get(pk=2)
user, password = instance.get_username_password()

# 用测试表 accesscard_test_diff (脚本 setup_test_diff_table.py 已建)
TABLE = "accesscard_test_diff"

# 先查测试表的真实列定义
import pymysql
conn = pymysql.connect(host=instance.host, port=instance.port, user=user, password=password,
                       database="archery_dev", autocommit=True)
print(f"=== {TABLE} 实际列定义 ===")
with conn.cursor() as cur:
    cur.execute(f"""SELECT COLUMN_NAME, COLUMN_TYPE, CHARACTER_SET_NAME, COLLATION_NAME,
                          IS_NULLABLE, COLUMN_DEFAULT, EXTRA
                   FROM information_schema.columns
                   WHERE TABLE_SCHEMA='archery_dev' AND TABLE_NAME='{TABLE}'
                   ORDER BY ORDINAL_POSITION""")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]} charset={r[2] or '-'} coll={r[3] or '-'} nullable={r[4]} default={r[5]} extra={r[6] or '-'}")
conn.close()


CASES = [
    ("A. 字符集丢失 (你的事故)", f"ALTER TABLE {TABLE} MODIFY COLUMN status VARCHAR(50)"),
    ("B. NULL→NOT NULL 无 DEFAULT", f"ALTER TABLE {TABLE} MODIFY COLUMN operator_id BIGINT NOT NULL"),
    ("C. 自增被改 (id 是 auto_increment)", f"ALTER TABLE {TABLE} MODIFY COLUMN id BIGINT"),
    ("D. 类型缩短 + NULL→NOT NULL 有 DEFAULT", f"ALTER TABLE {TABLE} MODIFY COLUMN status VARCHAR(50) NOT NULL DEFAULT ''"),
    ("E. 变长 + 改 COMMENT (低风险)", f"ALTER TABLE {TABLE} MODIFY COLUMN name VARCHAR(100) COMMENT '新用户名'"),
]

print("\n" + "=" * 80)
print("5 Case 端到端演练 (Django 直接调 column_diff_full)")
print("=" * 80)

results = []
for label, sql in CASES:
    print(f"\n{'─' * 80}")
    print(f"### {label}")
    print(f"SQL: {sql}")
    print(f"{'─' * 80}")
    result = column_diff_full(instance, "archery_dev", sql)
    results.append((label, result))
    if not result.get("ok"):
        print(f"  ❌ {result.get('error')}")
        continue
    print(f"  表: {result.get('table_name')}")
    print(f"  {result.get('summary')}")
    print(f"  风险计数: 🟥 {result.get('high_risk_count')} / 🟧 {result.get('mid_risk_count')} / 🟩 {result.get('low_risk_count')}")
    for col in result.get("columns", []):
        print(f"  [{col['operation']}] {col['name']}")
        for d in col.get("diffs", []):
            print(f"    {d['risk']:>4} | {d['field']:>10} | {d['old']!r:>30} → {d['new']!r:<30} | {d['reason']}")

print("\n" + "=" * 80)
print("[drill] 全部 5 Case 跑完")
print("=" * 80)
