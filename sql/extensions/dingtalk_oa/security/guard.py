"""钉钉 OA 回调安全防护：限流 / IP 封禁 / 审批人白名单 / 安全告警。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §10.5.3 / §10.5.7

公开 API：
    * ``record_signature_failure(ip)``       签名失败计数 + 阈值封禁
    * ``is_banned(ip) -> bool``               IP 是否在黑名单
    * ``verify_auditor_permission(audit, userid, decision)``  钉钉 userid 必须在白名单
    * ``get_dept_users(dept_id) -> set``      部门下 userid 集合（缓存 1 小时）
    * ``notify_security_alert(event_type, payload, severity)``  推钉钉群 + 记日志

所有「副作用」（推 webhook / 拉 API）都吃掉异常，不向上抛——安全告警
不能因为发不出去就把主业务挂掉。
"""

import json
import logging
from typing import Set

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied

logger = logging.getLogger(__name__)


# ============================== 配置 ==============================

# 这些常量来自 v0.7 §10.5.7；阈值调整请改这里
SIGNATURE_FAIL_THRESHOLD = 10   # 累计失败达此数 -> 自动封禁
SIGNATURE_WARN_THRESHOLD = 3    # 累计失败达此数 -> warning 告警
SIGNATURE_BAN_SECONDS = 3600    # 封禁时长（秒）= 60 分钟


# ============================== IP 限流 ==============================


def record_signature_failure(ip: str) -> None:
    """签名失败计数 + 阈值封禁 + 告警。

    失败计数缓存在 ``dingtalk_sig_fail:{ip}``；封禁标记在
    ``dingtalk_banned:{ip}``。两者都设置 ``ban_seconds`` TTL。
    """
    if not ip:
        return
    fail_key = f"dingtalk_sig_fail:{ip}"
    try:
        count = int(cache.get(fail_key, 0)) + 1
    except (TypeError, ValueError):
        count = 1
    cache.set(fail_key, count, timeout=SIGNATURE_BAN_SECONDS)

    if count >= SIGNATURE_FAIL_THRESHOLD:
        cache.set(f"dingtalk_banned:{ip}", True, timeout=SIGNATURE_BAN_SECONDS)
        logger.warning(
            "dingtalk signature failures reached threshold for ip=%s count=%s, banned",
            ip, count,
        )
        notify_security_alert(
            "ip_banned_after_repeated_signature_failure",
            {"ip": ip, "failure_count": count, "ban_seconds": SIGNATURE_BAN_SECONDS},
            severity="critical",
        )
    elif count >= SIGNATURE_WARN_THRESHOLD:
        notify_security_alert(
            "repeated_signature_failure",
            {"ip": ip, "failure_count": count},
            severity="warning",
        )


def is_banned(ip: str) -> bool:
    """IP 是否在黑名单中。"""
    if not ip:
        return False
    try:
        return bool(cache.get(f"dingtalk_banned:{ip}", False))
    except Exception:  # noqa: BLE001
        return False


# ============================== 审批人白名单 ==============================


def verify_auditor_permission(audit, dingtalk_userid: str, decision: str) -> None:
    """钉钉推送的审批人必须在 ``GroupDingtalkAuditor`` 中。

    Args:
        audit: ``sql.models.WorkflowAudit`` 实例，``current_audit`` 是
            当前审批节点（组 ID）。
        dingtalk_userid: 钉钉回调推送的 userid。
        decision: ``"pass"`` / ``"reject"``，仅记日志用。

    Raises:
        PermissionDenied: 当前节点未配置审批人 / 钉钉 userid 不在白名单。
    """
    # 缺省允许通过（空 userid）—— 钉钉某些事件不带审批人
    if not dingtalk_userid:
        logger.debug("dingtalk callback without userid, skip permission check")
        return

    # 延迟 import 避免 settings 未就绪
    from ..models import GroupDingtalkAuditor

    current_group_id = _safe_int(audit.current_audit)
    if current_group_id is None:
        raise PermissionDenied(
            f"无法解析 current_audit={audit.current_audit!r}，拒绝操作"
        )

    try:
        auditor = GroupDingtalkAuditor.objects.get(
            group_id=current_group_id, is_active=True,
        )
    except GroupDingtalkAuditor.DoesNotExist:
        notify_security_alert(
            "auditor_unconfigured",
            {"group_id": current_group_id, "audit_id": getattr(audit, "audit_id", None)},
            severity="critical",
        )
        raise PermissionDenied(
            f"当前审批节点 group_id={current_group_id} 未配置钉钉审批人"
        )

    # 合并 userid 白名单 + 部门下所有成员
    allowed: Set[str] = set()
    try:
        allowed.update(json.loads(auditor.dingtalk_user_ids or "[]"))
    except (ValueError, TypeError):
        logger.warning(
            "group %s dingtalk_user_ids 解析失败: %r",
            current_group_id, auditor.dingtalk_user_ids,
        )

    if auditor.dingtalk_dept_id:
        try:
            allowed.update(get_dept_users(auditor.dingtalk_dept_id))
        except Exception:  # noqa: BLE001
            # 拉部门成员失败不应阻塞业务，记告警
            logger.exception("get_dept_users(%s) failed", auditor.dingtalk_dept_id)
            notify_security_alert(
                "get_dept_users_failed",
                {"dept_id": auditor.dingtalk_dept_id},
                severity="warning",
            )

    if dingtalk_userid not in allowed:
        notify_security_alert(
            "unauthorized_auditor",
            {
                "dingtalk_userid": dingtalk_userid,
                "audit_id": getattr(audit, "audit_id", None),
                "group_id": current_group_id,
                "decision": decision,
            },
            severity="critical",
        )
        raise PermissionDenied(
            f"钉钉用户 {dingtalk_userid} 在 group_id={current_group_id} 无审批权限"
        )


def get_dept_users(dept_id: str) -> Set[str]:
    """从钉钉拉部门下所有 userid（缓存 1 小时）。

    Returns:
        userid 集合。调用方不应假设非空（API 失败/部门不存在返回空集）。

    Raises:
        RuntimeError: 配置缺失时（``DINGTALK_OA_APP_KEY/SECRET`` 都没设）。
    """
    cache_key = f"dingtalk_dept_users:{dept_id}"
    try:
        cached = cache.get(cache_key)
    except Exception:  # noqa: BLE001
        cached = None
    if cached is not None:
        return set(cached)

    token = _get_oa_access_token()
    if not token:
        logger.warning("OA access_token unavailable, skip get_dept_users(%s)", dept_id)
        return set()

    url = (
        f"https://oapi.dingtalk.com/topapi/v2/user/getDeptMemberUserList"
        f"?access_token={token}&dept_id={dept_id}"
    )
    try:
        resp = requests.post(url, json={}, timeout=10).json()
    except Exception as e:  # noqa: BLE001
        logger.exception("get_dept_users(%s) request failed: %s", dept_id, e)
        return set()

    if resp.get("errcode") not in (0, None):
        logger.warning("get_dept_users(%s) dingtalk errcode=%s", dept_id, resp.get("errcode"))
        return set()

    # v2 返回 {"result": {"userid_list": [...]}}；v1 旧接口返回 {"userIds": [...]}
    userids = []
    result = resp.get("result") or {}
    if isinstance(result, dict):
        userids = result.get("userid_list") or result.get("userIds") or []
    elif isinstance(result, list):
        userids = result

    userids = [str(u) for u in userids if u]
    try:
        cache.set(cache_key, userids, timeout=3600)
    except Exception:  # noqa: BLE001
        pass
    return set(userids)


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ============================== Token 缓存 ==============================


def get_oa_access_token() -> str:
    """拉 OA 应用 access_token，缓存到 ``dingtalk_oa_access_token``。

    注意：与上游 ``common.utils.ding_api.get_access_token``（用 SysConfig
    的 ding_app_key/ding_app_secret）不同——OA 应用是独立的
    ``DINGTALK_OA_APP_KEY`` / ``DINGTALK_OA_APP_SECRET``。

    供 DingtalkOaDriver 和本模块的 ``get_dept_users`` 共享。
    """
    try:
        token = cache.get("dingtalk_oa_access_token")
    except Exception:  # noqa: BLE001
        token = None
    if token:
        return str(token)

    app_key = getattr(settings, "DINGTALK_OA_APP_KEY", "")
    app_secret = getattr(settings, "DINGTALK_OA_APP_SECRET", "")
    if not app_key or not app_secret:
        logger.error("DINGTALK_OA_APP_KEY/SECRET 未配置")
        return ""

    try:
        resp = requests.get(
            "https://oapi.dingtalk.com/gettoken",
            params={"appkey": app_key, "appsecret": app_secret},
            timeout=5,
        ).json()
    except Exception as e:  # noqa: BLE001
        logger.exception("gettoken request failed: %s", e)
        return ""

    if resp.get("errcode") != 0:
        logger.error("gettoken failed: %s", resp)
        return ""

    token = resp.get("access_token", "")
    expires_in = int(resp.get("expires_in", 7200))
    # 提前 60s 过期，避免边界 race
    try:
        cache.set("dingtalk_oa_access_token", token, timeout=max(expires_in - 60, 60))
    except Exception:  # noqa: BLE001
        pass
    return token


# 内部别名，向后兼容旧代码
_get_oa_access_token = get_oa_access_token


# ============================== 安全告警 ==============================


def notify_security_alert(event_type: str, payload: dict, severity: str = "warning") -> None:
    """安全告警：推钉钉群（用 DINGTALK_NOTIFY_WEBHOOK） + 记 logger。

    严重事件（severity=critical）也会写 logger.error 方便 ELK 检索。
    告警发送失败不影响主业务。
    """
    log_fn = logger.error if severity == "critical" else logger.warning
    log_fn("dingtalk security alert [%s] %s: %s", severity, event_type, payload)

    webhook = getattr(settings, "DINGTALK_NOTIFY_WEBHOOK", "")
    if not webhook:
        return

    msg = f"[{severity.upper()}] 钉钉安全事件：{event_type}\n详情：{payload}"
    try:
        requests.post(
            webhook,
            json={"msgtype": "text", "text": {"content": msg[:3800]}},
            timeout=5,
        )
    except Exception:  # noqa: BLE001
        logger.exception("send security alert to dingtalk webhook failed")
