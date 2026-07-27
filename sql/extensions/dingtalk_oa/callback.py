"""钉钉 OA 回调 endpoint。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §10.5.1-§10.5.3

URL：``/dingtalk/oa/callback``（mount 在 ``archery/urls.py`` 中）。

完整处理流程（v0.7 §10.5.1）：

    0.  IP 黑名单 → 403
    1.  timestamp 校验（5 分钟窗口）→ 400
    2.  SHA1 验签 → 403 + 失败计数
    3.  AES-256-CBC 解密 → 400
    4.  幂等性检查（event_id）→ 重复事件直接返回 success
    5.  业务处理（路由到 AuditV2 / 写日志）→ 500
    6.  返回加密的 success 响应
"""

import hashlib
import json
import logging
import time
from typing import Optional

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import DingtalkOaEventLog, WorkflowAuditExternal
from .security.crypto import DingtalkCrypto
from .security.guard import (
    is_banned,
    record_signature_failure,
    verify_auditor_permission,
)

logger = logging.getLogger(__name__)

# 钉钉 timestamp 5 分钟窗口
TIMESTAMP_TOLERANCE_MS = 5 * 60 * 1000

# 事件 payload 脱敏关键字
_SENSITIVE_KEYS = {"password", "passwd", "secret", "token", "access_key", "api_key"}


# ============================== 入口 ==============================


@csrf_exempt
@require_POST
def dingtalk_oa_callback(request: HttpRequest):
    """钉钉 OA 回调 endpoint（v0.7 §10.5.1）。

    公开 POST 接口，**不**要求登录（钉钉服务器调用），但：
        * IP 黑名单（cache 标记）
        * timestamp 5 分钟窗口
        * SHA1 签名
        * AES-256-CBC 解密
        * 事件幂等（event_id）
    """
    client_ip = _get_client_ip(request)

    # 0) IP 黑名单
    if is_banned(client_ip):
        logger.warning("dingtalk callback from banned ip=%s", client_ip)
        return JsonResponse({"errcode": 1, "errmsg": "banned"}, status=403)

    # 1) timestamp 校验
    timestamp = request.GET.get("timestamp", "")
    nonce = request.GET.get("nonce", "")
    signature = request.GET.get("signature", "")
    if not _validate_timestamp(timestamp):
        logger.warning(
            "dingtalk callback invalid timestamp ip=%s ts=%s",
            client_ip, timestamp,
        )
        return JsonResponse(
            {"errcode": 1, "errmsg": "invalid timestamp"}, status=400,
        )

    # 2) 验签
    try:
        crypto = _get_crypto()
    except ValueError as e:
        logger.error("dingtalk crypto init failed: %s", e)
        return JsonResponse(
            {"errcode": 1, "errmsg": "crypto not configured"}, status=500,
        )

    try:
        encrypted_b64 = request.body.decode("utf-8")
    except UnicodeDecodeError:
        return JsonResponse(
            {"errcode": 1, "errmsg": "body not utf-8"}, status=400,
        )

    if not crypto.verify_signature(timestamp, nonce, encrypted_b64, signature):
        record_signature_failure(client_ip)
        return JsonResponse(
            {"errcode": 1, "errmsg": "signature invalid"}, status=403,
        )

    # 3) AES 解密
    try:
        event = crypto.decrypt(encrypted_b64)
    except Exception as e:  # noqa: BLE001
        logger.exception("dingtalk callback decrypt failed: %s", e)
        return JsonResponse(
            {"errcode": 1, "errmsg": "decrypt failed"}, status=400,
        )

    # 4) 幂等性
    event_id = str(event.get("EventId") or event.get("eventId") or "")
    if not event_id:
        # 钉钉总会给 EventId；缺失时用 hash 兜底
        event_id = _fallback_event_id(event)

    if event_id and DingtalkOaEventLog.objects.filter(
        event_id=event_id, processed=True,
    ).exists():
        logger.info("dingtalk callback duplicate event_id=%s, skip", event_id)
        return _make_encrypted_response(crypto, "success")

    # 5) 业务处理
    try:
        _handle_event(event, signature=signature, raw_encrypted=encrypted_b64)
    except Exception as e:  # noqa: BLE001
        logger.exception("handle dingtalk event failed: %s", e)
        # 记失败事件，便于排错
        DingtalkOaEventLog.objects.create(
            audit=None,
            event_id=event_id or "",
            event_type=str(event.get("EventType") or event.get("eventType") or "unknown"),
            payload=_sanitize_payload(event),
            processed=False, error=str(e)[:1000],
            raw_payload_encrypted=encrypted_b64[:1000],
            signature=signature,
        )
        return JsonResponse(
            {"errcode": 1, "errmsg": "internal error"}, status=500,
        )

    # 6) 记成功日志 + 返回加密响应
    DingtalkOaEventLog.objects.create(
        audit=None,
        event_id=event_id or "",
        event_type=str(event.get("EventType") or event.get("eventType") or "unknown"),
        payload=_sanitize_payload(event),
        processed=True,
        raw_payload_encrypted=encrypted_b64[:1000],
        signature=signature,
    )
    return _make_encrypted_response(crypto, "success")


# ============================== 业务处理 ==============================


def _handle_event(event: dict, signature: str, raw_encrypted: str) -> None:
    """处理解密后的事件。

    v0.2.0 改动：把核心业务处理委托给
    :func:`sql.extensions.dingtalk_oa.services.oa_callback_handler.handle_oa_callback`，
    后者真正推进 ``workflow_audit`` / 写 ``workflow_audit_detail`` / 写 ``workflow_log`` /
    更新 ``sql_workflow.status``。本函数保留审批人白名单校验和审计人解析。

    事件类型（v0.7 §10.4.2）：
        * ``bpms_instance_change`` 流程实例状态变更
        * ``bpms_task_change``      任务（节点）状态变更
    """
    from .services.oa_callback_handler import handle_oa_callback

    process_instance_id = (
        event.get("processInstanceId")
        or event.get("ProcessInstanceId")
        or ""
    )
    if not process_instance_id:
        logger.info("dingtalk event without processInstanceId, skip: %s", event)
        return

    # 提前查 ext 仅为审批人白名单校验（handler 内部也会查）
    try:
        ext = WorkflowAuditExternal.objects.select_related("audit").get(
            external_process_instance_id=process_instance_id,
        )
    except WorkflowAuditExternal.DoesNotExist:
        logger.warning(
            "dingtalk event for unknown process_instance_id=%s",
            process_instance_id,
        )
        return

    audit = ext.audit
    if audit is None:
        return

    # 审批人白名单（仅 task 级事件有 staffId）
    dingtalk_userid = (
        event.get("StaffId")
        or event.get("staffId")
        or event.get("userId")
        or ""
    )
    if dingtalk_userid:
        try:
            verify_auditor_permission(
                audit, dingtalk_userid, decision=event.get("type", ""),
            )
        except Exception:  # noqa: BLE001
            # verify_auditor_permission 已记告警；这里静默返回即可
            return

    # 真正推进本地 audit
    try:
        result = handle_oa_callback(event)
        logger.info(
            "dingtalk OA callback processed: processInstanceId=%s result=%s",
            process_instance_id, result,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "handle_oa_callback failed for processInstanceId=%s", process_instance_id,
        )


# ============================== 辅助 ==============================


def _get_crypto() -> DingtalkCrypto:
    """从 settings 构造 DingtalkCrypto。"""
    token = getattr(settings, "DINGTALK_OA_CALLBACK_TOKEN", "")
    aes_key = getattr(settings, "DINGTALK_OA_CALLBACK_AES_KEY", "")
    receiveid = getattr(settings, "DINGTALK_OA_CALLBACK_RECEIVEID", "") or ""
    if not token or not aes_key:
        raise ValueError("DINGTALK_OA_CALLBACK_TOKEN/AES_KEY 未配置")
    return DingtalkCrypto(token=token, aes_key=aes_key, receiveid=receiveid)


def _validate_timestamp(timestamp: str) -> bool:
    """5 分钟窗口（v0.7 §10.5.1）。"""
    if not timestamp:
        return False
    try:
        ts_ms = int(timestamp)
    except (TypeError, ValueError):
        return False
    return abs(time.time() * 1000 - ts_ms) <= TIMESTAMP_TOLERANCE_MS


def _get_client_ip(request: HttpRequest) -> str:
    """从 X-Forwarded-For 头取真实 IP（兼容反代）。"""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    real_ip = request.META.get("HTTP_X_REAL_IP", "")
    if real_ip:
        return real_ip.strip()
    return request.META.get("REMOTE_ADDR", "")


def _make_encrypted_response(crypto: DingtalkCrypto, text: str) -> JsonResponse:
    """把响应也加密（钉钉要求）。"""
    encrypted = crypto.encrypt({"errcode": 0, "errmsg": text})
    # JsonResponse 默认 safe=True（只接受 dict），dict 本身 OK
    return JsonResponse(encrypted, safe=False)


def _sanitize_payload(payload: dict) -> dict:
    """事件 payload 脱敏后入库（v0.7 §10.5.4）。"""
    try:
        sanitized = json.loads(json.dumps(payload))
    except (TypeError, ValueError):
        return {}
    for key in list(sanitized.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            sanitized[key] = "***REDACTED***"
    return sanitized


def _fallback_event_id(event: dict) -> str:
    """无 EventId 时用 payload hash 兜底，保证幂等。"""
    try:
        canonical = json.dumps(event, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        canonical = repr(event)
    return "fallback-" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _now():
    from django.utils import timezone
    return timezone.now()
