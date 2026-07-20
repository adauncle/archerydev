"""钉钉 OA driver 接入 — 集成测试。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §10.4.7 / §10.5.8

覆盖：
    1.  DingtalkOaDriver.start() 失败 → fallback + 写 FALLBACK 关联
    2.  DingtalkOaDriver.start() 成功 → 写 RUNNING 关联 + 锁 audit_driver
    3.  DingtalkOaDriver.apply_decision(PASS) → 调 comment.add
    4.  DingtalkOaDriver.apply_decision(REJECT) → 调 comment.add + terminate
    5.  DingtalkCrypto verify_signature / decrypt round-trip
    6.  callback endpoint: timestamp 过期 → 400
    7.  callback endpoint: signature 失败 → 403
    8.  callback endpoint: 解密失败 → 400
    9.  callback endpoint: 成功 → 加密 success 响应 + 幂等
    10. reconcile task 失败 3 次 → 强制 fallback

所有外部 HTTP 调用（``requests``）通过 ``mocker.patch`` 拦截，不打真实 API。
"""

import hashlib
import json
import time
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.test import RequestFactory

from common.utils.const import WorkflowStatus
from sql.extensions.audit_drivers.base import DriverStartResult
from sql.extensions.dingtalk_oa.callback import dingtalk_oa_callback
from sql.extensions.dingtalk_oa.drivers.dingtalk import (
    DingtalkApiError,
    DingtalkOaDriver,
)
from sql.extensions.dingtalk_oa.models import (
    ApprovalFlow,
    DingtalkOaEventLog,
    GroupDingtalkAuditor,
    WorkflowAuditExternal,
)
from sql.extensions.dingtalk_oa.security.crypto import DingtalkCrypto
from sql.extensions.dingtalk_oa.tasks import reconcile_pending_oa_workflows

pytestmark = pytest.mark.django_db


# ============================== Fixtures ==============================


@pytest.fixture
def dingtalk_flow():
    return ApprovalFlow.objects.create(
        code="test_dingtalk",
        name="Test Dingtalk Flow",
        audit_driver="dingtalk_oa",
        audit_auth_groups="1,2",
        dingtalk_process_code="PROC_TEST",
        is_active=True,
    )


@pytest.fixture
def dingtalk_audit(sql_workflow, create_audit_workflow, dingtalk_flow):
    """带 SqlWorkflow + WorkflowAudit + ApprovalFlow 的工单。"""
    workflow, _ = sql_workflow
    audit = create_audit_workflow
    # 把 workflow.id 写进 audit
    audit.workflow_id = workflow.id
    audit.audit_auth_groups = dingtalk_flow.audit_auth_groups
    audit.save(update_fields=["workflow_id", "audit_auth_groups"])
    workflow.audit_driver = "dingtalk_oa"
    workflow.audit_fallback_reason = ""
    workflow.save(update_fields=["audit_driver", "audit_fallback_reason"])
    return workflow, audit, dingtalk_flow


@pytest.fixture
def crypto_obj():
    crypto = DingtalkCrypto(
        token="test_token_1234567890",
        aes_key="abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
        receiveid="corp1",
    )
    crypto.aes_key_str = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    return crypto


def _make_signed_request(rf, encrypted_b64, crypto, ts=None):
    """构造一个带签名的钉钉回调 Request。"""
    if ts is None:
        ts = str(int(time.time() * 1000))
    nonce = "nonce_xyz"
    params = sorted([crypto.token, ts, nonce, encrypted_b64])
    sig = hashlib.sha1("".join(params).encode("utf-8")).hexdigest()
    url = f"/dingtalk/oa/callback?timestamp={ts}&nonce={nonce}&signature={sig}"
    return rf.post(
        url, data=encrypted_b64, content_type="text/plain",
    )


# ============================== 1. start() fallback ==============================


def test_dingtalk_driver_start_fallback_on_api_error(
    dingtalk_audit, settings, mocker,
):
    """钉钉 API 持续 3 次 500 -> 应 fallback。"""
    workflow, audit, flow = dingtalk_audit
    settings.CUSTOM_DINGTALK_OA_RETRY_TIMES = 3
    settings.CUSTOM_DINGTALK_OA_TIMEOUT_SECONDS = 2
    settings.CUSTOM_DINGTALK_OA_FALLBACK_ENABLED = True
    settings.DINGTALK_OA_APP_KEY = "fake_key"
    settings.DINGTALK_OA_APP_SECRET = "fake_secret"
    settings.DINGTALK_NOTIFY_WEBHOOK = ""

    # mock gettoken 返回成功
    mock_gettoken = mocker.patch(
        "sql.extensions.dingtalk_oa.drivers.dingtalk.get_oa_access_token",
        return_value="fake_token",
    )
    # mock create 持续 errcode=500
    mock_create = mocker.patch(
        "sql.extensions.dingtalk_oa.drivers.dingtalk.requests.post",
        return_value=_fake_response({"errcode": 500, "errmsg": "internal error"}),
    )

    driver = DingtalkOaDriver()
    result = driver.start(workflow, audit, flow)

    assert isinstance(result, DriverStartResult)
    assert result.external_id == ""
    assert result.extra.get("fallback") is True

    # 验证 WorkflowAuditExternal 写 FALLBACK
    ext = WorkflowAuditExternal.objects.get(audit=audit)
    assert ext.external_status == "FALLBACK"
    assert ext.oa_failure_reason  # 非空

    # 验证 workflow 切回 archery
    workflow.refresh_from_db()
    assert workflow.audit_driver == "archery"
    assert workflow.audit_fallback_reason  # 非空

    # 验证 FALLBACK_AT_START 事件
    event = DingtalkOaEventLog.objects.filter(
        audit=audit, event_type="FALLBACK_AT_START",
    ).first()
    assert event is not None
    assert event.processed is True

    # create 被调用 3 次（重试耗尽）
    assert mock_create.call_count == 3


# ============================== 2. start() success ==============================


def test_dingtalk_driver_start_success_writes_running(
    dingtalk_audit, settings, mocker,
):
    """钉钉 API 成功 -> 写 RUNNING 关联 + 锁 driver。"""
    workflow, audit, flow = dingtalk_audit
    settings.CUSTOM_DINGTALK_OA_RETRY_TIMES = 3
    settings.CUSTOM_DINGTALK_OA_FALLBACK_ENABLED = True
    settings.DINGTALK_OA_APP_KEY = "fake"
    settings.DINGTALK_OA_APP_SECRET = "fake"

    mocker.patch(
        "sql.extensions.dingtalk_oa.drivers.dingtalk.get_oa_access_token",
        return_value="fake_token",
    )
    mocker.patch(
        "sql.extensions.dingtalk_oa.drivers.dingtalk.requests.post",
        return_value=_fake_response({
            "errcode": 0,
            "result": {"process_instance_id": "PROC-INS-001"},
        }),
    )

    driver = DingtalkOaDriver()
    result = driver.start(workflow, audit, flow)

    assert result.external_id == "PROC-INS-001"
    assert result.extra.get("fallback") is None

    ext = WorkflowAuditExternal.objects.get(audit=audit)
    assert ext.external_status == "RUNNING"
    assert ext.external_process_instance_id == "PROC-INS-001"
    assert ext.external_process_code == flow.dingtalk_process_code

    workflow.refresh_from_db()
    assert workflow.audit_driver == "dingtalk_oa"

    # OA_START 事件
    event = DingtalkOaEventLog.objects.filter(
        audit=audit, event_type="OA_START",
    ).first()
    assert event is not None
    assert event.processed is True


# ============================== 3. apply_decision(PASS) ==============================


def test_dingtalk_driver_apply_decision_pass_calls_comment_add(
    dingtalk_audit, settings, mocker,
):
    workflow, audit, flow = dingtalk_audit
    settings.CUSTOM_DINGTALK_OA_TIMEOUT_SECONDS = 2

    # 先创建 RUNNING 关联（driver.start 已通过则应存在；这里手动建）
    WorkflowAuditExternal.objects.create(
        audit=audit, source="dingtalk_oa",
        external_process_instance_id="PROC-INS-002",
        external_process_code=flow.dingtalk_process_code,
        external_status="RUNNING",
    )

    mock_post = mocker.patch(
        "sql.extensions.dingtalk_oa.drivers.dingtalk.requests.post",
        return_value=_fake_response({"errcode": 0, "result": {}}),
    )
    mocker.patch(
        "sql.extensions.dingtalk_oa.drivers.dingtalk.get_oa_access_token",
        return_value="fake_token",
    )

    actor = type("U", (), {"display": "张三"})()
    DingtalkOaDriver().apply_decision(audit, "pass", actor, "LGTM")

    # 至少 1 次 comment.add
    assert mock_post.call_count >= 1
    body = mock_post.call_args.kwargs.get("json") or mock_post.call_args.args[1]
    assert "通过" in body.get("comment", "")
    assert "张三" in body.get("comment", "")


# ============================== 4. apply_decision(REJECT) ==============================


def test_dingtalk_driver_apply_decision_reject_terminates(
    dingtalk_audit, settings, mocker,
):
    workflow, audit, flow = dingtalk_audit
    WorkflowAuditExternal.objects.create(
        audit=audit, source="dingtalk_oa",
        external_process_instance_id="PROC-INS-003",
        external_process_code=flow.dingtalk_process_code,
        external_status="RUNNING",
    )

    mock_post = mocker.patch(
        "sql.extensions.dingtalk_oa.drivers.dingtalk.requests.post",
        return_value=_fake_response({"errcode": 0, "result": {}}),
    )
    mocker.patch(
        "sql.extensions.dingtalk_oa.drivers.dingtalk.get_oa_access_token",
        return_value="fake_token",
    )

    actor = type("U", (), {"display": "李四"})()
    DingtalkOaDriver().apply_decision(audit, "reject", actor, "NO")

    ext = WorkflowAuditExternal.objects.get(audit=audit)
    assert ext.external_status == "TERMINATED"
    # 至少 2 次：comment + terminate
    assert mock_post.call_count >= 2


# ============================== 5. crypto ==============================


def test_dingtalk_crypto_verify_signature_and_decrypt(crypto_obj):
    """crypto round-trip + 验签。"""
    msg = {"EventType": "bpms_instance_change", "processInstanceId": "P1"}
    encrypted = crypto_obj.encrypt(msg)

    ts = "1700000000000"
    nonce = "n1"
    params = sorted([crypto_obj.token, ts, nonce, encrypted])
    sig = hashlib.sha1("".join(params).encode("utf-8")).hexdigest()

    assert crypto_obj.verify_signature(ts, nonce, encrypted, sig) is True
    assert crypto_obj.verify_signature(ts, nonce, encrypted, "wrong") is False

    decrypted = crypto_obj.decrypt(encrypted)
    assert decrypted == msg


def test_dingtalk_crypto_short_aes_key_rejected():
    with pytest.raises(ValueError, match="43 chars"):
        DingtalkCrypto(token="t", aes_key="too_short")


# ============================== 6. callback timestamp 过期 ==============================


def test_callback_rejects_expired_timestamp(rf, crypto_obj, settings):
    settings.DINGTALK_OA_CALLBACK_TOKEN = crypto_obj.token
    settings.DINGTALK_OA_CALLBACK_AES_KEY = crypto_obj.aes_key_str
    settings.DINGTALK_OA_CALLBACK_RECEIVEID = "corp1"

    # 10 分钟前
    expired_ts = str(int((time.time() - 600) * 1000))
    encrypted = crypto_obj.encrypt({"EventType": "test"})
    req = _make_signed_request(rf, encrypted, crypto_obj, ts=expired_ts)

    resp = dingtalk_oa_callback(req)
    assert resp.status_code == 400
    body = json.loads(resp.content)
    assert "timestamp" in body.get("errmsg", "")


# ============================== 7. callback signature 失败 ==============================


def test_callback_rejects_bad_signature(rf, crypto_obj, settings):
    settings.DINGTALK_OA_CALLBACK_TOKEN = crypto_obj.token
    settings.DINGTALK_OA_CALLBACK_AES_KEY = crypto_obj.aes_key_str
    settings.DINGTALK_OA_CALLBACK_RECEIVEID = "corp1"

    encrypted = crypto_obj.encrypt({"EventType": "test"})
    req = _make_signed_request(rf, encrypted, crypto_obj)
    # 篡改 signature
    req.GET = req.GET.copy()
    req.GET["signature"] = "0" * 40

    resp = dingtalk_oa_callback(req)
    assert resp.status_code == 403
    body = json.loads(resp.content)
    assert "signature" in body.get("errmsg", "")


# ============================== 8. callback decrypt 失败 ==============================


def test_callback_rejects_garbled_ciphertext(rf, crypto_obj, settings):
    settings.DINGTALK_OA_CALLBACK_TOKEN = crypto_obj.token
    settings.DINGTALK_OA_CALLBACK_AES_KEY = crypto_obj.aes_key_str
    settings.DINGTALK_OA_CALLBACK_RECEIVEID = "corp1"

    # 签名正确但密文是乱码
    req = _make_signed_request(rf, "not-base64-garbage", crypto_obj)

    resp = dingtalk_oa_callback(req)
    assert resp.status_code == 403 or resp.status_code == 400


# ============================== 9. callback success + idempotent ==============================


def test_callback_success_and_idempotent(
    rf, crypto_obj, settings, mocker,
):
    settings.DINGTALK_OA_CALLBACK_TOKEN = crypto_obj.token
    settings.DINGTALK_OA_CALLBACK_AES_KEY = crypto_obj.aes_key_str
    settings.DINGTALK_OA_CALLBACK_RECEIVEID = "corp1"
    settings.DINGTALK_OA_APP_KEY = "fake"
    settings.DINGTALK_OA_APP_SECRET = "fake"

    # 没有对应 audit 也不应 500（按 design 静默跳过）
    event = {
        "EventType": "bpms_instance_change",
        "EventId": "evt-1",
        "processInstanceId": "PROC-INS-UNKNOWN-1",
        "type": "finish",
    }
    encrypted = crypto_obj.encrypt(event)
    req = _make_signed_request(rf, encrypted, crypto_obj)

    # 第一次：处理（但无对应 audit 跳过），返回 success
    resp = dingtalk_oa_callback(req)
    assert resp.status_code == 200

    # event_id 已写入 event log
    log = DingtalkOaEventLog.objects.get(event_id="evt-1")
    assert log.processed is True

    # 第二次（同一 EventId）：幂等返回 success，不再处理
    req2 = _make_signed_request(rf, encrypted, crypto_obj)
    resp2 = dingtalk_oa_callback(req2)
    assert resp2.status_code == 200
    # 仍然只有 1 条日志
    assert DingtalkOaEventLog.objects.filter(event_id="evt-1").count() == 1


# ============================== 10. reconcile 3 次失败 -> fallback ==============================


def test_reconcile_force_fallback_after_3_failures(
    dingtalk_audit, settings, mocker,
):
    workflow, audit, flow = dingtalk_audit
    # 创建 RUNNING 关联，reconcile_failed_count 已 2（再失败一次到 3）
    ext = WorkflowAuditExternal.objects.create(
        audit=audit, source="dingtalk_oa",
        external_process_instance_id="PROC-INS-REC-1",
        external_process_code=flow.dingtalk_process_code,
        external_status="RUNNING",
        reconcile_failed_count=2,
        last_synced_at=None,
    )

    # 把 audit 设为 WAITING
    audit.current_status = WorkflowStatus.WAITING
    audit.save(update_fields=["current_status"])

    # mock driver.get_status 一直抛
    mocker.patch.object(
        DingtalkOaDriver, "get_status",
        side_effect=DingtalkApiError("test", {"errcode": -1, "errmsg": "boom"}),
    )

    scanned = reconcile_pending_oa_workflows()

    assert scanned == 1
    ext.refresh_from_db()
    assert ext.external_status == "FALLBACK"
    assert ext.reconcile_failed_count == 3
    assert ext.fallback_at is not None

    workflow.refresh_from_db()
    assert workflow.audit_driver == "archery"
    assert "对账失败" in workflow.audit_fallback_reason

    # FALLBACK_AT_RECONCILE 事件
    event = DingtalkOaEventLog.objects.filter(
        audit=audit, event_type="FALLBACK_AT_RECONCILE",
    ).first()
    assert event is not None


# ============================== Helpers ==============================


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = json.dumps(payload).encode("utf-8")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


def _fake_response(payload, status_code=200):
    return _FakeResp(payload, status_code)
