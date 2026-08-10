"""
gh-ost 碎片回收 —— rebuild 场景的 CLI 构建 + 进程启动。

## CUSTOM-MODIFIED: v0.4.5-alpha 新建 rebuild service @ 2026-08-06 @ mavis
关联设计: docs/designs/2026-08-05_gh-ost-product-design.html v0.4.5 §4

设计要点：
- 复用 ``runner.build_ghost_command(rebuild_mode=True)`` 和 ``runner.start_ghost_process``
- 差异只在 ``--alter`` 改为空 COMMENT 触发表重建（不改变列结构）
- 跟 ghost 场景共享进度面板（poller.py / parser.py / notify.py 全部沿用）
- 进程日志 / PID 存到 ``DdlGhostTask`` 同一张表（用 ``task_type=rebuild`` 区分）
"""

import logging
from typing import List

from .runner import build_ghost_command, start_ghost_process

logger = logging.getLogger("default")


def build_rebuild_command(task, instance) -> List[str]:
    """rebuild 场景的 gh-ost CLI 列表。

    Args:
        task: ``DdlGhostTask`` 实例（task_type 必须 = 'rebuild'）
        instance: ``Instance`` 对象（rebuild 任务 workflow=NULL，必须显式传）

    Returns:
        list[str] gh-ost 命令行参数

    Raises:
        ValueError: task.task_type != 'rebuild' 或 task.workflow_id is not None
    """
    _validate_rebuild_task(task)
    if instance is None:
        raise ValueError("rebuild 模式必须传 instance（task.workflow=NULL）")
    return build_ghost_command(task, instance=instance, rebuild_mode=True)


def start_rebuild_process(task, instance) -> int:
    """启动 rebuild 场景的 gh-ost 子进程。

    与 ``runner.start_ghost_process`` 区别：
    - 校验 ``task.task_type == 'rebuild'`` 和 ``task.workflow_id is None``
    - 日志文件名前缀用 ``rebuild-`` 方便排错时区分

    Args:
        task: ``DdlGhostTask`` 实例（task_type=rebuild, workflow=NULL）
        instance: ``Instance`` 对象

    Returns:
        gh-ost PID（成功）

    Raises:
        ValueError: 参数不合法
        RuntimeError: gh-ost 进程秒退（看 log 排错）
    """
    _validate_rebuild_task(task)
    if instance is None:
        raise ValueError("rebuild 模式必须传 instance")

    logger.info(
        "gh-ost rebuild start: task_id=%s db=%s table=%s created_by=%s",
        task.id, task.db_name, task.table_name, task.created_by,
    )
    pid = start_ghost_process(task, instance)
    ## CUSTOM-MODIFIED: v0.4.5-alpha 修 134 dev 演练 bug：start_rebuild_process 写 task 字段 @ 2026-08-10 @ mavis
    ## bug 背景：原代码只 return pid，调用方拿到 pid 后写 task.ghost_pid；但 poller 启动时
    ## 如果调用方忘了写，task.ghost_pid=None → poller is_alive(None) 失败 → 标 failed
    ## 修复：start_rebuild_process 内部写，跟 queue.try_advance_queue 一致
    from django.utils import timezone
    task.ghost_pid = pid
    task.status = "running"
    task.started_at = task.started_at or timezone.now()
    task.current_stage = task.current_stage or "connecting"
    task.progress_pct = 0
    task.progress_message = "rebuild gh-ost 已启动"
    task.last_heartbeat_at = timezone.now()
    task.save()
    return pid


def _validate_rebuild_task(task) -> None:
    """校验 task 是合法的 rebuild 任务。

    校验规则：
        - ``task_type == 'rebuild'``
        - ``workflow_id is None``（rebuild 不挂 SQL 工单）
        - ``db_name`` 和 ``table_name`` 非空（DBA 选表必填）
        - ``target_table`` 跟 ``db_name.table_name`` 一致（防止手动改字段）
    """
    if task.task_type != "rebuild":
        raise ValueError(
            f"task.task_type={task.task_type!r} 不是 'rebuild'，"
            f"请用 runner.start_ghost_process 走 ghost 流程",
        )
    if task.workflow_id is not None:
        raise ValueError(
            f"rebuild 任务不应挂 workflow（当前 workflow_id={task.workflow_id}）",
        )
    if not task.db_name or not task.table_name:
        raise ValueError(
            f"rebuild 任务 db_name/table_name 必填（db={task.db_name!r}, table={task.table_name!r}）",
        )
    expected_target = f"{task.db_name}.{task.table_name}"
    if task.target_table and task.target_table != expected_target:
        # 仅警告，不抛错 —— target_table 字段可能 DBA 临时改了
        logger.warning(
            "rebuild task target_table=%r != %r，按 db_name.table_name 走",
            task.target_table, expected_target,
        )
