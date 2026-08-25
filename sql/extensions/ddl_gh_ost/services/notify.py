"""
gh-ost 终态钉钉群通知（best-effort，不阻塞主流程）。

设计参考：docs/designs/2026-08-05_gh-ost-product-design.html §7
"""

import logging
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger("default")


def notify_terminal(task) -> bool:
    """task 终态时发钉钉通知。

    Returns:
        True 通知成功（HTTP 200），False 跳过/失败
    """
    webhook = getattr(settings, "DINGTALK_NOTIFY_WEBHOOK", "")
    if not webhook:
        logger.info("DINGTALK_NOTIFY_WEBHOOK not set, skip notify: task=%s", task.id)
        return False

    if task.status not in ("success", "failed", "cancelled"):
        return False

    msg = _format_message(task)
    title = _status_title(task.status)
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": msg,
        },
        "at": {
            # 这里简化：@ 工程师需要 userid 转 phone，不做
            "isAtAll": False,
        },
    }

    try:
        r = requests.post(
            webhook, json=payload, timeout=5,
        )
        r.raise_for_status()
        logger.info("notify_terminal ok: task=%s status=%s", task.id, task.status)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify_terminal failed: task=%s err=%s", task.id, exc)
        return False


def _status_title(status: str) -> str:
    return {
        "success": "gh-ost 成功",
        "failed": "gh-ost 失败",
        "cancelled": "gh-ost 取消",
    }.get(status, "gh-ost")


def _format_message(task) -> str:
    """构造 markdown 消息。"""
    engineer = task.created_by or (task.workflow.engineer if task.workflow_id else "未知")
    db_t = f"{task.db_name}.{task.table_name}" if task.db_name else "未知"
    dur = task.duration_seconds
    dur_str = f"{dur // 60}m{dur % 60}s" if dur else "—"
    pct = task.progress_pct or 0
    status_emoji = {
        "success": "✅",
        "failed": "❌",
        "cancelled": "⚠️",
    }.get(task.status, "ℹ️")

    lines = [
        f"### {status_emoji} {_status_title(task.status)} · #{task.id}",
        "",
        f"- **工单**: #{task.workflow_id}  `{db_t}`",
        f"- **ALTER**: `{task.alter_statement[:200]}`",
        f"- **发起人**: @{engineer}",
        f"- **耗时**: {dur_str}（最终进度 {pct}%）",
    ]

    if task.status == "failed" and task.error_message:
        err = task.error_message.strip()[:500]
        lines.append(f"- **错误**:")
        lines.append(f"  ```\n  {err}\n  ```")

    if task.status == "cancelled" and task.error_message:
        lines.append(f"- **取消原因**: {task.error_message[:200]}")

    if task.status == "success":
        lines.append("- **影子表**: 保留 7 天可手动回滚")

    lines.append("")
    lines.append(f"[查看详情](/admin/ddl_gh_ost/ddlghosttask/{task.id}/change/)")

    return "\n".join(lines)
