"""钉钉 OA 审批回调 -> 本地 workflow_audit 状态推进。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §10.5.2

事件 schema（钉钉官方）：
    {
        "EventType": "bpms_task_change" | "bpms_instance_change" | ...,
        "processInstanceId": "...",
        "processCode": "PROC-XXX",
        "type": "start" | "finish" | "terminate" | ...,
        "result": "agree" | "refuse" | ... (only when type=finish),
        "taskId": "..." (节点 ID),
        "StaffId": "..."  (钉钉 userid, 仅 task 事件),
        "StaffName": "...",
        "createTime": 1234567890,
        "remark": "..." (审批意见, 仅 finish)
    }

推进策略：
    * ``bpms_task_change`` + ``finish/agree``:
        推进 audit 到 next_audit；无下级 -> WorkflowStatus.PASSED
    * ``bpms_task_change`` + ``finish/refuse``:
        audit 标 WorkflowStatus.REJECTED
    * ``bpms_instance_change`` + ``finish``:
        同步 final external_status (RUNNING/APPROVED/REJECTED)；
        不重复推进本地 audit (重复事件已由 callback 顶层幂等拦)
    * ``bpms_instance_change`` + ``terminate/abort``:
        同步 external_status=TERMINATED, 本地 audit 标 ABORTED

actor 处理：钉钉 staffId (userid) 翻译为 Archery Users（按 Users.ding_user_id 反查）；
            翻译不到就用 ``dingtalk_oa`` 兜底。
"""
import logging
from typing import Optional

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("default")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def handle_oa_callback(event: dict) -> dict:
    """把钉钉事件映射到本地 workflow_audit 状态变更。

    Returns:
        dict, e.g. ``{"status": "applied", "audit_id": 4612, "new_status": "PASSED"}``
        失败 / 未知事件返回 ``{"status": "skipped", "reason": "..."}``
    """
    process_instance_id = (
        event.get("processInstanceId")
        or event.get("ProcessInstanceId")
        or ""
    )
    if not process_instance_id:
        return {"status": "skipped", "reason": "no processInstanceId"}

    # 延迟 import 避免循环
    from sql.models import WorkflowAudit
    from sql.extensions.dingtalk_oa.models import WorkflowAuditExternal

    try:
        ext = WorkflowAuditExternal.objects.select_related("audit").get(
            external_process_instance_id=process_instance_id
        )
    except WorkflowAuditExternal.DoesNotExist:
        logger.warning(
            "OA callback for unknown process_instance_id=%s, skip",
            process_instance_id,
        )
        return {"status": "skipped", "reason": "unknown process_instance_id"}

    audit = ext.audit
    if audit is None or audit.workflow_id is None:
        logger.warning(
            "OA callback: external %s has no audit/workflow, skip",
            ext.id,
        )
        return {"status": "skipped", "reason": "no audit"}

    event_type = _norm(event.get("EventType") or event.get("eventType"))
    inner_type = _norm(event.get("type")).lower()
    result = _norm(event.get("result")).lower()
    activity_id = (
        event.get("taskId") or event.get("activityId") or ""
    )

    ext.last_synced_at = timezone.now()
    if activity_id:
        ext.current_external_node = activity_id

    # ---------- 节点级（task 事件）推进本地 audit ----------
    if event_type == "bpms_task_change":
        if inner_type == "finish":
            if result == "agree":
                return _apply_node_pass(ext, event)
            if result == "refuse":
                return _apply_node_reject(ext, event)
        if inner_type == "start":
            # 节点开始：仅记录，不推进
            ext.external_status = "RUNNING"
            ext.save(update_fields=["external_status", "last_synced_at", "current_external_node"])
            return {"status": "noop", "reason": "task start, no advance"}
        # 其他 type（redirect/cc 等）暂不处理
        ext.save(update_fields=["last_synced_at", "current_external_node"])
        return {"status": "noop", "reason": f"task {inner_type}"}

    # ---------- 实例级（instance 事件）只同步终态，不重复推进 ----------
    if event_type == "bpms_instance_change":
        if inner_type == "finish":
            ext.external_status = "APPROVED" if result == "agree" else "REJECTED"
            ext.save(update_fields=["external_status", "last_synced_at"])
            return {"status": "synced", "external_status": ext.external_status}
        if inner_type in ("terminate", "abort"):
            ext.external_status = "TERMINATED"
            ext.save(update_fields=["external_status", "last_synced_at"])
            return _apply_abort(ext, event)

    return {"status": "noop", "reason": f"unhandled event_type={event_type} type={inner_type}"}


# ---------------------------------------------------------------------------
# 节点级操作
# ---------------------------------------------------------------------------


def _apply_node_pass(ext, event: dict) -> dict:
    """task finish/agree: 推进 audit 到 next_audit 或 PASSED。"""
    from django.contrib.auth.models import Group
    from sql.models import (
        SqlWorkflow,
        WorkflowAudit,
        WorkflowAuditDetail,
        WorkflowLog,
    )
    from common.utils.const import WorkflowAction, WorkflowStatus

    audit = ext.audit
    actor_label = _resolve_actor_label(event)
    remark = _norm(event.get("remark") or event.get("comment") or "")

    with transaction.atomic():
        # 重新读 audit 加 select_for_update 防并发推进
        audit_locked = WorkflowAudit.objects.select_for_update().get(
            audit_id=audit.audit_id
        )
        if audit_locked.current_status != WorkflowStatus.WAITING:
            # 已推进（重复回调 / 上游已改）
            ext.save(update_fields=["last_synced_at", "current_external_node"])
            return {
                "status": "noop",
                "reason": f"audit current_status={audit_locked.current_status}, skip",
            }

        # 决定 current_audit / next_audit / current_status
        next_audit_raw = _norm(audit_locked.next_audit)
        if not next_audit_raw or next_audit_raw == "-1":
            # 无下一级：完成
            audit_locked.current_audit = "-1"
            audit_locked.current_status = WorkflowStatus.PASSED
        else:
            # 推进到 next_audit
            audit_locked.current_audit = next_audit_raw
            # 找下下级
            audit_locked.next_audit = _calc_next_audit(audit_locked, next_audit_raw)
            audit_locked.current_status = WorkflowStatus.WAITING
        audit_locked.save()

        # 写 detail
        WorkflowAuditDetail.objects.create(
            audit_id=audit_locked.audit_id,
            audit_user=actor_label["operator"],
            audit_status=WorkflowStatus.PASSED,
            audit_time=timezone.now(),
            remark=actor_label["remark_prefix"] + remark,
        )

        # 写 workflow_log
        if audit_locked.current_audit == "-1":
            next_info = "无下级审批"
        else:
            next_info = f"下级审批: {_group_name(audit_locked.current_audit)}"
        WorkflowLog.objects.create(
            audit_id=audit_locked.audit_id,
            operation_type=WorkflowAction.PASS,
            operation_type_desc=WorkflowAction.PASS.label,
            operation_info=(
                f"[OA] {actor_label['operator_display']} 通过: "
                f"{remark or '(无备注)'}, {next_info}"
            ),
            operator=actor_label["operator"],
            operator_display=actor_label["operator_display"],
        )

        # 同步 sql_workflow 状态
        if audit_locked.current_status == WorkflowStatus.PASSED:
            SqlWorkflow.objects.filter(id=audit_locked.workflow_id).update(
                status="workflow_review_pass"
            )
            # 触发审批通过后续通知
            _trigger_post_pass_notify(audit_locked)

    ext.save(update_fields=["last_synced_at", "current_external_node"])

    logger.info(
        "OA node PASS: audit=%s -> status=%s current_audit=%s by %s",
        audit_locked.audit_id,
        audit_locked.current_status,
        audit_locked.current_audit,
        actor_label["operator_display"],
    )
    return {
        "status": "applied",
        "audit_id": audit_locked.audit_id,
        "new_status": audit_locked.current_status,
        "current_audit": audit_locked.current_audit,
    }


def _apply_node_reject(ext, event: dict) -> dict:
    """task finish/refuse: audit 标 REJECTED。"""
    from sql.models import (
        SqlWorkflow,
        WorkflowAudit,
        WorkflowAuditDetail,
        WorkflowLog,
    )
    from common.utils.const import WorkflowStatus

    audit = ext.audit
    actor_label = _resolve_actor_label(event)
    remark = _norm(event.get("remark") or event.get("comment") or "")

    with transaction.atomic():
        audit_locked = WorkflowAudit.objects.select_for_update().get(
            audit_id=audit.audit_id
        )
        if audit_locked.current_status != WorkflowStatus.WAITING:
            ext.save(update_fields=["last_synced_at", "current_external_node"])
            return {
                "status": "noop",
                "reason": f"audit current_status={audit_locked.current_status}, skip",
            }

        audit_locked.current_audit = "-1"
        audit_locked.next_audit = "-1"
        audit_locked.current_status = WorkflowStatus.REJECTED
        audit_locked.save()

        WorkflowAuditDetail.objects.create(
            audit_id=audit_locked.audit_id,
            audit_user=actor_label["operator"],
            audit_status=WorkflowStatus.REJECTED,
            audit_time=timezone.now(),
            remark=actor_label["remark_prefix"] + remark,
        )
        WorkflowLog.objects.create(
            audit_id=audit_locked.audit_id,
            operation_type=2,  # WorkflowAction.REJECT
            operation_type_desc="审批不通过",
            operation_info=(
                f"[OA] {actor_label['operator_display']} 驳回: "
                f"{remark or '(无备注)'}"
            ),
            operator=actor_label["operator"],
            operator_display=actor_label["operator_display"],
        )
        SqlWorkflow.objects.filter(id=audit_locked.workflow_id).update(
            status="workflow_review_reject"
        )
        _trigger_post_reject_notify(audit_locked)

    ext.save(update_fields=["last_synced_at", "current_external_node"])
    logger.info(
        "OA node REJECT: audit=%s by %s", audit_locked.audit_id, actor_label["operator_display"]
    )
    return {
        "status": "applied",
        "audit_id": audit_locked.audit_id,
        "new_status": audit_locked.current_status,
    }


def _apply_abort(ext, event: dict) -> dict:
    """instance terminate/abort: audit 标 ABORTED。"""
    from sql.models import (
        SqlWorkflow,
        WorkflowAudit,
        WorkflowAuditDetail,
        WorkflowLog,
    )
    from common.utils.const import WorkflowStatus

    audit = ext.audit
    actor_label = _resolve_actor_label(event)
    remark = _norm(event.get("remark") or event.get("comment") or "")

    with transaction.atomic():
        audit_locked = WorkflowAudit.objects.select_for_update().get(
            audit_id=audit.audit_id
        )
        if audit_locked.current_status == WorkflowStatus.PASSED:
            # 已通过的不再 abort
            return {"status": "noop", "reason": "audit already PASSED, skip abort"}

        audit_locked.next_audit = "-1"
        audit_locked.current_status = WorkflowStatus.ABORTED
        audit_locked.save()

        WorkflowAuditDetail.objects.create(
            audit_id=audit_locked.audit_id,
            audit_user=actor_label["operator"],
            audit_status=WorkflowStatus.ABORTED,
            audit_time=timezone.now(),
            remark=actor_label["remark_prefix"] + remark,
        )
        WorkflowLog.objects.create(
            audit_id=audit_locked.audit_id,
            operation_type=3,  # WorkflowAction.ABORT
            operation_type_desc="审批取消",
            operation_info=(
                f"[OA] {actor_label['operator_display']} 终止: {remark or '(无备注)'}"
            ),
            operator=actor_label["operator"],
            operator_display=actor_label["operator_display"],
        )
        SqlWorkflow.objects.filter(id=audit_locked.workflow_id).update(
            status="workflow_abort"
        )

    return {
        "status": "applied",
        "audit_id": audit_locked.audit_id,
        "new_status": audit_locked.current_status,
    }


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _calc_next_audit(audit, current_id_str: str) -> str:
    """根据 ``audit.audit_auth_groups`` 算 current 之后的下一节点，没有就 -1。"""
    auth_groups_str = _norm(audit.audit_auth_groups)
    if not auth_groups_str:
        return "-1"
    groups = [g.strip() for g in auth_groups_str.split(",") if g.strip()]
    try:
        pos = groups.index(current_id_str)
    except ValueError:
        return "-1"
    if pos + 1 >= len(groups):
        return "-1"
    return groups[pos + 1]


def _group_name(group_id_str: str) -> str:
    from django.contrib.auth.models import Group

    try:
        return Group.objects.get(id=int(group_id_str)).name
    except (Group.DoesNotExist, ValueError, TypeError):
        return f"group#{group_id_str}"


def _resolve_actor_label(event: dict) -> dict:
    """把钉钉 StaffId/StaffName 翻译成 Archery operator 字符串。

    优先按 ``Users.ding_user_id`` 反查；查不到就用 ``dingtalk_oa`` 兜底。
    """
    staff_id = _norm(event.get("StaffId") or event.get("staffId") or event.get("userId"))
    staff_name = _norm(
        event.get("StaffName")
        or event.get("staffName")
        or event.get("userName")
        or staff_id
    )

    operator = staff_id
    operator_display = staff_name or "钉钉审批人"

    if staff_id:
        from sql.models import Users
        user = (
            Users.objects.filter(ding_user_id=staff_id, is_active=1)
            .order_by("-is_superuser", "id")
            .first()
        )
        if user:
            operator = user.username
            operator_display = user.display or user.username

    return {
        "operator": operator or "dingtalk_oa",
        "operator_display": (
            f"{operator_display} (via 钉钉)" if staff_id else operator_display
        ),
        "remark_prefix": f"[OA via 钉钉] {operator_display}: " if staff_id else "[OA] ",
    }


def _trigger_post_pass_notify(audit):
    """审批通过后异步通知执行 / 提交人。失败不抛错。"""
    try:
        from django_q.tasks import async_task
        from sql.notify import notify_for_audit
        async_task(
            notify_for_audit,
            workflow_audit=audit,
            timeout=60,
            task_name=f"sqlreview-oa-pass-{audit.audit_id}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("trigger post-pass notify failed (audit=%s)", audit.audit_id)


def _trigger_post_reject_notify(audit):
    """审批驳回后异步通知提交人。失败不抛错。"""
    try:
        from django_q.tasks import async_task
        from sql.notify import notify_for_audit
        async_task(
            notify_for_audit,
            workflow_audit=audit,
            timeout=60,
            task_name=f"sqlreview-oa-reject-{audit.audit_id}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("trigger post-reject notify failed (audit=%s)", audit.audit_id)


def _norm(s) -> str:
    return "" if s is None else str(s).strip()
