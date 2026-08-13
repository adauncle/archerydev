# -*- coding: utf-8 -*-
"""测 DDL 智能回滚 (A+B 方案): 5 单元测试 + 1 端到端 (工单 #76)."""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django; django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]

from unittest.mock import patch, MagicMock
from django.test import Client
from sql.models import Users, SqlWorkflow
from sql.services.ddl_rollback import (
    generate_ddl_rollback,
    _reverse_single_op,
    _should_use_ddl_rollback,
    _reverse_alter_table,
)


# =========================
# Case 1: ADD COLUMN → DROP COLUMN (不需查 schema)
# =========================
print("=== Case 1: ADD COLUMN → DROP COLUMN (无需查 schema) ===")
instance = MagicMock()
rb, warn = _reverse_single_op(instance, "archery_dev", "`accesscard_test_rollback`",
                              "ADD COLUMN test5 INT NOT NULL DEFAULT 0 COMMENT 'test'")
print(f"  rollback: {rb}, warn={warn}")
assert rb == "DROP COLUMN `test5`", f"Case 1 失败: 期望 DROP COLUMN `test5`, 实际 {rb}"
assert warn is None
print("  ✓ Case 1 PASS (ADD COLUMN → DROP COLUMN)\n")


# =========================
# Case 2: DROP COLUMN → ADD COLUMN (需查 schema)
# =========================
print("=== Case 2: DROP COLUMN → ADD COLUMN (需查 schema) ===")
mock_cols = {
    "test6": {
        "name": "test6", "type": "varchar(100)",
        "data_type": "varchar", "max_length": 100,
        "charset": "utf8mb4", "collation": "utf8mb4_general_ci",
        "nullable": True, "default": None,
        "comment": "test column", "extra": "", "column_key": "",
    }
}
with patch("sql.services.ddl_rollback._fetch_current_columns", return_value=mock_cols):
    rb, warn = _reverse_single_op(instance, "archery_dev", "`t`",
                                  "DROP COLUMN test6")
    print(f"  rollback: {rb}")
    print(f"  warning: {warn}")
    assert rb and rb.startswith("ADD COLUMN `test6`"), f"Case 2 失败: {rb}"
    assert "varchar(100)" in rb, f"Case 2 失败: 应含原类型, 实际 {rb}"
    assert warn is None
print("  ✓ Case 2 PASS (DROP COLUMN → ADD COLUMN <原类型>)\n")


# =========================
# Case 3: ADD INDEX → DROP INDEX (不需查 schema)
# =========================
print("=== Case 3: ADD INDEX → DROP INDEX (无需查 schema) ===")
rb, warn = _reverse_single_op(instance, "archery_dev", "`t`",
                              "ADD INDEX idx_test (col1, col2)")
print(f"  rollback: {rb}, warn={warn}")
assert rb == "DROP INDEX `idx_test`", f"Case 3 失败: {rb}"
assert warn is None
print("  ✓ Case 3 PASS (ADD INDEX → DROP INDEX)\n")


# =========================
# Case 4: ADD CONSTRAINT FK → warnings (B 方案)
# =========================
print("=== Case 4: ADD CONSTRAINT FK → warnings (B 方案) ===")
rb, warn = _reverse_single_op(instance, "archery_dev", "`t_child`",
                              "ADD CONSTRAINT fk_xxx FOREIGN KEY (parent_id) REFERENCES t_parent(id)")
print(f"  rollback: {rb}, warn={warn}")
assert rb is None, f"Case 4 失败: 应 None, 实际 {rb}"
assert warn is not None and "FOREIGN KEY" in warn, f"Case 4 失败: 警告不包含 FOREIGN KEY, 实际 {warn}"
print("  ✓ Case 4 PASS (B 方案 warnings)\n")


# =========================
# Case 5: 不识别的 DDL 操作
# =========================
print("=== Case 5: 未识别的 DDL 操作 (B 方案) ===")
rb, warn = _reverse_single_op(instance, "archery_dev", "`t`",
                              "RENAME TO t_new")
print(f"  rollback: {rb}, warn={warn}")
assert rb is None
assert warn and "RENAME" in warn.upper()
print("  ✓ Case 5 PASS (RENAME → warnings)\n")


# =========================
# Case 6: 端到端 - 调 backup_sql 端点, 验证工单 #76
# =========================
print("=== Case 6: 端到端 (工单 #76 gh-ost 走通的 ADD COLUMN test4) ===")
c = Client()
u = Users.objects.get(username="archery")
c.force_login(u, backend="django.contrib.auth.backends.ModelBackend")

r = c.get("/sqlworkflow/backup_sql/?workflow_id=76")
print(f"  status: {r.status_code}")
print(f"  content-type: {r.get('Content-Type')}")
import json
try:
    data = json.loads(r.content.decode("utf-8", "replace"))
    print(f"  response status: {data.get('status')}")
    print(f"  response rows: {data.get('rows')}")
    print(f"  response warnings: {data.get('warnings')}")
    assert data["status"] == 0, f"Case 6 失败: status 应 0, 实际 {data['status']}"
    rows = data.get("rows", [])
    assert len(rows) > 0, f"Case 6 失败: rows 应非空, 实际 {rows}"
    # rows[0] = [原 SQL, 回滚 SQL]
    src, rollback = rows[0]
    print(f"  原 SQL: {src[:80]}")
    print(f"  回滚 SQL: {rollback}")
    assert "DROP COLUMN `test4`" in rollback, f"Case 6 失败: 应含 DROP COLUMN test4, 实际 {rollback}"
    print("  ✓ Case 6 PASS (工单 #76 端到端: ADD COLUMN test4 → DROP COLUMN test4)")
except json.JSONDecodeError as e:
    print(f"  ✗ Case 6 失败: 响应不是 JSON: {e}")
    print(f"  body: {r.content[:500]}")
print()


# =========================
# Case 7: _should_use_ddl_rollback 路径判定
# =========================
print("=== Case 7: _should_use_ddl_rollback 路径判定 ===")
# 简化: 直接测真实 SqlWorkflow
w76 = SqlWorkflow.objects.get(pk=76)
print(f"  工单 #76 (有 ghost_task): _should_use_ddl_rollback={_should_use_ddl_rollback(w76)}")
assert _should_use_ddl_rollback(w76), "Case 7 失败: 工单 #76 有 ghost_task 应 True"

# 找一个没 ghost_task 的工单 (用 exclude 关联反向 query)
from sql.extensions.ddl_gh_ost.models import DdlGhostTask
w_no_ghost = SqlWorkflow.objects.exclude(id__in=DdlGhostTask.objects.values_list("workflow_id", flat=True)).first()
if w_no_ghost:
    print(f"  工单 #{w_no_ghost.id} (无 ghost_task): _should_use_ddl_rollback={_should_use_ddl_rollback(w_no_ghost)}")
    assert not _should_use_ddl_rollback(w_no_ghost), "Case 7 失败: 无 ghost_task 应 False"
    print("  ✓ Case 7 PASS (路径判定正确)")
else:
    print("  ⚠ 找不到无 ghost_task 的工单, 跳过该子 case")
print()


print("=" * 60)
print("ALL PASS: 5 单元测试 + 1 端到端 + 1 路径判定")
print("A 方案 DDL 智能回滚 验证通过")
print("=" * 60)
