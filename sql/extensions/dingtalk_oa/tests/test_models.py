"""模型基础测试。

覆盖 7 个新模型的核心字段与基础关系。
"""

import pytest

from sql.extensions.dingtalk_oa.models import (
    ApprovalFlow,
    ApprovalPolicy,
    CoreBusinessTable,
    DingtalkOaEventLog,
    GroupDingtalkAuditor,
    SqlTypeRegistry,
    WorkflowAuditExternal,
)


@pytest.mark.django_db
def test_sql_type_registry_creation():
    obj = SqlTypeRegistry.objects.create(
        code="TEST_INSERT",
        category="DML",
        description="test insert",
        pattern=r"^\s*TEST_INSERT\b",
        default_severity="low",
    )
    assert obj.code == "TEST_INSERT"
    assert obj.is_active is True
    assert obj.is_critical is False
    assert obj.has_affected_rows is True
    assert str(obj) == "TEST_INSERT (DML)"


@pytest.mark.django_db
def test_sql_type_registry_defaults():
    obj = SqlTypeRegistry.objects.create(
        code="X",
        category="DQL",
        description="x",
        pattern="X",
        default_severity="low",
    )
    # 显式不传的字段
    assert obj.has_affected_rows is True
    assert obj.is_critical is False
    assert obj.is_active is True


@pytest.mark.django_db
def test_approval_flow_creation():
    flow = ApprovalFlow.objects.create(
        code="test_flow",
        name="Test Flow",
        audit_driver="archery",
        audit_auth_groups="1,2,3",
    )
    assert flow.code == "test_flow"
    assert flow.audit_auth_groups == "1,2,3"
    assert flow.dingtalk_process_code == ""
    assert flow.is_active is True
    assert str(flow).startswith("test_flow")


@pytest.mark.django_db
def test_approval_policy_creation_and_ordering():
    flow = ApprovalFlow.objects.create(
        code="f", name="F", audit_driver="archery", audit_auth_groups="1",
    )
    p_low = ApprovalPolicy.objects.create(
        name="low", priority=1, is_enabled=True, flow=flow,
    )
    p_high = ApprovalPolicy.objects.create(
        name="high", priority=99, is_enabled=True, flow=flow,
    )

    ordered = list(ApprovalPolicy.objects.all())
    # Meta.ordering = ["-priority"]
    assert ordered[0].pk == p_high.pk
    assert ordered[1].pk == p_low.pk


@pytest.mark.django_db
def test_approval_policy_flow_protect(db_instance):
    """flow 被引用时，删除应被 PROTECT 阻止。"""
    flow = ApprovalFlow.objects.create(
        code="protected", name="P", audit_driver="archery", audit_auth_groups="1",
    )
    ApprovalPolicy.objects.create(
        name="uses_protected", priority=10, is_enabled=True, flow=flow,
    )
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        flow.delete()


@pytest.mark.django_db
def test_approval_policy_sql_types_m2m(db_instance):
    flow = ApprovalFlow.objects.create(
        code="f2", name="F2", audit_driver="archery", audit_auth_groups="1",
    )
    insert_type = SqlTypeRegistry.objects.create(
        code="INSERT_TEST", category="DML", description="i",
        pattern=r"INSERT", default_severity="low",
    )
    drop_type = SqlTypeRegistry.objects.create(
        code="DROP_TEST", category="DDL", description="d",
        pattern=r"DROP", default_severity="high", is_critical=True,
    )
    policy = ApprovalPolicy.objects.create(
        name="m2m_test", priority=10, is_enabled=True, flow=flow,
    )
    policy.sql_types.set([insert_type, drop_type])
    assert policy.sql_types.count() == 2
    assert set(policy.sql_types.values_list("code", flat=True)) == {"INSERT_TEST", "DROP_TEST"}


@pytest.mark.django_db
def test_core_business_table_unique_together(db_instance):
    CoreBusinessTable.objects.create(
        instance=db_instance, db_name="d1", table_name="t1",
        level="L1", created_by="tester",
    )
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        CoreBusinessTable.objects.create(
            instance=db_instance, db_name="d1", table_name="t1",
            level="L2", created_by="tester",
        )


@pytest.mark.django_db
def test_group_dingtalk_auditor_unique_together(create_auth_group):
    GroupDingtalkAuditor.objects.create(
        group=create_auth_group,
        dingtalk_user_ids='["u1","u2"]',
    )
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        GroupDingtalkAuditor.objects.create(
            group=create_auth_group,
            dingtalk_user_ids='["u3"]',
        )


@pytest.mark.django_db
def test_workflow_audit_external_payload_default():
    """JSONField 的 default=dict 必须能 dump/load。"""
    # 不直接挂 audit（要 mock SqlWorkflow），仅验证 default 行为
    obj = WorkflowAuditExternal()
    assert obj.payload == {}
    assert obj.reconcile_failed_count == 0
    assert obj.oa_failure_reason == ""


@pytest.mark.django_db
def test_dingtalk_oa_event_log_defaults():
    obj = DingtalkOaEventLog()
    assert obj.processed is False
    assert obj.error == ""
    assert obj.payload == {}
    assert obj.event_id  # 字段定义存在
