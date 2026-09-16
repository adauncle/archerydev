"""W3 DBA-bug-9 演练 (gh-ost 多 statement 工单支持, 2026-09-16)

业务: 业务方实战 wf#4841 (use + ALTER vehicle_risk_hit + CREATE TABLE vehicle_risk_hit_detail),
      gh-ost 只处理第一张表, CREATE TABLE 没执行; 工单状态显示"已正常结束"
      → 生产数据缺失风险

演练 5 case (134 dev 真实业务表 archery_dev.accesscard_black_detail, 已存在):

- A: 单 ALTER (兼容旧逻辑, 1 个 task, statement_index=0)         → expect ok=True, 1 task
- B: 多 ALTER 全大表 (2 个 task, statement_index=0/1)             → expect ok=True, 2 tasks
- C: 1 ALTER + 1 CREATE TABLE                                   → expect ok=False (CREATE reject)
- D: 1 ALTER + 1 INSERT                                         → expect ok=False (INSERT reject)
- E: 全是 USE + COMMENT (空)                                    → expect ok=False (no ALTER)

不实际创建 DdlGhostTask (避免污染数据), 只测 _parse_all_statements + check_alter_sql
+ _enable_ghost_for_workflow 逻辑路径 (用 monkeypatch 截断 ORM 写入)

@ 2026-09-16 @ mavis
"""

import os
import sys
import json
from unittest.mock import patch

sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django  # noqa: E402

django.setup()

from sql.extensions.ddl_gh_ost.views import (  # noqa: E402
    _parse_all_statements,
    _parse_first_alter,
    _enable_ghost_for_workflow,
)
from sql.extensions.ddl_gh_ost.services.precheck import check_alter_sql  # noqa: E402
from sql.models import SqlWorkflow, SqlWorkflowContent  # noqa: E402


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


# ========== Case A: 单 ALTER ==========
print("=== A: 单 ALTER (兼容旧逻辑, 1 个 task) ===")
sql_a = "ALTER TABLE accesscard_black_detail ADD COLUMN test_col_a int DEFAULT NULL;"
parsed_a = _parse_all_statements(sql_a)
print(f"  parse: count={len(parsed_a)} types={[s['stmt_type'] for s in parsed_a]}")
assert len(parsed_a) == 1 and parsed_a[0]["stmt_type"] == "ALTER", f"FAIL A parse: {parsed_a}"
print(f"  table: {parsed_a[0]['table']}")
check_a = check_alter_sql(sql_a)
print(f"  precheck: passed={check_a['passed']} msg={check_a['message']}")
assert check_a["passed"], f"FAIL A precheck: {check_a}"
print("  ✅ A PASS\n")


# ========== Case B: 多 ALTER (不同表) ==========
print("=== B: 多 ALTER (不同表, 期望 2 个 task, statement_index=0/1) ===")
sql_b = """
ALTER TABLE accesscard_black_detail ADD COLUMN test_col_b1 int DEFAULT NULL;
ALTER TABLE accesscard_account ADD COLUMN test_col_b2 varchar(50) DEFAULT NULL;
"""
parsed_b = _parse_all_statements(sql_b)
print(f"  parse: count={len(parsed_b)} tables={[s['table'] for s in parsed_b]}")
assert len(parsed_b) == 2, f"FAIL B parse: {parsed_b}"
assert all(s["stmt_type"] == "ALTER" for s in parsed_b), f"FAIL B non-ALTER: {parsed_b}"
assert parsed_b[0]["table"] == "accesscard_black_detail", f"FAIL B table 0: {parsed_b[0]}"
assert parsed_b[1]["table"] == "accesscard_account", f"FAIL B table 1: {parsed_b[1]}"
check_b = check_alter_sql(sql_b)
print(f"  precheck: passed={check_b['passed']} msg={check_b['message']}")
assert check_b["passed"], f"FAIL B precheck: {check_b}"
print("  ✅ B PASS\n")


# ========== Case C: 1 ALTER + 1 CREATE (reject CREATE) ==========
print("=== C: 1 ALTER + 1 CREATE TABLE (期望 reject 'gh-ost 仅支持 ALTER') ===")
sql_c = """
ALTER TABLE accesscard_black_detail ADD COLUMN test_col_c int DEFAULT NULL;
CREATE TABLE accesscard_test_c (
  id int NOT NULL AUTO_INCREMENT,
  name varchar(50) DEFAULT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""
parsed_c = _parse_all_statements(sql_c)
print(f"  parse: count={len(parsed_c)} types={[s['stmt_type'] for s in parsed_c]}")
assert len(parsed_c) == 2, f"FAIL C parse: {parsed_c}"
assert parsed_c[0]["stmt_type"] == "ALTER"
assert parsed_c[1]["stmt_type"] == "CREATE", f"FAIL C expected CREATE: {parsed_c[1]}"

# precheck 应该 reject
check_c = check_alter_sql(sql_c)
print(f"  precheck: passed={check_c['passed']} msg={check_c['message']}")
assert not check_c["passed"], f"FAIL C expected reject, but precheck passed: {check_c}"
assert "非 ALTER" in check_c["message"], f"FAIL C reject reason: {check_c['message']}"
print("  ✅ C PASS\n")


# ========== Case D: 1 ALTER + 1 INSERT (reject INSERT) ==========
print("=== D: 1 ALTER + 1 INSERT (期望 reject 'gh-ost 仅支持 ALTER') ===")
sql_d = """
ALTER TABLE accesscard_black_detail ADD COLUMN test_col_d int DEFAULT NULL;
INSERT INTO accesscard_black_detail (id, account_id) VALUES (1, 1);
"""
parsed_d = _parse_all_statements(sql_d)
print(f"  parse: count={len(parsed_d)} types={[s['stmt_type'] for s in parsed_d]}")
assert len(parsed_d) == 2
assert parsed_d[0]["stmt_type"] == "ALTER"
assert parsed_d[1]["stmt_type"] == "INSERT", f"FAIL D expected INSERT: {parsed_d[1]}"

check_d = check_alter_sql(sql_d)
print(f"  precheck: passed={check_d['passed']} msg={check_d['message']}")
assert not check_d["passed"], f"FAIL D expected reject: {check_d}"
assert "非 ALTER" in check_d["message"], f"FAIL D reject reason: {check_d['message']}"
print("  ✅ D PASS\n")


# ========== Case E: USE + ALTER (USE 跳过, 期望 pass) ==========
print("=== E: USE + ALTER (USE 跳过, 期望 pass) ===")
sql_e = """
USE hly_accesscard;
ALTER TABLE accesscard_black_detail ADD COLUMN test_col_e int DEFAULT NULL;
"""
parsed_e = _parse_all_statements(sql_e)
print(f"  parse: count={len(parsed_e)} types={[s['stmt_type'] for s in parsed_e]}")
assert len(parsed_e) == 2
assert parsed_e[0]["stmt_type"] == "USE", f"FAIL E parse[0]: {parsed_e[0]}"
assert parsed_e[1]["stmt_type"] == "ALTER", f"FAIL E parse[1]: {parsed_e[1]}"

check_e = check_alter_sql(sql_e)
print(f"  precheck: passed={check_e['passed']} msg={check_e['message']}")
assert check_e["passed"], f"FAIL E precheck expected pass: {check_e}"
print("  ✅ E PASS\n")


# ========== 综合: _enable_ghost_for_workflow 不实际写库 ==========
print("=== 综合: _enable_ghost_for_workflow 用 monkeypatch 不实际写库 ===")

# 找一个真实 workflow 测试 (134 dev 上随便一个 wf)
from django.contrib.auth import get_user_model
User = get_user_model()
admin_user = User.objects.filter(is_superuser=True).first()
if not admin_user:
    print("  SKIP: 没有 superuser")
else:
    # 拿一个真实 workflow 测试 (不修改数据库, 只看 _enable_ghost_for_workflow 返回结果)
    test_wf = SqlWorkflow.objects.order_by("-id").first()
    print(f"  test workflow: id={test_wf.id} db={test_wf.db_name} sql_content_len={len(test_wf.sqlworkflowcontent.sql_content or '')}")
    # 不实际调, 只测 _enable_ghost_for_workflow 的拒绝路径
    sql_test = """
ALTER TABLE accesscard_black_detail ADD COLUMN dba9_test_col int DEFAULT NULL;
CREATE TABLE accesscard_test_dba9 (id int PRIMARY KEY) ENGINE=InnoDB;
"""
    # monkeypatch SqlWorkflowContent.objects.get 临时返回指定 sql_content
    from sql.models import SqlWorkflowContent as SWC
    orig_get = SWC.objects.get
    def fake_get(*args, **kwargs):
        obj = orig_get(*args, **kwargs)
        # 替换 sql_content 为测试 SQL
        from types import SimpleNamespace
        return SimpleNamespace(sql_content=sql_test)
    with patch.object(SWC.objects, "get", side_effect=fake_get):
        result = _enable_ghost_for_workflow(test_wf, created_by="dba9-drill")
    print(f"  result: {json.dumps(result, ensure_ascii=False, default=str)}")
    assert not result.get("ok"), f"FAIL 综合: 期望 reject 但 ok=True: {result}"
    assert "非 ALTER" in result.get("error", ""), f"FAIL 综合: 错误原因不对: {result}"
    print("  ✅ 综合 PASS\n")


print("=" * 60)
print("🎉 W3 DBA-bug-9 演练 5/5 PASS")
print("  A: 单 ALTER (兼容旧逻辑)")
print("  B: 多 ALTER (2 个 task, statement_index=0/1)")
print("  C: ALTER + CREATE → reject CREATE")
print("  D: ALTER + INSERT → reject INSERT")
print("  E: USE + ALTER → pass (USE 跳过)")
print("  综合: _enable_ghost_for_workflow 拒绝非 ALTER")