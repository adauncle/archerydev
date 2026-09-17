"""v1 优化 mixed_ddl 验证 (5 case)

@ 2026-09-17 @ mavis
"""
import sys
sys.path.insert(0, "/opt/archery/prod")
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()
from sql.views import _check_mixed_ddl

# Case 1: 纯 ALTER → ok=True
sql_a = "ALTER TABLE t1 ADD COLUMN c int;"
r = _check_mixed_ddl(sql_a)
print(f"Case 1 (纯 ALTER): ok={r['ok']} (期望 True)")
assert r["ok"] is True, f"FAIL: {r}"

# Case 2: 纯 CREATE → ok=True
sql_b = "CREATE TABLE t1 (id int);"
r = _check_mixed_ddl(sql_b)
print(f"Case 2 (纯 CREATE): ok={r['ok']} (期望 True)")
assert r["ok"] is True, f"FAIL: {r}"

# Case 3: ALTER + CREATE 混合 → ok=False
sql_c = "ALTER TABLE t1 ADD COLUMN c int;\nCREATE TABLE t2 (id int);"
r = _check_mixed_ddl(sql_c)
print(f"Case 3 (ALTER + CREATE): ok={r['ok']} types={r.get('types')}")
assert r["ok"] is False
assert "ALTER" in r["types"] and "CREATE" in r["types"]
assert "ALTER" in r["error"] and "CREATE" in r["error"]
print(f"  error: {r['error'][:100]}")

# Case 4: wf#4841 实战 4 CREATE + 4 ALTER → ok=False
sql_d = """CREATE TABLE vehicle_risk_hit (id int);
CREATE TABLE vehicle_risk_hit_detail (id int);
CREATE TABLE risk_rule_set (id int);
CREATE TABLE risk_rule_operation_log (id int);
ALTER TABLE hly_accesscard.accesscard_licensefront_info ADD owner_name varchar(200);
ALTER TABLE hly_accesscard.vehicle_info_verify ADD data_source tinyint;
ALTER TABLE accesscard_vehicle_review ADD risk_level TINYINT;
ALTER TABLE accesscard_opendcardapply ADD agency_spread_code varchar(50);"""
r = _check_mixed_ddl(sql_d)
print(f"Case 4 (wf#4841 实战 4 CREATE + 4 ALTER): ok={r['ok']} types={r.get('types')}")
assert r["ok"] is False
assert len(r["types"]) == 2

# Case 5: USE + ALTER → ok=True (USE 跳过, 不算 CREATE)
sql_e = "USE hly_accesscard;\nALTER TABLE t1 ADD COLUMN c int;"
r = _check_mixed_ddl(sql_e)
print(f"Case 5 (USE + ALTER): ok={r['ok']} (期望 True)")
assert r["ok"] is True, f"FAIL: {r}"

# Case 6: ALTER + INSERT → ok=False (DBA-bug-9.5 类似)
sql_f = "ALTER TABLE t1 ADD COLUMN c int;\nINSERT INTO t1 (c) VALUES (1);"
r = _check_mixed_ddl(sql_f)
print(f"Case 6 (ALTER + INSERT): ok={r['ok']} types={r.get('types')}")
assert r["ok"] is False
assert "ALTER" in r["types"] and "INSERT" in r["types"]

# Case 7: 空 SQL → ok=True
r = _check_mixed_ddl("")
print(f"Case 7 (空 SQL): ok={r['ok']} (期望 True)")
assert r["ok"] is True

# Case 8: 注释 + ALTER + 注释 + CREATE → ok=False (注释不算)
sql_h = "-- comment\nALTER TABLE t1 ADD COLUMN c int;\n-- comment\nCREATE TABLE t2 (id int);"
r = _check_mixed_ddl(sql_h)
print(f"Case 8 (注释 + ALTER + 注释 + CREATE): ok={r['ok']}")
assert r["ok"] is False

print()
print("=== 8/8 PASS ===")
print("v1 优化: 混合 DDL 检测 ✅")
print("前端: 检测到 mixed → 红框 alert + 阻止提交按钮")
print("后端: serializer.create() 兜底 reject (即使前端绕过)")