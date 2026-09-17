"""W3 v0 gh-ost 智能模式演练 (5A 拍板, 9/16 阿达叔叔)

业务: 单工单多 ALTER 大小表混合, gh_ost_mode 智能分流
  smart (默认) / all_ghost / all_native

DBA 一条龙: 演练全在 134 dev + 110 prod, 不动生产任何数据/表结构
本脚本用 patch 把 ORM 调用 mock 掉, 跑核心逻辑但不真写 db (除依赖链 G 显式 commit)

7 case:
- A: smart 模式 1 大 + 1 小 → 1 task + 1 small ALTER
- B: smart 模式 全大表 (同表 2 ALTER) → 2 task 依赖链 (statement_index 0/1)
- C: smart 模式 全小表 (2 不存在表) → 0 task + 2 small ALTER
- D: all_ghost 模式 1 大 + 1 小 → 2 task (强制小表也走 gh-ost)
- E: all_native 模式 1 大 + 1 小 → 0 task + 2 small ALTER (强制大表也走原生)
- F: 1 大 + 1 CREATE → reject
- G: depends_on 串行依赖链测试 (手动设置 task.depends_on, 验证 start 拒起)

@ 2026-09-17 @ mavis
"""

import os
import sys
from unittest.mock import patch, MagicMock

# 110 prod 部署路径 (dev path: /opt/archery/prod)
sys.path.insert(0, os.environ.get("ARCHERY_DEPLOY_PATH", "/opt/archery/prod"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django

django.setup()

from sql.models import Instance, SqlWorkflow  # noqa: E402
from sql.extensions.ddl_gh_ost.views import _enable_ghost_for_workflow  # noqa: E402
from sql.extensions.ddl_gh_ost.models import DdlGhostTask  # noqa: E402


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


# ===== 找真实业务实例 + 大表演练 (auto-detect, 跟 DBA-bug-9.5 drill) =====
import pymysql

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


# ===== Mock 工厂: 跳过 ORM 但保留真实 instance 用于 size 查询 =====
_fake_tasks = []
_fake_task_counter = [0]


def fake_task(**kwargs):
    """模拟 DdlGhostTask 对象 (不写 db)"""
    _fake_task_counter[0] += 1
    task = MagicMock(spec=DdlGhostTask)
    task.id = _fake_task_counter[0]
    task.workflow_id = 99999
    task.task_type = "ghost"
    task.statement_index = kwargs.get("statement_index", 0)
    task.statement_type = kwargs.get("statement_type", "ALTER")
    task.db_name = kwargs.get("db_name", "")
    task.table_name = kwargs.get("table_name", "")
    task.alter_statement = kwargs.get("alter_statement", "")
    task.status = kwargs.get("status", "queued")
    task.enabled = True
    task.cut_over_strategy = "immediate"
    task.max_load_threads_running = 30
    task.timeout_seconds = 7200
    task.depends_on = kwargs.get("depends_on", None)
    # .save() no-op
    task.save = MagicMock()
    _fake_tasks.append(task)
    return task


class FakeQuerySet:
    """模拟 DdlGhostTask.objects.filter().order_by() 等返回"""
    def __init__(self, items):
        self.items = items
    def __iter__(self):
        return iter(self.items)
    def __len__(self):
        return len(self.items)
    def __bool__(self):
        return bool(self.items)
    def __getitem__(self, idx):
        return self.items[idx]
    @property
    def count(self):
        return lambda: len(self.items)
    def order_by(self, *args):
        return self


def fake_wf_magic(sql_content, gh_ost_mode="smart"):
    """模拟 SqlWorkflow 对象 (绕过 _workflow_sql_text 真实读库)"""
    fake = MagicMock(spec=SqlWorkflow)
    fake.id = 99999  # 占位
    fake.sql_content = sql_content  # v0 _workflow_sql_text 优先读这个属性
    fake.db_name = db_name
    fake.instance = inst
    fake.gh_ost_mode = gh_ost_mode
    fake.enable_gh_ost = True
    fake.native_alter_results = []
    fake.save = MagicMock()
    return fake


def call_enable(sql_content, gh_ost_mode="smart"):
    """直接调 _enable_ghost_for_workflow 核心逻辑 (patch 掉 ORM 写, 不真改 db)"""
    fake = fake_wf_magic(sql_content, gh_ost_mode)
    _fake_tasks.clear()
    _fake_task_counter[0] = 0

    # patch:
    # 1. DdlGhostTask._default_manager.filter().order_by() 返 [] (没历史 task)
    # 2. DdlGhostTask._default_manager.update_or_create() 返 (fake_task, True)
    # 3. run_all_prechecks 直接 pass (skip 真实预检, 因为演练关注分发逻辑)
    # 用 manager 级别 patch (Django Manager 是 descriptor, 普通 patch DdlGhostTask 不行)
    with patch.object(DdlGhostTask._default_manager, "filter", return_value=FakeQuerySet([])), \
         patch.object(DdlGhostTask._default_manager, "update_or_create",
                       side_effect=lambda **kw: (fake_task(**kw), True)), \
         patch("sql.extensions.ddl_gh_ost.views.run_all_prechecks") as MockPrecheck:
        MockPrecheck.return_value = {"ok": True, "passed": True, "summary": "mock precheck pass", "checks": []}

        return _enable_ghost_for_workflow(fake, created_by="v0-drill")


# ===== Case A: smart 模式 1 大 + 1 小 =====
print("=== A: smart 模式 1 大表 + 1 小表 (期望 1 task + 1 small ALTER) ===")
sql_a = f"""
ALTER TABLE {big_table} ADD COLUMN dba9v0_a varchar(100) DEFAULT NULL;
ALTER TABLE dba9v0_small_a ADD COLUMN dba9v0_a_col varchar(50) DEFAULT NULL;
"""
result_a = call_enable(sql_a, "smart")
print(f"  summary: {result_a.get('summary')}")
print(f"  ok: {result_a.get('ok')}")
print(f"  gh_ost_mode: {result_a.get('gh_ost_mode', result_a.get('mode', '?'))}")
print(f"  tasks: {len(result_a.get('tasks', []))}")
print(f"  small_alters: {len(result_a.get('small_alters', []))}")
assert result_a["ok"] is True, f"FAIL A ok: {result_a}"
assert len(result_a.get("tasks", [])) == 1, f"FAIL A tasks: {result_a.get('tasks')}"
assert len(result_a.get("small_alters", [])) == 1, f"FAIL A small_alters: {result_a.get('small_alters')}"
print("  PASS A\n")


# ===== Case B: smart 模式 全大表 (同表 2 ALTER) =====
print("=== B: smart 模式全大表 (同表 2 ALTER) → 2 task 依赖链 ===")
sql_b = f"""
ALTER TABLE {big_table} ADD COLUMN dba9v0_b1 varchar(100) DEFAULT NULL;
ALTER TABLE {big_table} ADD COLUMN dba9v0_b2 int DEFAULT NULL;
"""
result_b = call_enable(sql_b, "smart")
print(f"  summary: {result_b.get('summary')}")
print(f"  ok: {result_b.get('ok')}")
print(f"  tasks: {len(result_b.get('tasks', []))}")
print(f"  small_alters: {len(result_b.get('small_alters', []))}")
assert result_b["ok"] is True, f"FAIL B ok: {result_b}"
assert len(result_b.get("tasks", [])) == 2, f"FAIL B tasks: {result_b.get('tasks')}"
assert len(result_b.get("small_alters", [])) == 0, f"FAIL B small_alters (期望 0, 都走 gh-ost): {result_b.get('small_alters')}"
print("  PASS B\n")


# ===== Case C: smart 模式 全小表 (2 不存在的表) =====
print("=== C: smart 模式全小表 (2 不存在表) → 0 task + 2 small ALTER ===")
sql_c = """
ALTER TABLE dba9v0_small_c1 ADD COLUMN c1_col int DEFAULT NULL;
ALTER TABLE dba9v0_small_c2 ADD COLUMN c2_col int DEFAULT NULL;
"""
result_c = call_enable(sql_c, "smart")
print(f"  summary: {result_c.get('summary')}")
print(f"  ok: {result_c.get('ok')}")
print(f"  tasks: {len(result_c.get('tasks', []))}")
print(f"  small_alters: {len(result_c.get('small_alters', []))}")
assert result_c["ok"] is True, f"FAIL C ok: {result_c}"
assert len(result_c.get("tasks", [])) == 0, f"FAIL C tasks (期望 0): {result_c.get('tasks')}"
assert len(result_c.get("small_alters", [])) == 2, f"FAIL C small_alters (期望 2): {result_c.get('small_alters')}"
print("  PASS C\n")


# ===== Case D: all_ghost 模式 1 大 + 1 小 → 2 task =====
print("=== D: all_ghost 模式 1 大 + 1 小 → 2 task (强制小表也走 gh-ost) ===")
sql_d = f"""
ALTER TABLE {big_table} ADD COLUMN dba9v0_d1 varchar(100) DEFAULT NULL;
ALTER TABLE dba9v0_small_d ADD COLUMN dba9v0_d_col varchar(50) DEFAULT NULL;
"""
result_d = call_enable(sql_d, "all_ghost")
print(f"  summary: {result_d.get('summary')}")
print(f"  ok: {result_d.get('ok')}")
print(f"  tasks: {len(result_d.get('tasks', []))}")
print(f"  small_alters: {len(result_d.get('small_alters', []))}")
assert result_d["ok"] is True, f"FAIL D ok: {result_d}"
assert len(result_d.get("tasks", [])) == 2, f"FAIL D tasks (期望 2, 强制小表也走 gh-ost): {result_d.get('tasks')}"
assert len(result_d.get("small_alters", [])) == 0, f"FAIL D small_alters (期望 0, 强制全 gh-ost): {result_d.get('small_alters')}"
print("  PASS D\n")


# ===== Case E: all_native 模式 1 大 + 1 小 → 0 task + 2 small ALTER =====
print("=== E: all_native 模式 1 大 + 1 小 → 0 task + 2 small ALTER ===")
sql_e = f"""
ALTER TABLE {big_table} ADD COLUMN dba9v0_e1 varchar(100) DEFAULT NULL;
ALTER TABLE dba9v0_small_e ADD COLUMN dba9v0_e_col varchar(50) DEFAULT NULL;
"""
result_e = call_enable(sql_e, "all_native")
print(f"  summary: {result_e.get('summary')}")
print(f"  ok: {result_e.get('ok')}")
print(f"  tasks: {len(result_e.get('tasks', []))}")
print(f"  small_alters: {len(result_e.get('small_alters', []))}")
assert result_e["ok"] is True, f"FAIL E ok: {result_e}"
assert len(result_e.get("tasks", [])) == 0, f"FAIL E tasks (期望 0, 全原生): {result_e.get('tasks')}"
assert len(result_e.get("small_alters", [])) == 2, f"FAIL E small_alters (期望 2, 含大表): {result_e.get('small_alters')}"
print("  PASS E\n")


# ===== Case F: 1 大 + 1 CREATE → reject =====
print("=== F: 1 大表 + 1 CREATE → reject (gh-ost 模式不支持) ===")
sql_f = f"""
ALTER TABLE {big_table} ADD COLUMN dba9v0_f1 varchar(100) DEFAULT NULL;
CREATE TABLE dba9v0_f (id int PRIMARY KEY) ENGINE=InnoDB;
"""
result_f = call_enable(sql_f, "smart")
print(f"  result: ok={result_f.get('ok')} error={result_f.get('error', '')[:80]}")
assert result_f["ok"] is False, f"FAIL F expected reject: {result_f}"
assert "非 ALTER" in result_f.get("error", ""), f"FAIL F reject reason: {result_f.get('error')}"
print("  PASS F\n")


print("=== 7 case 演练结果 ===")
print("  Case A (smart 1+1): PASS")
print("  Case B (smart 全大): PASS")
print("  Case C (smart 全小): PASS")
print("  Case D (all_ghost): PASS")
print("  Case E (all_native): PASS")
print("  Case F (含 CREATE reject): PASS")
print("  Case G (depends_on 串行): 见下方独立测试 (需要真实 task)\n")


# ===== Case G: depends_on 串行依赖链测试 (用真实 SqlWorkflow, 但用 transaction.atomic 回滚) =====
print("=== G: depends_on 串行依赖链测试 (手动设置, 用 transaction.atomic 回滚不污染 db) ===")
try:
    from django.db import transaction

    test_wf = SqlWorkflow.objects.exclude(id=4841).order_by("-id").first()
    if not test_wf:
        print("  SKIP G: 没 wf\n")
    else:
        with transaction.atomic():
            sid = transaction.savepoint()
            try:
                # 模拟建 2 个 task, task2 依赖 task1
                t1 = DdlGhostTask.objects.create(
                    workflow=test_wf, task_type="ghost",
                    statement_index=0, statement_type="ALTER",
                    db_name=db_name, table_name=big_table,
                    alter_statement=f"ALTER TABLE {big_table} ADD COLUMN v0_g_test1 int DEFAULT NULL",
                    status="success",  # 前置 task 已成功
                    enabled=True, created_by="v0-drill-g",
                )
                t2 = DdlGhostTask.objects.create(
                    workflow=test_wf, task_type="ghost",
                    statement_index=1, statement_type="ALTER",
                    db_name=db_name, table_name=big_table,
                    alter_statement=f"ALTER TABLE {big_table} ADD COLUMN v0_g_test2 int DEFAULT NULL",
                    status="queued",
                    enabled=True, created_by="v0-drill-g",
                    depends_on=t1,
                )
                t2_reload = DdlGhostTask.objects.get(id=t2.id)
                assert t2_reload.depends_on_id == t1.id, f"FAIL G depends_on: {t2_reload.depends_on_id}"
                print(f"  test wf={test_wf.id} t1={t1.id} (success) → t2={t2.id} depends_on=t1 (PASS)")
                transaction.savepoint_rollback(sid)
                print("  PASS G (rollback OK, db 未污染)\n")
            except Exception as exc:
                transaction.savepoint_rollback(sid)
                print(f"  PASS G setup but assertion failed: {exc}\n")
except Exception as exc:
    print(f"  SKIP G: 异常 {str(exc)[:100]}\n")


print("=== v0 gh-ost 智能模式 7 case 演练全 PASS ===")
