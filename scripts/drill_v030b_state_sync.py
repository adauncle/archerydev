"""
v0.3.0-beta 状态机修复端到端演练
================================
在 134 dev 上跑，验证 3 个修复的完整闭环。

执行方式: 把本脚本 scp 到 134 dev /opt/archery/prod 跑 (用 prod venv 的 Python)
或 ssh 进 134 dev 后 cat | python (不推荐，输出乱码)

实际跑: 把本文件 scp 到 /tmp/v030b/, 然后 ssh 跑
"""
import os
import sys
import time
import json
import django
import pymysql

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
sys.path.insert(0, "/opt/archery/prod")
django.setup()

# ALLOWED_HOSTS 加 testserver 临时
from django.conf import settings
if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver", "localhost", "127.0.0.1"]
print(f"[drill] ALLOWED_HOSTS={settings.ALLOWED_HOSTS[:5]}...")

from django.utils import timezone
from django.test import Client
from sql.models import Users, SqlWorkflow, SqlWorkflowContent, Instance
from sql.extensions.ddl_gh_ost.models import DdlGhostTask
from sql.extensions.ddl_gh_ost.services.poller import _sync_workflow_status

# ===== config =====
ARCHERY_BASE = "http://127.0.0.1:9003"
TEST_INSTANCE_ID = 1  # 172.20.2.134:3306 archery master, 改 dbops 凭据
TEST_DB = "archery_dev"
TEST_TABLE = "accesscard_black_detail"
# 真实凭据 — 不写入 git 跟踪文件, 从 /etc/archery 读
DBOPS_PWD = open("/etc/archery/dbops_password").read().strip()
print(f"[drill] DBOPS_PWD len: {len(DBOPS_PWD)} chars")


def get_dbops_conn(db=None):
    return pymysql.connect(
        host="127.0.0.1", port=3306, user="dbops", password=DBOPS_PWD,
        database=db, connect_timeout=5, autocommit=True,
    )


def ensure_table_state():
    """确保测试表存在 + 添加一列 'beta_state_col INT DEFAULT 0' 备演练用。"""
    conn = get_dbops_conn(TEST_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SHOW TABLES LIKE '{TEST_TABLE}'")
            if not cur.fetchone():
                print(f"[drill] 表 {TEST_DB}.{TEST_TABLE} 不存在, 无法演练")
                sys.exit(1)
            cur.execute(f"SHOW COLUMNS FROM {TEST_TABLE} LIKE 'beta_state_col'")
            if not cur.fetchone():
                print(f"[drill] 加演练列 beta_state_col")
                cur.execute(f"ALTER TABLE {TEST_TABLE} ADD COLUMN beta_state_col INT DEFAULT 0")
            cur.execute(f"SELECT COUNT(*) FROM {TEST_TABLE}")
            row_count = cur.fetchone()[0]
            print(f"[drill] {TEST_DB}.{TEST_TABLE} rows={row_count}")
    finally:
        conn.close()


def drop_shadow_tables():
    """演练前清理影子表残留（cut-over 失败 / 中途断电遗留）。"""
    conn = get_dbops_conn(TEST_DB)
    try:
        with conn.cursor() as cur:
            for tbl in [f"_{TEST_TABLE}_gho", f"_{TEST_TABLE}_del", f"_{TEST_TABLE}_ghc"]:
                cur.execute(f"DROP TABLE IF EXISTS `{TEST_DB}`.`{tbl}`")
        print("[drill] 影子表清理 OK")
    finally:
        conn.close()


def make_workflow(engineer, sql_text):
    """直接 ORM 创建工单 + content + content row, 走旁路不走 submit 接口。"""
    instance = Instance.objects.get(pk=TEST_INSTANCE_ID)
    wf = SqlWorkflow.objects.create(
        workflow_name=f"[drill-v030b] {int(time.time())}",
        group_id=1,
        group_name="DBA",
        engineer=engineer,
        engineer_display=engineer,
        audit_auth_groups="DBA",
        status="workflow_review_pass",  # 模拟审核已通过
        is_backup=True,
        instance=instance,
        db_name=TEST_DB,
        syntax_type=1,  # DDL
    )
    SqlWorkflowContent.objects.create(
        workflow=wf, sql_content=sql_text, review_content="{}",
    )
    print(f"[drill] wf#{wf.id} engineer={engineer} status={wf.status}")
    return wf


def run_case_1(engineer, client):
    """Case 1: 启用 gh-ost → cut-over success → wf.status=workflow_finish"""
    print("\n" + "=" * 60)
    print("Case 1: cut-over success → workflow_finish")
    print("=" * 60)

    # 准备: 演练用 ALTER, 改列注释 (无副作用)
    sql = f"ALTER TABLE {TEST_TABLE} COMMENT 'drill-v030b-case1'"
    wf = make_workflow(engineer, sql)

    # 1) precheck
    r = client.post(f"/gh_ost/precheck/{wf.id}/")
    j = r.json()
    print(f"[case1] precheck: ok={j.get('ok')} passed={j.get('passed')} summary={j.get('summary', '')[:80]}")
    assert j.get("ok") and j.get("passed"), f"precheck fail: {j}"

    # 2) enable
    r = client.post(f"/gh_ost/enable/{wf.id}/")
    j = r.json()
    print(f"[case1] enable: ok={j.get('ok')} task_id={j.get('task_id')} status={j.get('status')}")
    assert j.get("ok") and j.get("passed"), f"enable fail: {j}"
    task_id = j["task_id"]

    # 3) start
    r = client.post(f"/gh_ost/start/{wf.id}/")
    j = r.json()
    print(f"[case1] start: ok={j.get('ok')} pid={j.get('pid')}")
    assert j.get("ok"), f"start fail: {j}"

    # 4) 等 poller 跑完 (cut-over < 30s)
    deadline = time.time() + 60
    while time.time() < deadline:
        task = DdlGhostTask.objects.get(pk=task_id)
        if task.is_terminal:
            break
        time.sleep(2)
    task = DdlGhostTask.objects.get(pk=task_id)
    print(f"[case1] task#{task_id} final: status={task.status} pct={task.progress_pct} dur={task.duration_seconds}s")
    assert task.status == "success", f"task 没 success: {task.status}"

    # 5) 验证 wf.status 同步
    wf.refresh_from_db()
    print(f"[case1] wf#{wf.id} status after success: {wf.status} finish_time={wf.finish_time}")
    assert wf.status == "workflow_finish", f"wf.status 没同步: {wf.status}"

    # 6) 验证 is_can_execute 联动 (has_active_ghost_task=False 因 task terminal)
    r = client.get(f"/detail/{wf.id}/")
    body = r.content.decode("utf-8", "replace")
    # active 状态时页面含 iframe, terminal 状态时含"cut-over 成功"字样
    assert "cut-over 成功" in body, f"详情页没显示终态摘要"
    assert "btn-enable-ghost" not in body, f"详情页不应再显示启用按钮 (button id)"
    assert '<iframe src="/gh_ost/progress' not in body, f"详情页不应再显示进度面板 iframe"
    print(f"[case1] 详情页终态 UI OK (终态摘要+无按钮+无 iframe)")

    return wf.id, task_id


def run_case_2(engineer, client):
    """Case 2: 启用 gh-ost → cancel → wf.status 保持 workflow_review_pass"""
    print("\n" + "=" * 60)
    print("Case 2: cancel → wf.status 保持原状态")
    print("=" * 60)

    sql = f"ALTER TABLE {TEST_TABLE} COMMENT 'drill-v030b-case2'"
    wf = make_workflow(engineer, sql)

    # 1) precheck + enable
    r = client.post(f"/gh_ost/precheck/{wf.id}/")
    assert r.json().get("ok")
    r = client.post(f"/gh_ost/enable/{wf.id}/")
    j = r.json()
    print(f"[case2] enable: ok={j.get('ok')} task_id={j.get('task_id')}")
    assert j.get("ok")
    task_id = j["task_id"]

    # 2) start
    r = client.post(f"/gh_ost/start/{wf.id}/")
    j = r.json()
    print(f"[case2] start: pid={j.get('pid')}")
    assert j.get("ok")

    # 3) 跑 5s 后取消
    time.sleep(5)
    r = client.post(f"/gh_ost/cancel/{wf.id}/")
    j = r.json()
    print(f"[case2] cancel: ok={j.get('ok')} status={j.get('status')}")
    assert j.get("ok") and j["status"] == "cancelled"

    # 4) 等 poller 退出
    time.sleep(3)
    task = DdlGhostTask.objects.get(pk=task_id)
    print(f"[case2] task#{task_id} final: status={task.status}")
    assert task.status == "cancelled"

    # 5) wf.status 应该保持 workflow_review_pass (cancel 不动 wf.status)
    wf.refresh_from_db()
    print(f"[case2] wf#{wf.id} status after cancel: {wf.status}")
    assert wf.status == "workflow_review_pass", f"cancel 不应改 wf.status, got {wf.status}"

    # 6) 详情页: 终态摘要显示"已取消" + 启用按钮不显示
    r = client.get(f"/detail/{wf.id}/")
    body = r.content.decode("utf-8", "replace")
    assert "已取消" in body, f"详情页应显示'已取消'终态摘要"
    assert "btn-enable-ghost" not in body, f"详情页不应显示启用按钮 (button id)"
    print(f"[case2] 详情页取消后 UI OK (无启用按钮)")

    return wf.id, task_id


def main():
    ensure_table_state()
    drop_shadow_tables()

    # 用 superuser 跑接口 (admin)
    u = Users.objects.get(username="archery")
    client = Client()
    client.force_login(u, backend="django.contrib.auth.backends.ModelBackend")
    print(f"[drill] login as archery (superuser)")

    # Case 1: success → workflow_finish
    wf1, task1 = run_case_1(u.username, client)

    # Case 2: cancel → workflow_review_pass (不变)
    wf2, task2 = run_case_2(u.username, client)

    print("\n" + "=" * 60)
    print("[drill] 全部 Case 通过 ✅")
    print(f"  Case 1 (success→finish):  wf#{wf1} task#{task1}")
    print(f"  Case 2 (cancel→不动 wf): wf#{wf2} task#{task2}")
    print("=" * 60)


if __name__ == "__main__":
    main()
