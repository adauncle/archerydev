"""
v0.3.0-beta gh-ost 审批守卫 端到端演练
========================================
5 Case 覆盖:
  A. 提交勾 gh-ost + 审批前访问详情页 → 显示"已申请 gh-ost"提示, 无启用按钮
  B. 审批通过 → lazy auto-enable 触发 → DdlGhostTask 创建 (status=queued)
  C. 启动 gh-ost + cut-over success → wf.status 自动切 workflow_finish
  D. 提交勾 gh-ost + 审批拒绝 → DdlGhostTask 清理 + wf.enable_gh_ost 标记保留
  E. 未勾 gh-ost + 审批通过 → 不自动启用, 详情页显示启用按钮 (DBA/提交人手动)
"""
import os
import sys
import time
import json
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
sys.path.insert(0, "/opt/archery/prod")
django.setup()

from django.conf import settings
if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver", "localhost", "127.0.0.1"]

from django.utils import timezone
from django.test import Client
from django.contrib.auth.backends import ModelBackend
from common.utils.const import WorkflowAction, WorkflowStatus
from sql.models import Users, SqlWorkflow, SqlWorkflowContent, Instance
from sql.utils.workflow_audit import get_auditor
from sql.extensions.ddl_gh_ost.models import DdlGhostTask
from sql.engines import get_engine

TEST_INSTANCE_ID = 2  # 测试 MySQL 8.0 (有 can_write tag)
TEST_DB = "archery_dev"
TEST_TABLE = "accesscard_black_detail"
DBOPS_PWD = open("/etc/archery/dbops_password").read().strip()


def cleanup_table():
    """演练前清表残留 (影子表 + 演练用列)."""
    import pymysql
    conn = pymysql.connect(
        host="127.0.0.1", port=3306, user="dbops", password=DBOPS_PWD,
        database=TEST_DB, connect_timeout=5, autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            for tbl in [f"_{TEST_TABLE}_gho", f"_{TEST_TABLE}_del", f"_{TEST_TABLE}_ghc"]:
                cur.execute(f"DROP TABLE IF EXISTS `{TEST_DB}`.`{tbl}`")
    finally:
        conn.close()


def make_wf(client_user, sql_text, enable_gh_ost=False):
    """走 /api/v1/workflow/ 端点建工单 (模拟提交页)"""
    instance = Instance.objects.get(pk=TEST_INSTANCE_ID)
    c = Client()
    c.force_login(client_user, backend="django.contrib.auth.backends.ModelBackend")
    # WorkflowContentSerializer 嵌套: {workflow: {...}, sql_content: ...}
    data = {
        "workflow": {
            "workflow_name": f"[drill-v030b-approval] {int(time.time())}",
            "group_id": 8,  # pod core for archery
            "instance": instance.id,
            "db_name": TEST_DB,
            "is_backup": True,
            "is_offline_export": 0,
        },
        "sql_content": sql_text,
        "review_content": "{}",
        "enable_ghost": enable_gh_ost,
    }
    r = c.post("/api/v1/workflow/", data=json.dumps(data), content_type="application/json")
    j = r.json()
    assert r.status_code in (200, 201), f"submit failed: {r.status_code} {j}"
    wf_id = j.get("workflow", {}).get("id") or j.get("id")
    print(f"  [submit] wf#{wf_id} enable_gh_ost={enable_gh_ost} ghost_result={j.get('enable_ghost', {})}")
    return wf_id, j


def approve_wf(wf_id, approver):
    """模拟审批通过 — 直接 ORM 调 auditor.operate(PASS) + 改 wf.status"""
    wf = SqlWorkflow.objects.get(pk=wf_id)
    auditor = get_auditor(workflow=wf)
    if auditor.audit is None:
        # 没审批流 (DBA 直接通过) — 直接改 status
        wf.status = "workflow_review_pass"
        wf.save()
        print(f"  [approve] wf#{wf_id} 无审批流, 直改 status=review_pass")
    else:
        auditor.operate(WorkflowAction.PASS, approver, "drill approve")
        if auditor.audit.current_status == WorkflowStatus.PASSED:
            wf.status = "workflow_review_pass"
            wf.save()
        print(f"  [approve] wf#{wf_id} audit.operate(PASS) done, wf.status={wf.status}")


def reject_wf(wf_id, rejecter, remark="drill reject"):
    """模拟审批拒绝 — 走 /cancel/ 端点 (DBA 自己撤回/驳回工单, 内部用 auditor.operate(REJECT) + status=abort)"""
    c = Client()
    c.force_login(rejecter, backend="django.contrib.auth.backends.ModelBackend")
    r = c.post("/cancel/", {"workflow_id": wf_id, "cancel_remark": remark})
    print(f"  [reject] wf#{wf_id} cancel 端点: status={r.status_code}")


def get_detail_body(wf_id, viewer):
    """GET /detail/<wf>/ 返回 HTML body"""
    c = Client()
    c.force_login(viewer, backend="django.contrib.auth.backends.ModelBackend")
    r = c.get(f"/detail/{wf_id}/")
    return r.status_code, r.content.decode("utf-8", "replace")


def run_case_A(client, approver):
    """Case A: 提交勾 gh-ost + 审批前 → 显示'已申请'提示, 无启用按钮"""
    print("\n" + "=" * 60)
    print("Case A: 提交勾 gh-ost, 审批前详情页")
    print("=" * 60)
    sql = f"ALTER TABLE {TEST_TABLE} COMMENT 'drill-v030b-approval-A';"
    wf_id, _ = make_wf(client, sql, enable_gh_ost=True)

    # 验证: wf.enable_gh_ost=True + status=manreviewing + 没 task
    wf = SqlWorkflow.objects.get(pk=wf_id)
    print(f"  wf#{wf_id} enable_gh_ost={wf.enable_gh_ost} status={wf.status}")
    assert wf.enable_gh_ost is True, f"wf.enable_gh_ost 没存上: {wf.enable_gh_ost}"
    assert wf.status == "workflow_manreviewing", f"wf.status: {wf.status}"
    assert not DdlGhostTask.objects.filter(workflow=wf).exists(), "审批前不该有 DdlGhostTask"

    # 验证: 详情页显示"已申请"提示 + 无启用按钮
    status, body = get_detail_body(wf_id, client)
    assert status == 200, f"detail 200 失败: {status}"
    assert "已申请 gh-ost 无锁变更" in body, "应显示'已申请'提示"
    assert "等待审批通过" in body, "应显示'等待审批'字样"
    assert "btn-enable-ghost" not in body, "审批前不该有启用按钮"
    print("  ✅ Case A 通过: 提示在 + 按钮隐藏")
    return wf_id


def run_case_B(client, approver):
    """Case B: 审批通过 → lazy auto-enable"""
    print("\n" + "=" * 60)
    print("Case B: 审批通过 → lazy auto-enable")
    print("=" * 60)
    sql = f"ALTER TABLE {TEST_TABLE} COMMENT 'drill-v030b-approval-B';"
    wf_id, _ = make_wf(client, sql, enable_gh_ost=True)
    approve_wf(wf_id, approver)

    # 验证: 访问详情页 → 触发 lazy auto-enable → 写 DdlGhostTask
    status, body = get_detail_body(wf_id, approver)
    assert status == 200, f"detail 200 失败: {status}"
    task = DdlGhostTask.objects.filter(workflow_id=wf_id).first()
    assert task is not None, f"lazy auto-enable 没创建 DdlGhostTask: {wf_id}"
    print(f"  ✅ Case B 通过: auto-enable 创建 task#{task.id} status={task.status}")
    return wf_id, task.id


def run_case_C(client, approver):
    """Case C: 审批通过 + 启动 → cut-over success → wf.status=finish"""
    print("\n" + "=" * 60)
    print("Case C: 启动 gh-ost → cut-over success → wf.finish")
    print("=" * 60)
    wf_id, task_id = run_case_B(client, approver)

    # 启动
    c = Client()
    c.force_login(approver, backend="django.contrib.auth.backends.ModelBackend")
    r = c.post(f"/gh_ost/start/{wf_id}/")
    j = r.json()
    print(f"  start: ok={j.get('ok')} pid={j.get('pid')}")
    assert j.get("ok"), f"start fail: {j}"

    # 等 cut-over
    deadline = time.time() + 60
    while time.time() < deadline:
        task = DdlGhostTask.objects.get(pk=task_id)
        if task.is_terminal:
            break
        time.sleep(2)
    task = DdlGhostTask.objects.get(pk=task_id)
    print(f"  task#{task_id} final: status={task.status} dur={task.duration_seconds}s")
    assert task.status == "success", f"task 没 success: {task.status}"

    wf = SqlWorkflow.objects.get(pk=wf_id)
    print(f"  wf#{wf_id} status: {wf.status}")
    assert wf.status == "workflow_finish", f"wf.status 没同步: {wf.status}"
    print("  ✅ Case C 通过: cut-over + wf.finish 同步")
    return wf_id


def run_case_D(client, approver):
    """Case D: 提交勾 gh-ost + 审批拒绝 → 清理 DdlGhostTask + 标记保留"""
    print("\n" + "=" * 60)
    print("Case D: 提交勾 gh-ost + 审批拒绝 → 清理")
    print("=" * 60)
    sql = f"ALTER TABLE {TEST_TABLE} COMMENT 'drill-v030b-approval-D';"
    wf_id, _ = make_wf(client, sql, enable_gh_ost=True)

    # 拒绝 (走 cancel 端点, 含 task 清理)
    reject_wf(wf_id, approver, remark="drill reject D")

    # 验证: wf.status=workflow_abort + enable_gh_ost=True 保留 + 无 task
    wf = SqlWorkflow.objects.get(pk=wf_id)
    print(f"  wf#{wf_id} status={wf.status} enable_gh_ost={wf.enable_gh_ost}")
    assert wf.status == "workflow_abort", f"wf.status: {wf.status}"
    assert wf.enable_gh_ost is True, f"标记应保留: {wf.enable_gh_ost}"
    tasks = DdlGhostTask.objects.filter(workflow=wf)
    assert not tasks.exists(), f"拒绝后不该有 task, got: {tasks}"
    print("  ✅ Case D 通过: 拒绝后 task 清理 + 标记保留")
    return wf_id


def run_case_E(client, approver):
    """Case E: 未勾 gh-ost + 审批通过 → 不 auto-enable, 详情页有启用按钮"""
    print("\n" + "=" * 60)
    print("Case E: 未勾 gh-ost + 审批通过 → 详情页有启用按钮")
    print("=" * 60)
    sql = f"ALTER TABLE {TEST_TABLE} COMMENT 'drill-v030b-approval-E';"
    wf_id, _ = make_wf(client, sql, enable_gh_ost=False)
    approve_wf(wf_id, approver)

    # 验证: 没 task + 详情页有启用按钮
    wf = SqlWorkflow.objects.get(pk=wf_id)
    assert wf.enable_gh_ost is False, f"标记应为 False: {wf.enable_gh_ost}"
    assert not DdlGhostTask.objects.filter(workflow=wf).exists(), "未勾不应 auto-enable"
    status, body = get_detail_body(wf_id, client)
    assert status == 200
    assert "btn-enable-ghost" in body, "审批通过后应显示启用按钮"
    assert "已申请 gh-ost" not in body, "未勾不应显示'已申请'提示"
    print("  ✅ Case E 通过: 未勾不 auto-enable, 显示启用按钮")
    return wf_id


def main():
    cleanup_table()
    # 134 dev 上 archery user 是 superuser
    client = Users.objects.get(username="archery")
    # approver 暂用同一个 (DBA 审批流简化; 真实场景用 DBA 角色)
    approver = client

    results = {}
    results["A"] = run_case_A(client, approver)
    results["C"] = run_case_C(client, approver)  # Case C 内含 Case B
    results["D"] = run_case_D(client, approver)
    results["E"] = run_case_E(client, approver)

    print("\n" + "=" * 60)
    print("[drill] 全部 Case 通过 ✅")
    print(f"  Case A (审批前提示):       wf#{results['A']}")
    print(f"  Case C (auto-enable+finish): wf#{results['C']}")
    print(f"  Case D (拒绝清理):         wf#{results['D']}")
    print(f"  Case E (未勾不 auto):      wf#{results['E']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
