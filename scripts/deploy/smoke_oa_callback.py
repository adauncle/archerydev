"""v0.2.0 callback handler smoke test —— 不依赖 pytest，直接跑。

模拟 5 个场景：
    1. 单级审批通过 (audit_auth_groups=3, no next)
    2. 多级审批推进 (audit_auth_groups=3,4, current=3, next=4)
    3. 驳回 (refuse)
    4. 终止 (instance terminate)
    5. 重复回调幂等

运行：
    cd /opt/archery/prod
    sudo -u archery ./venv/bin/python scripts/deploy/smoke_oa_callback.py
"""
import os
import sys

# Bootstrap Django
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django  # noqa: E402
django.setup()

import json  # noqa: E402
from django.utils import timezone  # noqa: E402

from common.utils.const import WorkflowStatus  # noqa: E402
from sql.extensions.dingtalk_oa.models import (  # noqa: E402
    GroupDingtalkAuditor,
    WorkflowAuditExternal,
)
from sql.extensions.dingtalk_oa.services.oa_callback_handler import handle_oa_callback  # noqa: E402
from sql.models import (  # noqa: E402
    ResourceGroup,
    SqlWorkflow,
    Users,
    WorkflowAudit,
    WorkflowAuditDetail,
    WorkflowLog,
)


PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def log(msg, ok=True):
    print(f"  [{PASS if ok else FAIL}] {msg}")


def setup_test_user():
    """确保测试用的 Archery User 存在，且 ding_user_id=oa_tester_1。"""
    u, _ = Users.objects.get_or_create(
        username="oa_tester_1",
        defaults=dict(
            display="OA 测试审批人",
            email="oa_tester@archery.local",
            is_active=1,
            is_staff=1,
        ),
    )
    u.ding_user_id = "oa_tester_1"
    u.save(update_fields=["ding_user_id"])
    return u


def setup_group_mapping():
    """DBA group + 测试组 → 钉钉 user oa_tester_1。"""
    GroupDingtalkAuditor.objects.update_or_create(
        group_id=3,
        resource_group_id=25,
        defaults=dict(
            dingtalk_user_ids=json.dumps(["oa_tester_1"]),
            is_active=True,
        ),
    )


def make_workflow(name, instance_id=2, group_id=25, audit_auth_groups="3", engineer="archery"):
    rg = ResourceGroup.objects.get(group_id=group_id)
    user = Users.objects.get(username=engineer)
    wf = SqlWorkflow.objects.create(
        workflow_name=name,
        group_id=rg.group_id,
        group_name=rg.group_name,
        instance_id=instance_id,
        db_name="archery",
        engineer=user.username,
        engineer_display=user.display,
        audit_auth_groups=audit_auth_groups,
        create_time=timezone.now(),
        status="workflow_manreviewing",
        is_backup=1,
        is_manual=0,
        syntax_type=1,
        demand_url="oa_callback_smoke",
        is_offline_export=0,
        audit_driver="dingtalk_oa",
    )
    return wf


def make_external(audit, pi="SMOKE-PI-001"):
    return WorkflowAuditExternal.objects.create(
        audit=audit,
        source="dingtalk_oa",
        external_process_instance_id=pi,
        external_process_code="PROC-SMOKE",
        external_status="RUNNING",
    )


def make_event(pi, event_type="bpms_task_change", inner_type="finish", result="agree",
               staff_id="oa_tester_1", staff_name="OA 测试审批人", remark="OK 通过"):
    return {
        "EventType": event_type,
        "processInstanceId": pi,
        "processCode": "PROC-SMOKE",
        "type": inner_type,
        "result": result,
        "StaffId": staff_id,
        "StaffName": staff_name,
        "remark": remark,
        "taskId": "TASK-001",
        "EventId": f"evt-{pi}-{inner_type}-{result}-{timezone.now().timestamp()}",
        "createTime": int(timezone.now().timestamp() * 1000),
    }


def case1_single_level_pass():
    print("\n=== Case 1: 单级审批通过 (audit_auth_groups=3) ===")
    pi = f"SMOKE-C1-{int(timezone.now().timestamp())}"
    wf = make_workflow(f"smoke_c1_{int(timezone.now().timestamp())}", audit_auth_groups="3")
    audit = WorkflowAudit.objects.create(
        workflow_id=wf.id, workflow_type=2, workflow_title=wf.workflow_name,
        audit_auth_groups="3", current_audit="3", next_audit="-1",
        current_status=WorkflowStatus.WAITING,
        create_user="archery", create_user_display="Archery Admin",
        group_id=25, group_name="测试组",
    )
    ext = make_external(audit, pi=pi)
    result = handle_oa_callback(make_event(pi, inner_type="finish", result="agree",
                                            staff_id="oa_tester_1", staff_name="OA 测试审批人",
                                            remark="OK 通过"))
    log(f"handle_oa_callback result={result}", result["status"] == "applied")
    audit.refresh_from_db()
    log(f"audit.current_status={audit.current_status} (期望 {WorkflowStatus.PASSED})",
        audit.current_status == WorkflowStatus.PASSED)
    log(f"audit.current_audit='{audit.current_audit}' (期望 '-1')",
        audit.current_audit == "-1")
    detail = WorkflowAuditDetail.objects.filter(audit_id=audit.audit_id).last()
    log(f"detail.audit_user='{detail.audit_user}' (期望 'oa_tester_1')",
        detail.audit_user == "oa_tester_1")
    log(f"detail.remark 含 'OA 测试审批人' 和 'OK 通过'",
        "OA 测试审批人" in detail.remark and "OK 通过" in detail.remark)
    log_entry = WorkflowLog.objects.filter(audit_id=audit.audit_id).last()
    log(f"workflow_log.operator_display='{log_entry.operator_display}'",
        "OA 测试审批人" in log_entry.operator_display and "via 钉钉" in log_entry.operator_display)
    wf.refresh_from_db()
    log(f"sql_workflow.status='{wf.status}' (期望 'workflow_review_pass')",
        wf.status == "workflow_review_pass")
    return audit.audit_id


def case2_multi_level_advance():
    print("\n=== Case 2: 多级审批推进 (3 -> 4) ===")
    pi = f"SMOKE-C2-{int(timezone.now().timestamp())}"
    wf = make_workflow(f"smoke_c2_{int(timezone.now().timestamp())}", audit_auth_groups="3,4")
    audit = WorkflowAudit.objects.create(
        workflow_id=wf.id, workflow_type=2, workflow_title=wf.workflow_name,
        audit_auth_groups="3,4", current_audit="3", next_audit="4",
        current_status=WorkflowStatus.WAITING,
        create_user="archery", create_user_display="Archery Admin",
        group_id=25, group_name="测试组",
    )
    ext = make_external(audit, pi=pi)
    result = handle_oa_callback(make_event(pi, inner_type="finish", result="agree",
                                            remark="一级通过"))
    log(f"handle_oa_callback result={result}", result["status"] == "applied")
    audit.refresh_from_db()
    log(f"audit.current_audit='{audit.current_audit}' (期望 '4')",
        audit.current_audit == "4")
    log(f"audit.next_audit='{audit.next_audit}' (期望 '-1'，4 是最后一节点)",
        audit.next_audit == "-1")
    log(f"audit.current_status={audit.current_status} (仍为 {WorkflowStatus.WAITING})",
        audit.current_status == WorkflowStatus.WAITING)
    return audit.audit_id


def case3_reject():
    print("\n=== Case 3: 节点驳回 (refuse) ===")
    pi = f"SMOKE-C3-{int(timezone.now().timestamp())}"
    wf = make_workflow(f"smoke_c3_{int(timezone.now().timestamp())}", audit_auth_groups="3")
    audit = WorkflowAudit.objects.create(
        workflow_id=wf.id, workflow_type=2, workflow_title=wf.workflow_name,
        audit_auth_groups="3", current_audit="3", next_audit="-1",
        current_status=WorkflowStatus.WAITING,
        create_user="archery", create_user_display="Archery Admin",
        group_id=25, group_name="测试组",
    )
    ext = make_external(audit, pi=pi)
    result = handle_oa_callback(make_event(pi, inner_type="finish", result="refuse",
                                            remark="SQL 有问题"))
    log(f"handle_oa_callback result={result}", result["status"] == "applied")
    audit.refresh_from_db()
    log(f"audit.current_status={audit.current_status} (期望 {WorkflowStatus.REJECTED})",
        audit.current_status == WorkflowStatus.REJECTED)
    wf.refresh_from_db()
    log(f"sql_workflow.status='{wf.status}' (期望 'workflow_review_reject')",
        wf.status == "workflow_review_reject")
    return audit.audit_id


def case4_terminate():
    print("\n=== Case 4: 实例终止 (instance terminate) ===")
    pi = f"SMOKE-C4-{int(timezone.now().timestamp())}"
    wf = make_workflow(f"smoke_c4_{int(timezone.now().timestamp())}", audit_auth_groups="3")
    audit = WorkflowAudit.objects.create(
        workflow_id=wf.id, workflow_type=2, workflow_title=wf.workflow_name,
        audit_auth_groups="3", current_audit="3", next_audit="-1",
        current_status=WorkflowStatus.WAITING,
        create_user="archery", create_user_display="Archery Admin",
        group_id=25, group_name="测试组",
    )
    ext = make_external(audit, pi=pi)
    result = handle_oa_callback(make_event(
        pi, event_type="bpms_instance_change", inner_type="terminate",
        result="", staff_id="archery", staff_name="Archery Admin", remark="撤回"
    ))
    log(f"handle_oa_callback result={result}", result["status"] == "applied")
    audit.refresh_from_db()
    log(f"audit.current_status={audit.current_status} (期望 {WorkflowStatus.ABORTED})",
        audit.current_status == WorkflowStatus.ABORTED)
    ext.refresh_from_db()
    log(f"ext.external_status='{ext.external_status}' (期望 'TERMINATED')",
        ext.external_status == "TERMINATED")
    return audit.audit_id


def case5_idempotent_repeat():
    print("\n=== Case 5: 重复回调幂等 ===")
    pi = f"SMOKE-C5-{int(timezone.now().timestamp())}"
    wf = make_workflow(f"smoke_c5_{int(timezone.now().timestamp())}", audit_auth_groups="3")
    audit = WorkflowAudit.objects.create(
        workflow_id=wf.id, workflow_type=2, workflow_title=wf.workflow_name,
        audit_auth_groups="3", current_audit="3", next_audit="-1",
        current_status=WorkflowStatus.WAITING,
        create_user="archery", create_user_display="Archery Admin",
        group_id=25, group_name="测试组",
    )
    ext = make_external(audit, pi=pi)
    r1 = handle_oa_callback(make_event(pi, inner_type="finish", result="agree"))
    r2 = handle_oa_callback(make_event(pi, inner_type="finish", result="agree"))
    log(f"第一次 status={r1['status']} (期望 applied)", r1["status"] == "applied")
    log(f"第二次 status={r2['status']} (期望 noop)", r2["status"] == "noop")
    cnt = WorkflowAuditDetail.objects.filter(audit_id=audit.audit_id).count()
    log(f"detail 数量={cnt} (期望 1)", cnt == 1)
    return audit.audit_id


def main():
    print("=" * 60)
    print("v0.2.0 OA callback handler smoke test")
    print("=" * 60)

    print("\n[Setup] 准备测试数据...")
    setup_test_user()
    setup_group_mapping()
    print("  - 创建/更新 Users(oa_tester_1) ding_user_id=oa_tester_1")
    print("  - 创建/更新 GroupDingtalkAuditor(group=3,resource=25) -> oa_tester_1")

    audit_ids = []
    audit_ids.append(case1_single_level_pass())
    audit_ids.append(case2_multi_level_advance())
    audit_ids.append(case3_reject())
    audit_ids.append(case4_terminate())
    audit_ids.append(case5_idempotent_repeat())

    print("\n" + "=" * 60)
    print(f"所有 audit_id: {audit_ids}")
    print("可以查 workflow_log 看完整操作链")
    print("=" * 60)


if __name__ == "__main__":
    main()
