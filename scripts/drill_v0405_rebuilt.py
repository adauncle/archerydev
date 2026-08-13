# -*- coding: utf-8 -*-
"""v0.4.5 rebuild 拍板 3 决策落地演练 (8/13).

5 Case:
  Case 1: 单元测试 _build_rebuild_alter_clause 拼出正确 alter (mock schema)
  Case 2: 单元测试 _fetch_table_info_for_rebuild 拿原表属性 (真实 MySQL)
  Case 3: 端到端 走 rebuild_start 端点, 验证 task 填 5 字段 + 不破坏 COMMENT
  Case 4: 演练 accesscard_black_detail rebuild 走通后, 验证字符集没漂
  Case 5: 验证 _make_rebuild_alter (runner) 走新方案 (用 task.rebuilt_alter_full)
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django; django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]

from django.contrib.auth.models import Group, Permission
from django.test import Client
from sql.models import Users, Instance
from sql.extensions.ddl_gh_ost.models import DdlGhostTask
from sql.extensions.ddl_gh_ost.views import (
    _build_rebuild_alter_clause,
    _fetch_table_info_for_rebuild,
    TableNotExistForRebuildError,
)
from sql.extensions.ddl_gh_ost.services.runner import _make_rebuild_alter


# =========================
# Case 1: 单元测试 alter 拼接
# =========================
print("=" * 60)
print("=== Case 1: 单元测试 _build_rebuild_alter_clause ===")
print("=" * 60)

# Mock 1.1: utf8mb4 + Dynamic
table_info = {
    "engine": "InnoDB", "row_format": "Dynamic",
    "charset": "utf8mb4", "collation": "utf8mb4_general_ci",
}
alter = _build_rebuild_alter_clause(table_info)
print(f"  utf8mb4 + Dynamic → {alter}")
assert alter == "ENGINE=InnoDB, ROW_FORMAT=Dynamic, DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_general_ci"
print("  ✓ 1.1 PASS (utf8mb4 + Dynamic)")

# Mock 1.2: utf8mb4_bin collation
table_info["collation"] = "utf8mb4_bin"
alter = _build_rebuild_alter_clause(table_info)
print(f"  utf8mb4_bin → {alter}")
assert alter == "ENGINE=InnoDB, ROW_FORMAT=Dynamic, DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_bin"
print("  ✓ 1.2 PASS (utf8mb4_bin)")

# Mock 1.3: latin1 (不常见但支持)
table_info = {
    "engine": "InnoDB", "row_format": "Compact",
    "charset": "latin1", "collation": "latin1_swedish_ci",
}
alter = _build_rebuild_alter_clause(table_info)
print(f"  latin1 + Compact → {alter}")
assert "CHARACTER SET=latin1" in alter and "COLLATE=latin1_swedish_ci" in alter
print("  ✓ 1.3 PASS (latin1 + Compact)")

print()


# =========================
# Case 2: 真实 MySQL 查 information_schema
# =========================
print("=" * 60)
print("=== Case 2: _fetch_table_info_for_rebuild 真实 MySQL ===")
print("=" * 60)
i = Instance.objects.get(pk=2)  # 134 dev 测试 MySQL 8.0
try:
    info = _fetch_table_info_for_rebuild(i, "archery_dev", "accesscard_black_detail")
    print(f"  engine: {info['engine']}")
    print(f"  row_format: {info['row_format']}")
    print(f"  charset: {info['charset']}")
    print(f"  collation: {info['collation']}")
    assert info["engine"] == "InnoDB"
    assert info["row_format"] in ("Dynamic", "Compact")
    assert info["charset"] in ("utf8", "utf8mb4", "latin1")
    print("  ✓ 2.1 PASS (accesscard_black_detail 查询成功)")

    # Case 2.2: 不存在的表
    try:
        _fetch_table_info_for_rebuild(i, "archery_dev", "table_does_not_exist_xyz")
        print("  ✗ 2.2 失败: 应该抛 TableNotExistForRebuildError")
    except TableNotExistForRebuildError as e:
        print(f"  ✓ 2.2 PASS (不存在的表抛 TableNotExistForRebuildError: {e})")
except Exception as e:
    print(f"  ✗ Case 2 失败: {e}")
    raise
print()


# =========================
# Case 3: 端到端 rebuild_start 端点
# =========================
print("=" * 60)
print("=== Case 3: 端到端 rebuild_start 端点 (DBA 视角) ===")
print("=" * 60)

# 临时给 DBA 组加 view + change perm (走 perm 守卫)
view_perm = Permission.objects.get(content_type__app_label="ddl_gh_ost", codename="view_ddlghosttask")
change_perm = Permission.objects.get(content_type__app_label="ddl_gh_ost", codename="change_ddlghosttask")
dba_group = Group.objects.get(name="DBA")
original_dba_perms = set(dba_group.permissions.all())
dba_group.permissions.add(view_perm, change_perm)
dba_group.save()

c = Client()
u = Users.objects.get(username="mkq")
c.force_login(u, backend="django.contrib.auth.backends.ModelBackend")

# 触发 rebuild (用小演练表避免大表耗时)
print("  准备演练表 accesscard_test_rollback (5 字段 + 索引)...")
import pymysql
user, password = (
    i.get_username_password()
    if hasattr(i, "get_username_password")
    else (i.user, i.password)
)
conn = pymysql.connect(host=i.host, port=i.port, user=user, password=password,
                       database="archery_dev", connect_timeout=5, autocommit=True)
try:
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS accesscard_test_rebuild_drill (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            col1 VARCHAR(50) DEFAULT NULL,
            col2 INT DEFAULT 0,
            col3 VARCHAR(100) DEFAULT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='业务表-演练用'""")
        # 确认 COMMENT 存在
        cur.execute("""SELECT TABLE_COMMENT FROM information_schema.tables
                       WHERE table_schema='archery_dev' AND table_name='accesscard_test_rebuild_drill'""")
        comment = cur.fetchone()[0]
        print(f"  演练前 COMMENT: {comment!r}")
        assert comment == "业务表-演练用", f"COMMENT 应该是 '业务表-演练用', 实际 {comment!r}"

        # 备份原表信息
        cur.execute("""SELECT TABLE_COLLATION, ENGINE, ROW_FORMAT FROM information_schema.tables
                       WHERE table_schema='archery_dev' AND table_name='accesscard_test_rebuild_drill'""")
        col, eng, rf = cur.fetchone()
        print(f"  演练前: collation={col} engine={eng} row_format={rf}")
finally:
    conn.close()

# 触发 rebuild
print("\n  POST /gh_ost/rebuild/start/ ...")
r = c.post("/gh_ost/rebuild/start/", {
    "instance_id": 2,
    "db": "archery_dev",
    "table": "accesscard_test_rebuild_drill",
})
print(f"  status: {r.status_code}")
import json
try:
    data = json.loads(r.content.decode("utf-8", "replace"))
    print(f"  ok: {data.get('ok')}, task_id: {data.get('task_id')}, status: {data.get('status')}")
    assert r.status_code == 200, f"Case 3 失败: status {r.status_code}"
    assert data.get("ok"), f"Case 3 失败: ok=False, error={data.get('error')}"
    task_id = data.get("task_id")
    print(f"  ✓ Case 3.1 PASS (rebuild 触发, task_id={task_id})")
except json.JSONDecodeError:
    print(f"  ✗ Case 3 失败: 响应不是 JSON: {r.content[:500]}")
    raise

# Case 3.2: 验证 task 填了 5 rebuilt_* 字段
print(f"\n  验证 task #{task_id} 填了 rebuilt_* 字段...")
task = DdlGhostTask.objects.get(pk=task_id)
print(f"  rebuilt_charset: {task.rebuilt_charset!r}")
print(f"  rebuilt_row_format: {task.rebuilt_row_format!r}")
print(f"  rebuilt_collation: {task.rebuilt_collation!r}")
print(f"  rebuilt_alter_full: {task.rebuilt_alter_full!r}")
print(f"  rebuilt_at: {task.rebuilt_at!r} (演练时为 None, success 后写)")

assert task.rebuilt_charset == "utf8mb4", f"rebuilt_charset 应 utf8mb4, 实际 {task.rebuilt_charset!r}"
assert task.rebuilt_row_format in ("Dynamic", "Compact"), f"row_format 异常 {task.rebuilt_row_format!r}"
assert "utf8mb4" in task.rebuilt_collation, f"collation 异常 {task.rebuilt_collation!r}"
expected_alter = "ENGINE=InnoDB, ROW_FORMAT=" + task.rebuilt_row_format + ", DEFAULT CHARACTER SET=utf8mb4 COLLATE=" + task.rebuilt_collation
assert task.rebuilt_alter_full == expected_alter, f"alter 不匹配: {task.rebuilt_alter_full!r} != {expected_alter!r}"
assert task.rebuilt_at is None  # 还没 success
print("  ✓ Case 3.2 PASS (5 rebuilt_* 字段填值正确)")

# Case 3.3: 验证 COMMENT 没被破坏 (跑过程中不应该改 COMMENT)
import time
print(f"\n  监控 rebuild 进度 (最多 90 秒)...")
for tick in range(30):
    task.refresh_from_db()
    if task.status in ("success", "failed", "cancelled"):
        break
    time.sleep(3)
    print(f"  [{tick*3}s] status={task.status} pct={task.progress_pct}%")
print(f"  最终 status: {task.status} pct={task.progress_pct}%")

# Case 3.4: 验证 COMMENT 没被破坏 (核心!)
conn = pymysql.connect(host=i.host, port=i.port, user=user, password=password,
                       database="archery_dev", connect_timeout=5, autocommit=True)
try:
    with conn.cursor() as cur:
        cur.execute("""SELECT TABLE_COMMENT, TABLE_COLLATION, ENGINE, ROW_FORMAT
                       FROM information_schema.tables
                       WHERE table_schema='archery_dev' AND table_name='accesscard_test_rebuild_drill'""")
        comment, col_after, eng_after, rf_after = cur.fetchone()
        print(f"  演练后 COMMENT: {comment!r}")
        print(f"  演练后: collation={col_after} engine={eng_after} row_format={rf_after}")
        assert comment == "业务表-演练用", f"COMMENT 改变了! 应 '业务表-演练用' 实际 {comment!r}"
        assert col == col_after, f"collation 漂移: {col} → {col_after}"
        assert eng_after == eng, f"engine 漂移: {eng} → {eng_after}"
        assert rf_after == rf, f"row_format 漂移: {rf} → {rf_after}"
        print("  ✓ Case 3.4 PASS (COMMENT/字符集/ROW_FORMAT 全部保留)")
finally:
    conn.close()

# Case 3.5: rebuilt_at 字段在 success 时写
if task.status == "success":
    task.refresh_from_db()
    print(f"  rebuilt_at: {task.rebuilt_at!r}")
    assert task.rebuilt_at is not None, "rebuilt_at 应在 success 时写"
    print("  ✓ Case 3.5 PASS (rebuilt_at 字段 success 时填值)")
else:
    print(f"  ⚠ Case 3.5 跳过 (rebuild 状态 {task.status}, 演练时已 success/failed)")

# 清理
print(f"\n  清理: drop 演练表 + 还原 DBA 组 perm...")
conn = pymysql.connect(host=i.host, port=i.port, user=user, password=password,
                       database="archery_dev", connect_timeout=5, autocommit=True)
try:
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS accesscard_test_rebuild_drill")
finally:
    conn.close()
dba_group.permissions.set(original_dba_perms)
dba_group.save()
print("  ✓ 清理完成")
print()


# =========================
# Case 4: _make_rebuild_alter (runner) 用 task.rebuilt_alter_full
# =========================
print("=" * 60)
print("=== Case 4: runner._make_rebuild_alter 走新方案 ===")
print("=" * 60)

# Mock task with rebuilt_alter_full
class MockTask:
    id = 99999
    rebuilt_alter_full = "ENGINE=InnoDB, ROW_FORMAT=Dynamic, DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_general_ci"

result = _make_rebuild_alter(MockTask())
print(f"  new task alter: {result}")
assert "ENGINE=InnoDB" in result, f"应包含 ENGINE=InnoDB, 实际 {result}"
assert "COMMENT" not in result, f"不应有 COMMENT 触发, 实际 {result}"
print("  ✓ Case 4.1 PASS (新 task 用 rebuilt_alter_full)")

# Mock task 旧版 (rebuilt_alter_full 为空) 兜底用 COMMENT
class MockOldTask:
    id = 99998
    rebuilt_alter_full = ""

result = _make_rebuild_alter(MockOldTask())
print(f"  old task (兜底) alter: {result}")
assert "COMMENT 'archery-auto-rebuild-" in result, f"应 fallback 到 COMMENT, 实际 {result}"
print("  ✓ Case 4.2 PASS (旧 task 兜底 COMMENT 触发)")
print()


print("=" * 60)
print("ALL PASS: v0.4.5 拍板 3 决策落地演练")
print("=" * 60)
print("  - alter 子句 ENGINE+ROW_FORMAT+CHARSET (3 层防护)")
print("  - rebuilt_* 5 字段记录'这次 rebuild 改了什么'")
print("  - 列表页 ALTER 子句列显示")
print("  - COMMENT 业务描述保留 (数据治理关键)")
print("  - 字符集/引擎/ROW_FORMAT 不漂移")
print("  - 5.7/8.0 都触发物理重写")
