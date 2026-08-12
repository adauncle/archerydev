# -*- coding: utf-8 -*-
"""Django test client 测 /gh_ost/column_diff/ 端点"""
import os, sys
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django; django.setup()
from django.conf import settings
settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]
from django.test import Client
from sql.models import Users

u = Users.objects.get(username="archery")
c = Client()
c.force_login(u, backend="django.contrib.auth.backends.ModelBackend")

import json

# Case A 字符集丢失
sql_a = "ALTER TABLE accesscard_test_diff MODIFY COLUMN status VARCHAR(50)"
r = c.post("/gh_ost/column_diff/", {"instance_id": 2, "db_name": "archery_dev", "sql_content": sql_a})
j = r.json()
print("=== Case A: 字符集丢失 (你的事故) ===")
print(f"  status: {r.status_code}")
print(f"  ok: {j.get('ok')}")
print(f"  summary: {j.get('summary')}")
print(f"  high/mid/low: {j.get('high_risk_count')}/{j.get('mid_risk_count')}/{j.get('low_risk_count')}")
for col in j.get("columns", []):
    print(f"  [{col['operation']}] {col['name']}: {len(col.get('diffs', []))} diffs")
    for d in col.get("diffs", []):
        print(f"    {d['risk']:>4} | {d['field']:>10} | {d['reason']}")

# Case B NULL→NOT NULL 无 DEFAULT
print()
print("=== Case B: NULL→NOT NULL 无 DEFAULT ===")
sql_b = "ALTER TABLE accesscard_test_diff MODIFY COLUMN operator_id BIGINT NOT NULL"
r = c.post("/gh_ost/column_diff/", {"instance_id": 2, "db_name": "archery_dev", "sql_content": sql_b})
j = r.json()
print(f"  ok: {j.get('ok')}, high: {j.get('high_risk_count')}, mid: {j.get('mid_risk_count')}, low: {j.get('low_risk_count')}")
for col in j.get("columns", []):
    for d in col.get("diffs", []):
        print(f"    {d['risk']:>4} | {d['field']:>10} | {d['reason']}")

# Case C 自增被改
print()
print("=== Case C: 自增被改 ===")
sql_c = "ALTER TABLE accesscard_test_diff MODIFY COLUMN id BIGINT"
r = c.post("/gh_ost/column_diff/", {"instance_id": 2, "db_name": "archery_dev", "sql_content": sql_c})
j = r.json()
print(f"  ok: {j.get('ok')}, high: {j.get('high_risk_count')}, mid: {j.get('mid_risk_count')}, low: {j.get('low_risk_count')}")
for col in j.get("columns", []):
    for d in col.get("diffs", []):
        print(f"    {d['risk']:>4} | {d['field']:>10} | {d['reason']}")

# 错误处理
print()
print("=== 错误: 不是 ALTER ===")
r = c.post("/gh_ost/column_diff/", {"instance_id": 2, "db_name": "archery_dev", "sql_content": "SELECT 1"})
j = r.json()
print(f"  ok: {j.get('ok')}, error: {j.get('error')}, hint: {j.get('hint')}")
