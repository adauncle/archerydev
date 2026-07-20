"""钉钉 OA 集成 — Django 视图。

目前只暴露一个手动重试视图：``retry_oa``。
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from sql.models import SqlWorkflow

from .drivers.dingtalk import DingtalkOaDriver
from .services.policy import match_policy
from .services.sql_type_detect import extract_affected_tables

logger = logging.getLogger(__name__)


@permission_required("sql.audit_user", raise_exception=True)
@require_POST
def retry_oa(request, workflow_id: int):
    """手动重试钉钉 OA（仅降级工单显示按钮，v0.7 §10.4.6）。

    流程：
        1. 重新跑 ``match_policy`` 看是否仍命中 dingtalk_oa flow；
        2. 调 ``DingtalkOaDriver.start()``；
        3. 清空 ``audit_fallback_reason``，把 driver 切回 dingtalk_oa。

    失败时回到原页面 + 错误消息；不抛出。
    """
    workflow = get_object_or_404(SqlWorkflow, pk=workflow_id)

    try:
        affected_tables = extract_affected_tables(workflow)
        policy = match_policy(workflow, affected_tables=affected_tables)
    except Exception as e:  # noqa: BLE001
        logger.exception("retry_oa: match_policy failed workflow=%s: %s", workflow_id, e)
        messages.error(request, f"策略匹配失败：{e}")
        return redirect(reverse("sql:detail", args=[workflow_id]))

    if not policy or policy.flow.audit_driver != "dingtalk_oa":
        messages.error(request, "当前工单策略不要求钉钉 OA，无需重试")
        return redirect(reverse("sql:detail", args=[workflow_id]))

    audit = workflow.get_audit()
    if audit is None:
        messages.error(request, "找不到对应的审批记录")
        return redirect(reverse("sql:detail", args=[workflow_id]))

    try:
        driver = DingtalkOaDriver()
        result = driver.start(workflow, audit, policy.flow)
    except Exception as e:  # noqa: BLE001
        logger.exception("retry_oa: driver.start failed workflow=%s", workflow_id)
        messages.error(request, f"重试失败：{e}")
        return redirect(reverse("sql:detail", args=[workflow_id]))

    if (result.extra or {}).get("fallback"):
        messages.warning(
            request,
            f"重试触发降级：{result.extra.get('reason', '')[:200]}",
        )
    else:
        messages.success(request, "已重新发起钉钉 OA")
    return redirect(reverse("sql:detail", args=[workflow_id]))
