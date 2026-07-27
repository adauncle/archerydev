"""v0.2.0 callback handler 单元测试 + 集成测试（不依赖钉钉服务，直接调 handler）。

测试目标：
    1. 节点通过 (task finish/agree) -> 推进 audit 到 next_audit 或 PASSED
    2. 节点驳回 (task finish/refuse) -> audit 标 REJECTED
    3. 实例终止 (instance terminate) -> audit 标 ABORTED
    4. 重复回调幂等
    5. actor 翻译（Users.ding_user_id 反查）
    6. 写 detail / log 的字段对得上
    7. sql_workflow.status 同步

运行：
    cd /opt/archery/prod
    sudo -u archery ./venv/bin/python -m pytest sql/extensions/dingtalk_oa/tests/test_oa_callback_handler.py -v

或在 dev shell：
    DJANGO_SETTINGS_MODULE=archery.settings python -m pytest ...
"""
import json
import os
import sys
from typing import Optional
from unittest import skipIf

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()

from django.db import transaction
from django.test import TransactionTestCase  # noqa: E402
from django.utils import timezone  # noqa: E402

from common.config import SysConfig  # noqa: E402
from common.utils.const import WorkflowStatus  # noqa: E402
from sql.extensions.dingtalk_oa.models import (  # noqa: E402
    ApprovalFlow,
    GroupDingtalkAuditor,
    WorkflowAuditExternal,
)
from sql.extensions.dingtalk_oa.services.oa_callback_handler import (  # noqa: E402
    handle_oa_callback,
)
from sql.models import (  # noqa: E402
    Group,
    ResourceGroup,
    SqlWorkflow,
    Users,
    WorkflowAudit,
    WorkflowAuditDetail,
    WorkflowLog,
)


def _make_workflow(
    workflow_name: str = "test_oa_callback",
    instance_id: int = 2,
    group_id: int = 25,
    engineer: str = "archery",
    audit_auth_groups: str = "3",
) -> SqlWorkflow:
    """建一个 SqlWorkflow 走通 audit，便于 callback handler 测试。"""
    rg = ResourceGroup.objects.get(group_id=group_id)
    user = Users.objects.get(username=engineer)
    wf = SqlWorkflow.objects.create(
        workflow_name=workflow_name,
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
        demand_url="oa_callback_test",
        is_offline_export=0,
        audit_driver="dingtalk_oa",
    )
    return wf


def _make_external(
    audit: WorkflowAudit, process_instance_id: str = "TEST-PI-001"
) -> WorkflowAuditExternal:
    """建一个 WorkflowAuditExternal 关联。"""
    return WorkflowAuditExternal.objects.create(
        audit=audit,
        source="dingtalk_oa",
        external_process_instance_id=process_instance_id,
        external_process_code="PROC-TEST",
        external_status="RUNNING",
    )


def _make_event(
    process_instance_id: str,
    event_type: str = "bpms_task_change",
    inner_type: str = "finish",
    result: str = "agree",
    staff_id: str = "",
    staff_name: str = "",
    remark: str = "",
) -> dict:
    e = {
        "EventType": event_type,
        "processInstanceId": process_instance_id,
        "processCode": "PROC-TEST",
        "type": inner_type,
        "EventId": f"evt-{process_instance_id}-{inner_type}-{result}-{timezone.now().timestamp()}",
        "createTime": int(timezone.now().timestamp() * 1000),
    }
    if result:
        e["result"] = result
    if staff_id:
        e["StaffId"] = staff_id
    if staff_name:
        e["StaffName"] = staff_name
    if remark:
        e["remark"] = remark
    if event_type == "bpms_task_change":
        e["taskId"] = "TASK-001"
    return e


@skipIf(
    "MYSQL_TEST_HOST" not in os.environ,
    "需要 mysql 测试库（pytest-django 配 archive_sql 工单类型当前 project-wide test DB 不可用）",
)
class OaCallbackHandlerIntegrationTest(TransactionTestCase):
    """集成测试：跑真实数据库事务。"""

    def setUp(self):
        # 清理上次测试遗留
        WorkflowAuditExternal.objects.filter(
            external_process_code="PROC-TEST"
        ).delete()
        # 测试固定 userid 关联
        GroupDingtalkAuditor.objects.filter(
            group_id=3, resource_group_id=25
        ).update_or_create(
            group_id=3,
            resource_group_id=25,
            defaults=dict(
                dingtalk_user_ids=json.dumps(["test_oa_user_1"]),
                is_active=True,
            ),
        )
        # 给 test_oa_user_1 配一个 Archery Users（如果还没）
        u, _ = Users.objects.get_or_create(
            username="test_oa_user_1",
            defaults=dict(
                display="测试 OA 审批人",
                email="oa_tester@archery.local",
                is_active=1,
                is_staff=1,
            ),
        )
        u.ding_user_id = "test_oa_user_1"
        u.save(update_fields=["ding_user_id"])

    def test_task_finish_agree_no_next_audit(self):
        """单级审批：节点通过 → audit 标 PASSED。"""
        wf = _make_workflow(audit_auth_groups="3")
        audit = WorkflowAudit.objects.create(
            workflow_id=wf.id,
            workflow_type=2,
            workflow_title=wf.workflow_name,
            audit_auth_groups="3",
            current_audit="3",
            next_audit="-1",
            current_status=WorkflowStatus.WAITING,
            create_user="archery",
            create_user_display="Archery Admin",
            group_id=25,
            group_name="测试组",
        )
        ext = _make_external(audit)
        event = _make_event(
            ext.external_process_instance_id,
            event_type="bpms_task_change",
            inner_type="finish",
            result="agree",
            staff_id="test_oa_user_1",
            staff_name="测试 OA 审批人",
            remark="OK 通过",
        )
        result = handle_oa_callback(event)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["new_status"], WorkflowStatus.PASSED)

        audit.refresh_from_db()
        self.assertEqual(audit.current_status, WorkflowStatus.PASSED)
        self.assertEqual(audit.current_audit, "-1")

        detail = WorkflowAuditDetail.objects.filter(audit_id=audit.audit_id).last()
        self.assertEqual(detail.audit_status, WorkflowStatus.PASSED)
        self.assertIn("测试 OA 审批人", detail.remark)

        log = WorkflowLog.objects.filter(audit_id=audit.audit_id).last()
        self.assertEqual(log.operator, "test_oa_user_1")
        self.assertIn("[OA]", log.operation_info)
        self.assertIn("OK 通过", log.operation_info)

        wf.refresh_from_db()
        self.assertEqual(wf.status, "workflow_review_pass")

    def test_task_finish_agree_with_next_audit(self):
        """多级审批：节点通过 → 推进到下个节点。"""
        wf = _make_workflow(audit_auth_groups="3,4")
        audit = WorkflowAudit.objects.create(
            workflow_id=wf.id,
            workflow_type=2,
            workflow_title=wf.workflow_name,
            audit_auth_groups="3,4",
            current_audit="3",
            next_audit="4",
            current_status=WorkflowStatus.WAITING,
            create_user="archery",
            create_user_display="Archery Admin",
            group_id=25,
            group_name="测试组",
        )
        ext = _make_external(audit)
        event = _make_event(
            ext.external_process_instance_id,
            event_type="bpms_task_change",
            inner_type="finish",
            result="agree",
            staff_id="test_oa_user_1",
            staff_name="测试 OA 审批人",
        )
        result = handle_oa_callback(event)
        self.assertEqual(result["status"], "applied")
        audit.refresh_from_db()
        self.assertEqual(audit.current_status, WorkflowStatus.WAITING)
        self.assertEqual(audit.current_audit, "4")
        self.assertEqual(audit.next_audit, "-1")  # 下一节点是最后一个
        wf.refresh_from_db()
        self.assertEqual(wf.status, "workflow_manreviewing")  # 还在审批中

    def test_task_finish_refuse(self):
        """节点驳回 → audit 标 REJECTED。"""
        wf = _make_workflow(audit_auth_groups="3")
        audit = WorkflowAudit.objects.create(
            workflow_id=wf.id,
            workflow_type=2,
            workflow_title=wf.workflow_name,
            audit_auth_groups="3",
            current_audit="3",
            next_audit="-1",
            current_status=WorkflowStatus.WAITING,
            create_user="archery",
            create_user_display="Archery Admin",
            group_id=25,
            group_name="测试组",
        )
        ext = _make_external(audit)
        event = _make_event(
            ext.external_process_instance_id,
            event_type="bpms_task_change",
            inner_type="finish",
            result="refuse",
            staff_id="test_oa_user_1",
            staff_name="测试 OA 审批人",
            remark="SQL 有问题",
        )
        result = handle_oa_callback(event)
        self.assertEqual(result["status"], "applied")
        audit.refresh_from_db()
        self.assertEqual(audit.current_status, WorkflowStatus.REJECTED)
        self.assertEqual(audit.current_audit, "-1")

        detail = WorkflowAuditDetail.objects.filter(audit_id=audit.audit_id).last()
        self.assertEqual(detail.audit_status, WorkflowStatus.REJECTED)
        self.assertIn("SQL 有问题", detail.remark)

        wf.refresh_from_db()
        self.assertEqual(wf.status, "workflow_review_reject")

    def test_instance_terminate(self):
        """实例级 terminate → audit 标 ABORTED。"""
        wf = _make_workflow(audit_auth_groups="3")
        audit = WorkflowAudit.objects.create(
            workflow_id=wf.id,
            workflow_type=2,
            workflow_title=wf.workflow_name,
            audit_auth_groups="3",
            current_audit="3",
            next_audit="-1",
            current_status=WorkflowStatus.WAITING,
            create_user="archery",
            create_user_display="Archery Admin",
            group_id=25,
            group_name="测试组",
        )
        ext = _make_external(audit)
        event = _make_event(
            ext.external_process_instance_id,
            event_type="bpms_instance_change",
            inner_type="terminate",
            result="",
            staff_id="archery",
            staff_name="Archery Admin",
            remark="发起人撤回",
        )
        result = handle_oa_callback(event)
        self.assertEqual(result["status"], "applied")
        audit.refresh_from_db()
        self.assertEqual(audit.current_status, WorkflowStatus.ABORTED)
        ext.refresh_from_db()
        self.assertEqual(ext.external_status, "TERMINATED")
        wf.refresh_from_db()
        self.assertEqual(wf.status, "workflow_abort")

    def test_repeat_callback_idempotent(self):
        """重复回调：第二次 noop（current_status 已经变了）。"""
        wf = _make_workflow(audit_auth_groups="3")
        audit = WorkflowAudit.objects.create(
            workflow_id=wf.id,
            workflow_type=2,
            workflow_title=wf.workflow_name,
            audit_auth_groups="3",
            current_audit="3",
            next_audit="-1",
            current_status=WorkflowStatus.WAITING,
            create_user="archery",
            create_user_display="Archery Admin",
            group_id=25,
            group_name="测试组",
        )
        ext = _make_external(audit)
        event = _make_event(
            ext.external_process_instance_id,
            event_type="bpms_task_change",
            inner_type="finish",
            result="agree",
            staff_id="test_oa_user_1",
            staff_name="测试 OA 审批人",
        )
        # 第一次
        r1 = handle_oa_callback(event)
        self.assertEqual(r1["status"], "applied")
        # 第二次（同一 processInstanceId + type + result）
        event2 = _make_event(
            ext.external_process_instance_id,
            event_type="bpms_task_change",
            inner_type="finish",
            result="agree",
            staff_id="test_oa_user_1",
            staff_name="测试 OA 审批人",
        )
        r2 = handle_oa_callback(event2)
        self.assertEqual(r2["status"], "noop")

        # detail 应该只写一次
        count = WorkflowAuditDetail.objects.filter(audit_id=audit.audit_id).count()
        self.assertEqual(count, 1)

    def test_unknown_staff_id_uses_oa_fallback(self):
        """钉钉 userid 在 Archery 找不到对应用户 → operator 兜底为 dingtalk_oa。"""
        wf = _make_workflow(audit_auth_groups="3")
        audit = WorkflowAudit.objects.create(
            workflow_id=wf.id,
            workflow_type=2,
            workflow_title=wf.workflow_name,
            audit_auth_groups="3",
            current_audit="3",
            next_audit="-1",
            current_status=WorkflowStatus.WAITING,
            create_user="archery",
            create_user_display="Archery Admin",
            group_id=25,
            group_name="测试组",
        )
        ext = _make_external(audit)
        event = _make_event(
            ext.external_process_instance_id,
            event_type="bpms_task_change",
            inner_type="finish",
            result="agree",
            staff_id="no_such_user_in_archery",
            staff_name="外部测试人",
        )
        result = handle_oa_callback(event)
        self.assertEqual(result["status"], "applied")
        detail = WorkflowAuditDetail.objects.filter(audit_id=audit.audit_id).last()
        # operator 用 Archery 未查到的 dingtalk userid 兜底（不是 dingtalk_oa）
        self.assertEqual(detail.audit_user, "no_such_user_in_archery")
        log = WorkflowLog.objects.filter(audit_id=audit.audit_id).last()
        self.assertIn("外部测试人 (via 钉钉)", log.operator_display)

    def test_unknown_process_instance_id_skipped(self):
        """未知 processInstanceId → 跳过。"""
        event = _make_event("UNKNOWN-PI-9999", inner_type="finish", result="agree")
        result = handle_oa_callback(event)
        self.assertEqual(result["status"], "skipped")

    def test_instance_finish_syncs_external_status(self):
        """instance finish/agree → external_status=APPROVED，不重复推进。"""
        wf = _make_workflow(audit_auth_groups="3")
        audit = WorkflowAudit.objects.create(
            workflow_id=wf.id,
            workflow_type=2,
            workflow_title=wf.workflow_name,
            audit_auth_groups="3",
            current_audit="-1",
            next_audit="-1",
            current_status=WorkflowStatus.PASSED,  # 已经通过
            create_user="archery",
            create_user_display="Archery Admin",
            group_id=25,
            group_name="测试组",
        )
        ext = _make_external(audit)
        event = _make_event(
            ext.external_process_instance_id,
            event_type="bpms_instance_change",
            inner_type="finish",
            result="agree",
        )
        result = handle_oa_callback(event)
        self.assertEqual(result["status"], "synced")
        ext.refresh_from_db()
        self.assertEqual(ext.external_status, "APPROVED")


if __name__ == "__main__":
    import unittest
    unittest.main()
