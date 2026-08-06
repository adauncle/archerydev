"""
gh-ost 碎片回收 —— 任务队列（同表 FIFO 排队 + 归档联动）。

## CUSTOM-MODIFIED: v0.4.5-alpha 新建 queue @ 2026-08-06 @ mavis
关联设计: docs/designs/2026-08-05_gh-ost-product-design.html v0.4.5 §7

核心规则：
- 同表冲突：DBA 同时点"归档 + 回收"或两个回收 → rebuild 排队等前面完成
- 任务状态推进：rebuild 任务完成 → 调 ``try_advance_queue`` 推进同表下一个
- 关联归档：v0.4.2 接入（commit 5 提供 ``trigger_rebuild_after_archive`` helper，
  ``archiver.py`` 接入点见 helper docstring）

不引入新的 ORM 表 —— 用 ``DdlGhostTask.status='queued'`` 当队列状态，
FIFO 排序用 ``created_at``。重启后队列丢失（task 状态保留，停止时 pending/running
会被 poller 死进程检测标 failed；queued 任务不会被自动启动，要 DBA 重触发）。
"""

import logging
from typing import Optional

from django.conf import settings
from django.utils import timezone

from ..models import DdlGhostTask

logger = logging.getLogger("default")


# ===========================================================================
# 同表 FIFO 排队
# ===========================================================================

def find_waiting_for(db: str, table: str):
    """查同表 status=queued 的最早 task（按 created_at 排序，FIFO）。

    Args:
        db: 数据库名
        table: 表名

    Returns:
        QuerySet（可继续 .first() / .count() / etc.）
    """
    return DdlGhostTask.objects.filter(
        task_type="rebuild",
        db_name=db, table_name=table,
        status="queued",
    ).order_by("created_at")


def get_queue_position(task: DdlGhostTask) -> int:
    """查 task 在同表队列里排第几（1 = 队头，2 = 第二，0 = 不在队列）。

    Returns:
        0 = task 不在 queued 状态
        1+ = 排队位置
    """
    if task.status != "queued":
        return 0
    earlier = find_waiting_for(task.db_name, task.table_name).filter(
        created_at__lt=task.created_at,
    ).count()
    return earlier + 1


def try_advance_queue(db: str, table: str) -> Optional[DdlGhostTask]:
    """任务完成时调，推进同表下一个等待的 rebuild。

    流程：
        1. 找同表最早的 queued task（FIFO）
        2. 解析 instance（从 ``related_task_id`` 关联 ArchiveConfig 拿源 instance）
        3. ``start_rebuild_process`` 启动 gh-ost
        4. 写 PID + started_at + status=running
        5. 启动 poller

    Args:
        db: 数据库名
        table: 表名

    Returns:
        启动的 task（None = 队列空，没人启动）
    """
    waiting = find_waiting_for(db, table).first()
    if not waiting:
        logger.debug("queue empty for %s.%s", db, table)
        return None

    instance = _resolve_instance(waiting)
    if instance is None:
        waiting.status = "failed"
        waiting.error_message = (
            "queue 推进失败：无法解析 instance"
            "（related_task_id 无效或 ArchiveConfig 不存在）"
        )
        waiting.finished_at = timezone.now()
        waiting.save()
        logger.warning(
            "queue advance: task #%s instance 解析失败，跳过",
            waiting.id,
        )
        return waiting

    # 启动 gh-ost（rebuild 模式）
    from .rebuild import start_rebuild_process
    try:
        pid = start_rebuild_process(waiting, instance)
    except Exception as exc:  # noqa: BLE001
        logger.exception("queue advance start_rebuild_process failed: task=%s", waiting.id)
        waiting.status = "failed"
        waiting.error_message = f"queue 推进启动 gh-ost 失败：{exc}"
        waiting.finished_at = timezone.now()
        waiting.save()
        return waiting

    waiting.ghost_pid = pid
    waiting.status = "running"
    waiting.started_at = timezone.now()
    waiting.current_stage = "connecting"
    waiting.progress_pct = 0
    waiting.progress_message = "queue 推进启动"
    waiting.last_heartbeat_at = timezone.now()
    waiting.save()

    # 启动 poller
    from .poller import start_poller
    try:
        start_poller(waiting.id)
    except Exception:  # noqa: BLE001
        logger.exception("start_poller failed in queue advance: task=%s", waiting.id)
        waiting.error_message = "poller 启失败 — gh-ost 在跑但没人在轮询"
        waiting.save()

    logger.info(
        "queue advance: task_id=%s db=%s table=%s pid=%s",
        waiting.id, db, table, pid,
    )
    return waiting


# ===========================================================================
# 关联归档：v0.4.2 联动 helper
# ===========================================================================

def trigger_rebuild_after_archive(archive_id: int) -> Optional[DdlGhostTask]:
    """归档完成钩子 —— 自动触发 src 表的 rebuild。

    ## 接入点（v0.4.2 实施时改）：
    ``sql/archiver.py`` 的 ``archive()`` 函数末尾（约 line 475）添加：

    ```python
    from sql.extensions.ddl_gh_ost.services.queue import trigger_rebuild_after_archive
    try:
        trigger_rebuild_after_archive(archive_id)
    except Exception:
        logger.exception("trigger_rebuild_after_archive failed: archive=%s", archive_id)
    ```

    ## 触发条件：
    1. ``ArchiveConfig.auto_rebuild_after_archive`` 字段为 True（commit 5 仅文档化，
       字段由 v0.4.2 实施时 migration 0003 加）
    2. ``CUSTOM_GH_OST_REBUILD_AUTO_LINK_ARCHIVE`` 全局开关为 True（默认 False）
    3. 同表无已有 running/queued/cut_over 任务

    ## 行为：
    - 写新 DdlGhostTask（task_type=rebuild, workflow=NULL, related_task_id=archive_id）
    - 调 ``try_advance_queue`` 立即推进（如果同表没有别的排队 task，直接启动）

    Args:
        archive_id: ArchiveConfig.id

    Returns:
        新建 / 推进的 rebuild task（None = 不需要触发）
    """
    # 全局灰度开关
    if not getattr(settings, "CUSTOM_GH_OST_REBUILD_AUTO_LINK_ARCHIVE", False):
        logger.debug("trigger_rebuild_after_archive: 灰度开关关，跳过 archive #%s", archive_id)
        return None

    # 跨 app import 放函数内（避免启动时循环依赖）
    from sql.models import ArchiveConfig
    try:
        archive = ArchiveConfig.objects.get(id=archive_id)
    except ArchiveConfig.DoesNotExist:
        logger.warning(
            "trigger_rebuild_after_archive: archive #%s 不存在",
            archive_id,
        )
        return None

    # ArchiveConfig.auto_rebuild_after_archive 字段（v0.4.2 加，commit 5 暂不强制）
    if not getattr(archive, "auto_rebuild_after_archive", False):
        logger.debug(
            "archive #%s auto_rebuild_after_archive=False, skip",
            archive_id,
        )
        return None

    # 同表已存在 running/queued/cut_over 任务 → 不重复建
    existing = DdlGhostTask.objects.filter(
        task_type="rebuild",
        db_name=archive.src_db_name, table_name=archive.src_table_name,
        status__in=["queued", "running", "cut_over"],
    ).first()
    if existing:
        logger.info(
            "trigger_rebuild_after_archive: archive #%s 同表已有 task #%s, skip",
            archive_id, existing.id,
        )
        return existing

    # 写 rebuild task
    task = DdlGhostTask.objects.create(
        workflow=None,
        task_type="rebuild",
        db_name=archive.src_db_name,
        table_name=archive.src_table_name,
        target_table=f"{archive.src_db_name}.{archive.src_table_name}",
        related_task_id=archive.id,
        enabled=True,
        status="queued",
        created_by=f"archive-{archive.user_name}",
        max_load_threads_running=30,
        timeout_seconds=7200,
    )
    logger.info(
        "archive #%s 触发 rebuild: task #%s db=%s table=%s",
        archive_id, task.id, archive.src_db_name, archive.src_table_name,
    )

    # 立即推进（如果同表无别的排队 task）
    return try_advance_queue(archive.src_db_name, archive.src_table_name)


# ===========================================================================
# instance 解析
# ===========================================================================

def _resolve_instance(task: DdlGhostTask):
    """从 task 推断 instance。

    rebuild task ``workflow=NULL`` 没有直接的 instance 字段。

    推断规则：
        1. 如果 ``task.related_task_id`` 非空（关联归档 task），
           查 ``ArchiveConfig`` 拿 ``src_instance``（归档源实例）
        2. 否则返回 None —— DBA 应通过端点 /gh_ost/rebuild/start/ 显式传 instance
    """
    if task.related_task_id is None:
        return None
    try:
        from sql.models import ArchiveConfig
        archive = ArchiveConfig.objects.get(id=task.related_task_id)
        return archive.src_instance
    except Exception:  # noqa: BLE001
        logger.warning(
            "_resolve_instance: ArchiveConfig #%s 查不到",
            task.related_task_id,
        )
        return None
