"""ghost_task_sync.py — gh-ost 任务跟 SqlWorkflow 状态联动 helper。

## CUSTOM-MODIFIED: v0.3.0-beta 抽公共 helper @ 2026-08-13 @ mavis
## 业务背景: 8/13 用户反馈工单 #38 (status=workflow_abort) 的 DdlGhostTask 状态还是 queued,
##          应该跟 wf 一起变 cancelled。原因: Archery 上游 cancel() 视图有清理逻辑
##          (sql_workflow.py:524-545, 8/11 commit 664058c 加的), 但钉钉 OA 终止路径
##          (oa_callback_handler.py:331-333) 直接 .update(status='workflow_abort'),
##          绕过了清理。
## 修法: 把清理逻辑抽成 helper, cancel() 视图 + OA callback 两处都调。

## 关联: docs/changelogs/2026-08-13_ghost-task-wf-abort-sync.md
## 关联 commit: <本 commit hash>
"""
from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("default")


def cleanup_pending_ghost_tasks(workflow, operator: str, reason: str = "") -> int:
    """工单被终止/拒绝/撤回时, 清理该工单下所有非终态 DdlGhostTask。

    业务规则:
      - 仅在 CUSTOM_GH_OST_ENABLED=True 时生效
      - 清理 status in (pending, precheck_failed, queued, running, cut_over) 的 task
      - 改成 cancelled + 写 finished_at + 在 error_message 追加 [aborted] 来源
      - 异常不抛 (try/except + logger.exception), 避免影响主流程 (工单终止)

    Args:
        workflow: SqlWorkflow 实例 (用于 workflow= 过滤)
        operator: 操作人 username (写 error_message 用, "wf 被 X 拒绝/撤回/终止")
        reason: 可选 reason 描述, 默认 "拒绝/撤回"

    Returns:
        清理的 task 数量
    """
    if not getattr(settings, "CUSTOM_GH_OST_ENABLED", False):
        return 0

    try:
        # 延迟 import, 避免 settings 未加载时循环依赖
        from sql.extensions.ddl_gh_ost.models import DdlGhostTask

        pending_tasks = DdlGhostTask.objects.filter(
            workflow=workflow,
            status__in=("pending", "precheck_failed", "queued", "running", "cut_over"),
        )
        cleaned = 0
        now = timezone.now()
        for t in pending_tasks:
            t.status = "cancelled"
            t.finished_at = now
            t.error_message = (
                (t.error_message or "")
                + f"\n[aborted] 工单被 {operator} {reason}"
            ).strip()
            t.save()
            cleaned += 1
        if cleaned:
            logger.info(
                "工单 #%s 终止时清理了 %s 个非终态 DdlGhostTask (operator=%s, reason=%s)",
                workflow.id, cleaned, operator, reason,
            )
        return cleaned
    except Exception:  # noqa: BLE001
        logger.exception("清理 DdlGhostTask 失败: wf=%s", getattr(workflow, "id", None))
        return 0
