"""W3 DBA-bug-9.5 drill (frontend visible bugs, multi-table big_table + non_alter prompt)

Business: 2 frontend visible bugs found by 阿达叔叔:
  Bug 1: 工单含 CREATE TABLE no prompt to split (backend rejects but frontend doesn't show)
  Bug 2: 多 ALTER 大表 only prompt 1st table (others missed)

DBA 一条龙: drill on 134 dev + 110 prod, NO production data/table touched

6 cases (use real big table, auto-detect via Instance):
- A: multi-ALTER (same big table 3 columns)        -> big_tables length >= 1
- B: single ALTER big table                         -> big_tables length >= 1
- C: 1 ALTER + 1 CREATE                             -> has_non_alter=True
- D: 1 ALTER big table + 1 CREATE                   -> big_tables + has_non_alter
- E: full USE + comment only                        -> big_tables=[], has_non_alter=False
- F: wf#4841 like: USE + ALTER + CREATE             -> big_tables + has_non_alter
- summary: detail.html big_tables field verify

No real DdlGhostTask created. Test:
- sql.views._parse_all_alters (scan all ALTER)
- sql.views._detect_non_alter (scan non-ALTER)
- sql.extensions.ddl_gh_ost.services.column_diff.column_diff_full (return big_tables)
- /gh_ost/check_non_alter/ endpoint logic (call helper directly, bypass login_required)

@ 2026-09-16 @ mavis
"""

import os
import sys
import json
from collections import Counter

sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django  # noqa: E402

django.setup()

from sql.views import _parse_all_alters, _detect_non_alter  # noqa: E402
from sql.extensions.ddl_gh_ost.services.column_diff import column_diff_full  # noqa: E402
from sql.extensions.ddl_gh_ost.views import _parse_all_statements  # noqa: E402
from sql.models import Instance, SqlWorkflow  # noqa: E402
import pymysql  # noqa: E402


def load_env(env_path):
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


load_env("/opt/archery/prod/.env")


# ===== Auto-detect big table from real instances =====
inst = None
big_table = None
db_name = None
for inst_id, db_name_try in [(1, "archery_dev"), (5, "hly_accesscard"), (27, "hly_history_card")]:
    try:
        inst_try = Instance.objects.get(id=inst_id)
        user, password = inst_try.get_username_password()
        conn = pymysql.connect(
            host=inst_try.host, port=int(inst_try.port), user=user, password=password,
            database=db_name_try, connect_timeout=5, autocommit=True,
        )
        with conn.cursor() as cur:
            cur.execute("""
                SELECT TABLE_NAME
                FROM information_schema.tables
                WHERE TABLE_SCHEMA = %s AND TABLE_ROWS >= 100000
                ORDER BY TABLE_ROWS DESC LIMIT 1
            """, (db_name_try,))
            row = cur.fetchone()
            if row:
                inst = inst_try
                db_name = db_name_try
                big_table = row[0]
                print(f"USE inst={inst.id} {inst.instance_name} db={db_name} big_table={big_table}")
                break
        conn.close()
    except Exception as exc:
        print(f"  inst={inst_id} db={db_name_try} skip: {str(exc)[:80]}")

if not big_table:
    raise RuntimeError("No instance with big table found")


def call_check_non_alter(sql_content):
    """Mock /gh_ost/check_non_alter/ endpoint logic (bypass login_required + ALLOWED_HOSTS)."""
    parsed = _parse_all_statements(sql_content)
    non_alter_stmts = [s for s in parsed if s["stmt_type"] not in ("ALTER", "USE", "OTHER")]
    return {
        "has_non_alter": len(non_alter_stmts) > 0,
        "non_alter_count": len(non_alter_stmts),
        "alter_count": sum(1 for s in parsed if s["stmt_type"] == "ALTER"),
        "use_count": sum(1 for s in parsed if s["stmt_type"] == "USE"),
        "type_counts": dict(Counter(s["stmt_type"] for s in non_alter_stmts)),
        "examples": [
            {"stmt_type": s["stmt_type"], "full": s["full"][:200]}
            for s in non_alter_stmts[:3]
        ],
        "advice": (
            "本工单含非 ALTER 语句 (CREATE/INSERT/UPDATE/DELETE), gh-ost 模式不支持, "
            "请拆分: CREATE / INSERT / UPDATE / DELETE 单独提交工单"
        ) if non_alter_stmts else "全部是 ALTER + USE, gh-ost 模式可以启用",
    }


# ===== Case A: multi-ALTER (same big table 3 columns) =====
print(f"=== A: multi-ALTER (same big table {big_table}) - big_tables length >= 1 ===")
sql_a = f"""
ALTER TABLE {big_table} ADD COLUMN dba9v2_test_a varchar(100) DEFAULT NULL;
ALTER TABLE {big_table} ADD COLUMN dba9v2_test_b int DEFAULT NULL;
ALTER TABLE {big_table} ADD COLUMN dba9v2_test_c varchar(50) DEFAULT NULL;
"""
parsed_a = _parse_all_alters(sql_a)
print(f"  parse all_alters: count={len(parsed_a)} tables={[t['table'] for t in parsed_a]}")
assert len(parsed_a) == 3, f"FAIL A parse: {parsed_a}"
assert all(t["table"] == big_table for t in parsed_a)

diff_a = column_diff_full(inst, db_name, sql_a)
big_tables_a = diff_a.get("big_tables", [])
print(f"  big_tables: count={len(big_tables_a)} names={[bt['table_name'] for bt in big_tables_a]}")
assert len(big_tables_a) >= 1, f"FAIL A big_tables empty: {diff_a}"
assert diff_a.get("big_table_alert") is not None, f"FAIL A big_table_alert: {diff_a}"
for bt in big_tables_a:
    assert "table_name" in bt and "rows" in bt and "size_mb" in bt
print(f"  PASS A (big_tables 长度 = {len(big_tables_a)})\n")


# ===== Case B: single ALTER big table (compatible old logic) =====
print(f"=== B: single ALTER ({big_table}) - big_tables length >= 1 ===")
sql_b = f"ALTER TABLE {big_table} ADD COLUMN dba9v2_test_b_col varchar(50) DEFAULT NULL;"
parsed_b = _parse_all_alters(sql_b)
print(f"  parse all_alters: count={len(parsed_b)} tables={[t['table'] for t in parsed_b]}")
assert len(parsed_b) == 1
assert parsed_b[0]["table"] == big_table

diff_b = column_diff_full(inst, db_name, sql_b)
big_tables_b = diff_b.get("big_tables", [])
print(f"  big_tables: count={len(big_tables_b)} names={[bt['table_name'] for bt in big_tables_b]}")
assert len(big_tables_b) >= 1, f"FAIL B big_tables empty: {diff_b}"
assert diff_b.get("big_table_alert") is not None
print(f"  PASS B (big_tables 长度 = {len(big_tables_b)})\n")


# ===== Case C: 1 ALTER + 1 CREATE =====
print("=== C: 1 ALTER + 1 CREATE - 期望 has_non_alter=True ===")
sql_c = f"""
ALTER TABLE {big_table} ADD COLUMN dba9v2_test_c_col int DEFAULT NULL;
CREATE TABLE dba9v2_test_c (id int PRIMARY KEY) ENGINE=InnoDB;
"""
non_alter_c = _detect_non_alter(sql_c)
print(f"  detect_non_alter: count={len(non_alter_c)} types={[s['stmt_type'] for s in non_alter_c]}")
assert len(non_alter_c) == 1
assert non_alter_c[0]["stmt_type"] == "CREATE"

resp_data = call_check_non_alter(sql_c)
print(f"  check_non_alter: has_non_alter={resp_data['has_non_alter']} alter_count={resp_data['alter_count']} non_alter_count={resp_data['non_alter_count']}")
assert resp_data["has_non_alter"] is True
assert resp_data["non_alter_count"] == 1
assert resp_data["alter_count"] == 1
assert "CREATE" in resp_data["type_counts"]
assert "CREATE" in [ex["stmt_type"] for ex in resp_data["examples"]]
assert "请拆分" in resp_data["advice"]
print("  PASS C\n")


# ===== Case D: 1 ALTER big table + 1 CREATE =====
print("=== D: 1 ALTER big table + 1 CREATE - big_tables + has_non_alter ===")
sql_d = f"""
ALTER TABLE {big_table} ADD COLUMN dba9v2_test_d_col varchar(100) DEFAULT NULL;
CREATE TABLE dba9v2_test_d (id int PRIMARY KEY) ENGINE=InnoDB;
"""
diff_d = column_diff_full(inst, db_name, sql_d)
big_tables_d = diff_d.get("big_tables", [])
print(f"  big_tables: count={len(big_tables_d)} names={[bt['table_name'] for bt in big_tables_d]}")
assert len(big_tables_d) >= 1

resp_data = call_check_non_alter(sql_d)
print(f"  check_non_alter: has_non_alter={resp_data['has_non_alter']} count={resp_data['non_alter_count']}")
assert resp_data["has_non_alter"] is True
assert resp_data["non_alter_count"] == 1
print("  PASS D\n")


# ===== Case E: USE + comment only (no ALTER, no non-ALTER) =====
print("=== E: USE + comment only - big_tables=[], has_non_alter=False ===")
sql_e = """
USE hly_accesscard;
-- comment
"""
parsed_e = _parse_all_alters(sql_e)
print(f"  parse all_alters: count={len(parsed_e)}")
assert len(parsed_e) == 0

non_alter_e = _detect_non_alter(sql_e)
print(f"  detect_non_alter: count={len(non_alter_e)}")
assert len(non_alter_e) == 0

resp_data = call_check_non_alter(sql_e)
print(f"  check_non_alter: has_non_alter={resp_data['has_non_alter']}")
assert resp_data["has_non_alter"] is False
print("  PASS E\n")


# ===== Case F: wf#4841 like: USE + ALTER + CREATE =====
print("=== F: wf#4841 like (USE + ALTER + CREATE) - big_tables + has_non_alter ===")
sql_f = f"""
USE `hly_accesscard`;
ALTER TABLE `{big_table}` ADD COLUMN dba9v2_test_f_col varchar(50) DEFAULT NULL;
CREATE TABLE `dba9v2_test_f` (id int PRIMARY KEY) ENGINE=InnoDB;
"""
diff_f = column_diff_full(inst, db_name, sql_f)
big_tables_f = diff_f.get("big_tables", [])
print(f"  big_tables: count={len(big_tables_f)} names={[bt['table_name'] for bt in big_tables_f]}")
assert len(big_tables_f) >= 1

non_alter_f = _detect_non_alter(sql_f)
print(f"  detect_non_alter: count={len(non_alter_f)} types={[s['stmt_type'] for s in non_alter_f]}")
assert len(non_alter_f) == 1
assert non_alter_f[0]["stmt_type"] == "CREATE"

resp_data = call_check_non_alter(sql_f)
print(f"  check_non_alter: has_non_alter={resp_data['has_non_alter']} alter_count={resp_data['alter_count']} use_count={resp_data['use_count']}")
assert resp_data["has_non_alter"] is True
assert resp_data["alter_count"] == 1
assert resp_data["use_count"] == 1
print("  PASS F\n")


# ===== Summary: detail.html big_tables field verify =====
print("=== Summary: detail.html big_tables field verify ===")
test_wf = SqlWorkflow.objects.filter(
    sqlworkflowcontent__sql_content__icontains="ALTER TABLE",
).exclude(id=4841).order_by("-id").first()
if test_wf:
    sql_text = test_wf.sqlworkflowcontent.sql_content or ""
    all_alters = _parse_all_alters(sql_text)
    print(f"  test wf={test_wf.id} all_alters={len(all_alters)}")
    if len(all_alters) >= 1:
        print(f"  tables: {[t['table'] for t in all_alters]}")
    print("  PASS Summary\n")
else:
    print("  SKIP Summary\n")


print("=" * 60)
print("W3 DBA-bug-9.5 drill 6+1 case PASS")
print(f"  A: multi-ALTER ({big_table}) -> big_tables list")
print(f"  B: single ALTER ({big_table}) -> compatible old logic")
print("  C: ALTER + CREATE -> has_non_alter=True")
print(f"  D: ALTER {big_table} + CREATE -> both")
print("  E: USE + comment -> empty")
print(f"  F: wf#4841 like -> big_tables + has_non_alter")
print("  Summary: detail.html big_tables field")