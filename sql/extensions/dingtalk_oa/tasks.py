"""钉钉 OA 对账 + 强制降级。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §10.4.3 第 4 款

定时任务：``reconcile_pending_oa_workflows``
    * 周期：每 5 分钟（用 django-q2 调度，archery 默认队列框架）
    * 扫描 ``WorkflowAuditExternal`` 中 ``external_status='RUNNING'`` 且
      ``last_synced_at`` 超过阈值的记录
    * 调 DingtalkOaDriver.get_status 查实际状态
    * 连续 3 次对账失败 → 强制 fallback 到本地 Group 审批

Celery 兼容：
    archery 当前用的是 django-q2，**没有装 Celery**。代码中 ``@shared_task``
    装饰器通过 try/except 兼容：
        * 装了 celery → 用真装饰器（任务可走 Celery worker）
        * 没装 → 装饰器退化为 noop（函数可直接被 django-q2 schedule 调用）

调度方式（部署时由 ops 一次性执行）：

    python manage.py shell -c "from sql.extensions.dingtalk_oa.tasks import \\
        add_reconcile_schedule; add_reconcile_schedule()"
"""

import logging
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.utils import timezone

# 兼容 Celery：装了 celery 用真 @shared_task，没装就用 noop
try:
    from celery import shared_task  # type: ignore[import]
except ImportError:  # pragma: no cover - 项目无 Celery
    def shared_task(func):
        """Celery 未装时的 fallback 装饰器。"""
        func.delay = lambda *a, **kw: func(*a, **kw)
        func.apply_async = lambda *a, **kw: func()
        return func


from .models import DingtalkOaEventLog, WorkflowAuditExternal  # noqa: E402

logger = logging.getLogger(__name__)

# django-q2 schedule 名（按名 upsert）
RECONCILE_SCHEDULE_NAME = "dingtalk_oa_reconcile"


# ============================== 对账 task ==============================


@shared_task
def reconcile_pending_oa_workflows() -> int:
    """对账 task：每 5 分钟扫一次 RUNNING 中超时的工单（v0.7 §10.4.3）。

    Returns:
        本次扫描的工单数（用于监控 / 单元测试断言）。
    """
    threshold_min = int(
        getattr(settings, "CUSTOM_DINGTALK_OA_RECONCILE_TIMEOUT_MIN", 30)
    )
    threshold = timezone.now() - timedelta(minutes=threshold_min)

    # 延迟 import 避免 AppRegistryNotReady
    from common.utils.const import WorkflowStatus
    from .drivers.dingtalk import DingtalkOaDriver

    pending = WorkflowAuditExternal.objects.filter(
        external_status="RUNNING",
    ).filter(
        # last_synced_at 为空（刚发起）或老于阈值
        last_synced_at__lt=threshold,
    ).select_related("audit", "audit__workflow")

    driver = DingtalkOaDriver()
    scanned = 0
    for ext in pending:
        scanned += 1
        audit = ext.audit
        if audit is None:
            ext.external_status = "DONE"
            ext.save(update_fields=["external_status"])
            continue

        # 本地已非 WAITING（说明已通过/拒绝），对账无意义
        if audit.current_status != WorkflowStatus.WAITING:
            ext.external_status = "DONE"
            ext.save(update_fields=["external_status"])
            continue

        try:
            status = driver.get_status(audit) or {}
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "reconcile audit_id=%s get_status failed: %s",
                getattr(audit, "audit_id", None), e,
            )
            ext.reconcile_failed_count = (ext.reconcile_failed_count or 0) + 1
            ext.last_synced_at = timezone.now()
            ext.save(update_fields=["reconcile_failed_count", "last_synced_at"])
            if ext.reconcile_failed_count >= 3:
                _force_fallback(ext, f"reconcile failed 3 times: {e}")
            continue

        # 钉钉 status 字段：COMPLETED / RUNNING / TERMINATED
        ext_status = str(status.get("status") or "").upper()
        if ext_status in ("COMPLETED", "APPROVED", "AGREE"):
            ext.external_status = "DONE"
            ext.last_synced_at = timezone.now()
            ext.save(update_fields=["external_status", "last_synced_at"])
        elif ext_status in ("TERMINATED", "REFUSED", "REFUSE", "REJECTED"):
            ext.external_status = "TERMINATED"
            ext.last_synced_at = timezone.now()
            ext.save(update_fields=["external_status", "last_synced_at"])
        else:
            # 仍 RUNNING；只更新时间戳
            ext.last_synced_at = timezone.now()
            ext.reconcile_failed_count = 0  # 重置计数
            ext.save(update_fields=["last_synced_at", "reconcile_failed_count"])

    if scanned:
        logger.info("dingtalk OA reconcile scanned %s workflows", scanned)
    return scanned


def _force_fallback(ext: WorkflowAuditExternal, reason: str) -> None:
    """强制降级：把工单回退到本地 Group 审批（v0.7 §10.4.3 第 4 款 b）。"""
    audit = ext.audit
    if audit is None:
        return

    try:
        workflow = audit.get_workflow()
    except Exception:  # noqa: BLE001
        logger.exception("force_fallback: get_workflow failed audit_id=%s", audit.audit_id)
        return

    if not hasattr(workflow, "audit_driver"):
        # 非 SqlWorkflow（如 QueryPrivilegesApply / ArchiveConfig）不处理
        logger.warning(
            "force_fallback: workflow without audit_driver field, skip "
            "audit_id=%s", audit.audit_id,
        )
        return

    workflow.audit_driver = "archery"
    workflow.audit_fallback_reason = f"对账失败降级：{reason}"[:255]
    workflow.save(update_fields=["audit_driver", "audit_fallback_reason"])

    ext.external_status = "FALLBACK"
    ext.oa_failure_reason = reason[:500]
    ext.fallback_at = timezone.now()
    ext.save(update_fields=["external_status", "oa_failure_reason", "fallback_at"])

    DingtalkOaEventLog.objects.create(
        audit=audit,
        event_type="FALLBACK_AT_RECONCILE",
        event_id=f"reconcile-fallback-{audit.audit_id}-{int(timezone.now().timestamp())}",
        payload={"reason": reason},
        processed=True, error=reason[:1000],
    )
    # 推 DBA 群
    try:
        from .drivers.dingtalk import DingtalkOaDriver
        DingtalkOaDriver._send_admin_alert(
            f"⚠️ 钉钉 OA 对账失败，已降级到本地审批\n"
            f"工单 audit_id={audit.audit_id}\n"
            f"原因：{reason[:200]}"
        )
    except Exception:  # noqa: BLE001
        logger.exception("send admin alert for reconcile fallback failed")


# ============================== django-q2 schedule 注册 ==============================


def add_reconcile_schedule() -> Optional[object]:
    """注册对账 schedule（每 5 分钟）。

    Returns:
        ``django_q.models.Schedule`` 实例；未启用 django-q2 时返回 None。

    使用方式（部署后 ops 跑一次）：

        python manage.py shell <<EOF
        from sql.extensions.dingtalk_oa.tasks import add_reconcile_schedule
        add_reconcile_schedule()
        EOF
    """
    try:
        from django_q.models import Schedule
        from django_q.tasks import schedule
    except ImportError:  # pragma: no cover
        logger.warning("django-q2 未安装，跳过 add_reconcile_schedule")
        return None

    interval_min = int(
        getattr(settings, "CUSTOM_DINGTALK_OA_RECONCILE_INTERVAL_MIN", 5)
    )

    # 已有则删
    try:
        existing = Schedule.objects.get(name=RECONCILE_SCHEDULE_NAME)
        Schedule.delete(existing)
    except Schedule.DoesNotExist:
        pass

    return schedule(
        "sql.extensions.dingtalk_oa.tasks.reconcile_pending_oa_workflows",
        name=RECONCILE_SCHEDULE_NAME,
        schedule_type="I",  # I = interval
        minutes=interval_min,
        repeats=-1,
        timeout=-1,
    )
