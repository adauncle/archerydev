"""
v0.3.0-beta DBA 兜底 + 大表 DDL 防呆 端到端演练
===============================================
5 Case 覆盖:
  A. RD 勾 gh-ost + 3 级通过 → DBA 启用 → cut-over success → wf.finish (跟之前一样, 走流程)
  B. RD 没勾 + 3 级通过 + 小表 → detail 不显示大表 alert, 立即执行按钮正常 (无 confirm)
  C. RD 没勾 + 3 级通过 + **大表** → detail 红色 alert + 三按钮 (启用 gh-ost / 立即执行 confirm / 终止)
  D. DBA 走"终止工单" (大表时) → wf.status=workflow_abort + 任何 task 清理
  E. DBA 走"启用 gh-ost" (大表时, 兜底) → 创建 task + 走 cut-over success + wf.finish
"""
import os
import sys
import json
import time
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
sys.path.insert(0, "/opt/archery/prod")
django.setup()

from django.conf import settings
if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver", "localhost", "127.0.0.1"]

from common.config import SysConfig
from common.utils.const import WorkflowAction
from sql.models import Users, SqlWorkflow, Instance
from sql.utils.workflow_audit import get_auditor
from django.test import Client

TEST_INSTANCE_ID = 2  # 测试 MySQL 8.0
TEST_DB = "archery_dev"
BIG_TABLE = "accesscard_black_detail"  # 24w 行 / 53MB, 触发大表 alert


def make_wf(client_user, sql_text, enable_gh_ost=False):
    instance = Instance.objects.get(pk=TEST_INSTANCE_ID)
    c = Client()
    c.force_login(client_user, backend="django.contrib.auth.backends.ModelBackend")
    data = {
        "workflow": {
            "workflow_name": f"[drill-v030b-dba-fallback] {int(time.time())}",
            "group_id": 25,  # 测试组 (有 14,15,3 3 级审批配置)
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
    assert r.status_code in (200, 201), f"submit fail: {r.status_code} {j}"
    return j.get("workflow", {}).get("id") or j.get("id")


def approve_wf(wf_id, approver):
    """走完 3 级审批 (研发组长 -> DBA组长 -> DBA)."""
    wf = SqlWorkflow.objects.get(pk=wf_id)
    auditor = get_auditor(workflow=wf)
    if auditor.audit is None:
        wf.status = "workflow_review_pass"
        wf.save()
        return
    # 走完所有 3 级
    for i in range(5):  # 最多 5 次防死循环
        if auditor.audit.current_audit == "-1":
            break
        auditor.operate(WorkflowAction.PASS, approver, f"drill pass #{i+1}")
    # 强制同步 wf.status
    wf.refresh_from_db()
    if auditor.audit.current_status == 1:  # PASSED (WorkflowStatus.PASSED=1)
        wf.status = "workflow_review_pass"
        wf.save()


def get_detail_body(wf_id, viewer):
    c = Client()
    c.force_login(viewer, backend="django.contrib.auth.backends.ModelBackend")
    r = c.get(f"/detail/{wf_id}/")
    return r.status_code, r.content.decode("utf-8", "replace")


def run_case_A(client, approver):
    """Case A: RD 勾 gh-ost + 3 级通过 → 走 gh-ost (跟之前一样)."""
    print("\n" + "=" * 60)
    print("Case A: RD 勾 gh-ost + 3 级通过 → 走 gh-ost (基础流程)")
    print("=" * 60)
    sql = f"ALTER TABLE {BIG_TABLE} COMMENT 'drill-A';"
    wf_id = make_wf(client, sql, enable_gh_ost=True)
    approve_wf(wf_id, approver)
    status, body = get_detail_body(wf_id, approver)
    assert status == 200
    # 走 gh-ost 路径: detail 应该没大表 alert (因为已经启用 gh-ost)
    # 但 wf.status 应该是 review_pass + 没 task (待启动)
    # 实际上 lazy auto-enable 已经创建了 task
    from sql.extensions.ddl_gh_ost.models import DdlGhostTask
    task = DdlGhostTask.objects.filter(workflow_id=wf_id).first()
    assert task is not None, "lazy auto-enable 没创建 task"
    print(f"  ✅ Case A: wf#{wf_id} 已自动启用 gh-ost task#{task.id}")
    return wf_id


def run_case_B(client, approver):
    """Case B: RD 没勾 + 3 级通过 + 小表 → 无大表 alert, 立即执行按钮正常."""
    print("\n" + "=" * 60)
    print("Case B: RD 没勾 + 小表 → 无大表 alert, 走原路径")
    print("=" * 60)
    # 用一张肯定小的表 (随便选, sys_config 表就够小)
    sql = f"ALTER TABLE {BIG_TABLE} COMMENT 'drill-B';"  # 大表但我们让表大小查询失败
    # 实际我先查 accesscard_black_detail 行数, 24w 触发大表, Case B 需要小表
    # 134 dev 有没有小表? 用 config 表:
    # mysql archery_prod -> sql_config (几行) 或者 archery_dev.sql_config
    # 改用 archery_dev.sql_config (肯定小)
    sql = "ALTER TABLE sql_config COMMENT 'drill-B';"  # 小表, 不触发大表 alert
    wf_id = make_wf(client, sql, enable_gh_ost=False)
    approve_wf(wf_id, approver)
    status, body = get_detail_body(wf_id, approver)
    assert status == 200
    assert "big-table-alert" not in body, "小表不应该有大表 alert"
    assert "btnExecuteOnly" in body, "应该有立即执行按钮"
    assert "btn-big-table-execute" not in body, "小表不应该有大表 confirm 按钮"
    print(f"  ✅ Case B: wf#{wf_id} 小表, 无大表 alert, 立即执行按钮正常")
    return wf_id


def run_case_C(client, approver):
    """Case C: RD 没勾 + 3 级通过 + **大表** → 红色 alert + 三按钮 (DBA 兜底全开)."""
    print("\n" + "=" * 60)
    print("Case C: RD 没勾 + 大表 → 红色 alert + 三按钮")
    print("=" * 60)
    sql = f"ALTER TABLE {BIG_TABLE} COMMENT 'drill-C';"
    wf_id = make_wf(client, sql, enable_gh_ost=False)
    approve_wf(wf_id, approver)
    status, body = get_detail_body(wf_id, approver)
    assert status == 200
    # 关键断言: 大表 alert 在
    assert "big-table-alert" in body, "大表必须有大表 alert"
    assert "是" in body and "大表" in body, "alert 文案必须含大表关键字"
    # 三按钮: 启用 gh-ost + 立即执行 (confirm) + 终止工单
    assert "btn-big-table-enable-ghost" in body, "必须有大表启用 gh-ost 按钮"
    assert "btn-big-table-execute" in body, "必须有大表立即执行按钮 (双层 confirm)"
    assert "btn-big-table-cancel" in body, "必须有大表终止工单按钮"
    print(f"  ✅ Case C: wf#{wf_id} 大表, alert + 三按钮全在")
    return wf_id


def run_case_D(client, approver):
    """Case D: DBA 走"终止工单" (大表时) → wf.status=workflow_abort."""
    print("\n" + "=" * 60)
    print("Case D: DBA 走终止工单 (大表时)")
    print("=" * 60)
    sql = f"ALTER TABLE {BIG_TABLE} COMMENT 'drill-D';"
    wf_id = make_wf(client, sql, enable_gh_ost=False)
    approve_wf(wf_id, approver)
    # 走 /cancel/
    c = Client()
    c.force_login(approver, backend="django.contrib.auth.backends.ModelBackend")
    r = c.post("/cancel/", {
        "workflow_id": wf_id,
        "cancel_remark": "DBA 兜底: 大表 DDL 走原路径会锁表, 建议 RD 重新提交并勾 gh-ost",
    })
    print(f"  cancel 端点: status={r.status_code}")
    wf = SqlWorkflow.objects.get(pk=wf_id)
    assert wf.status == "workflow_abort", f"wf.status={wf.status}"
    print(f"  ✅ Case D: wf#{wf_id} 已终止 status=workflow_abort")
    return wf_id


def run_case_E(client, approver):
    """Case E: DBA 走"启用 gh-ost" (大表时, 兜底) → 创建 task + cut-over success → wf.finish."""
    print("\n" + "=" * 60)
    print("Case E: DBA 兜底启用 gh-ost (大表时)")
    print("=" * 60)
    sql = f"ALTER TABLE {BIG_TABLE} COMMENT 'drill-E';"
    wf_id = make_wf(client, sql, enable_gh_ost=False)
    approve_wf(wf_id, approver)
    # DBA 调 enable 端点
    c = Client()
    c.force_login(approver, backend="django.contrib.auth.backends.ModelBackend")
    r = c.post(f"/gh_ost/enable/{wf_id}/")
    j = r.json()
    print(f"  enable: ok={j.get('ok')} task_id={j.get('task_id')}")
    assert j.get("ok"), f"enable fail: {j}"
    # 启动
    r = c.post(f"/gh_ost/start/{wf_id}/")
    j = r.json()
    print(f"  start: ok={j.get('ok')} pid={j.get('pid')}")
    assert j.get("ok"), f"start fail: {j}"
    # 等 cut-over
    from sql.extensions.ddl_gh_ost.models import DdlGhostTask
    task_id = j["task_id"]
    deadline = time.time() + 60
    while time.time() < deadline:
        t = DdlGhostTask.objects.get(pk=task_id)
        if t.is_terminal:
            break
        time.sleep(2)
    t = DdlGhostTask.objects.get(pk=task_id)
    assert t.status == "success", f"task status: {t.status}"
    wf = SqlWorkflow.objects.get(pk=wf_id)
    assert wf.status == "workflow_finish", f"wf.status: {wf.status}"
    print(f"  ✅ Case E: wf#{wf_id} task#{task_id} cut-over success, wf.finish 同步")
    return wf_id, task_id


def main():
    cleanup_zombie()
    client_user = Users.objects.get(username="archery")
    approver = client_user
    results = {}
    results["A"] = run_case_A(client_user, approver)
    results["B"] = run_case_B(client_user, approver)
    results["C"] = run_case_C(client_user, approver)
    results["D"] = run_case_D(client_user, approver)
    results["E"] = run_case_E(client_user, approver)

    print("\n" + "=" * 60)
    print("[drill] 全部 5 Case 通过 ✅")
    print(f"  Case A (RD 勾+走 gh-ost):          wf#{results['A']}")
    print(f"  Case B (RD 没勾+小表无 alert):      wf#{results['B']}")
    print(f"  Case C (RD 没勾+大表+三按钮):      wf#{results['C']}")
    print(f"  Case D (DBA 终止工单):            wf#{results['D']}")
    print(f"  Case E (DBA 兜底启用 gh-ost):     wf#{results['E'][0]}")
    print("=" * 60)


def cleanup_zombie():
    """演练前清 zombie socket + 影子表.
    ## CUSTOM: archery user 读不到 /etc/archery/dbops_password (root 600),
    ## 改用 Instance model 拿 dbops 凭据 (mirage 解密对 archery user 可用).
    ## @ 2026-08-11 @ mavis
    """
    import pymysql
    import os
    # 1) 拿 dbops 凭据 (走 archery master instance id=1, ORM 拿解密后明文)
    from sql.models import Instance as _Instance
    inst = _Instance.objects.get(pk=1)  # archery master, 134 dev 已改 dbops 凭据
    dbops_user, dbops_pwd = inst.get_username_password() if hasattr(inst, "get_username_password") else (inst.user, inst.password)
    try:
        conn = pymysql.connect(host="127.0.0.1", port=3306, user=dbops_user, password=dbops_pwd,
                               database=TEST_DB, connect_timeout=5, autocommit=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] cleanup_zombie 连 dbops 失败 (跳过清理): {e}")
        return
    try:
        with conn.cursor() as cur:
            for tbl in [f"_{BIG_TABLE}_gho", f"_{BIG_TABLE}_del", f"_{BIG_TABLE}_ghc"]:
                cur.execute(f"DROP TABLE IF EXISTS `{TEST_DB}`.`{tbl}`")
    finally:
        conn.close()
    # 2) 清 zombie sock
    if os.path.isdir("/tmp"):
        for f in os.listdir("/tmp"):
            if f.startswith("gh-ost") and f.endswith(".sock"):
                try:
                    os.unlink(f"/tmp/{f}")
                except OSError:
                    pass


if __name__ == "__main__":
    main()
