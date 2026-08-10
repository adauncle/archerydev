"""
gh-ost 后台 poller：每 3s 读 stdout 解析 + 状态机推进 + 暂停阈值。

启动方式：start 端点启 gh-ost 子进程后，立刻启动一个 daemon thread 跑 poll_loop。
终态时 thread 自动退出。

全局 ``_active_pollers`` dict 跟踪当前在跑的 poller（防止同一 task 重复启动）。
"""

import logging
import os
import signal
import threading
import time
from typing import Dict, Optional

import pymysql
from django.conf import settings
from django.utils import timezone

from ..models import DdlGhostTask
from .db import _get_creds
from .notify import notify_terminal
from .parser import parse_ghost_log
from .runner import is_alive, read_log_tail

logger = logging.getLogger("default")

# 全局 poller 跟踪
_active_pollers: Dict[int, threading.Thread] = {}
_pollers_lock = threading.Lock()

# poll 配置
POLL_INTERVAL = 3  # 秒
THREADS_RUNNING_QUERY_INTERVAL = 10  # 10s 查一次 Threads_running（不要每 3s 都查）


def _query_threads_running(instance) -> Optional[int]:
    """查 MySQL Threads_running 状态值。"""
    try:
        user, password, (host, port) = _get_creds(instance)
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            connect_timeout=2, autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SHOW GLOBAL STATUS LIKE 'Threads_running'")
                row = cur.fetchone()
                if row:
                    return int(row.get("Value", 0))
                return None
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("query Threads_running failed: %s", exc)
        return None


def _maybe_pause_resume(task, instance):
    """根据 Threads_running 决定 SIGSTOP / SIGCONT gh-ost 进程。"""
    if not task.ghost_pid or not is_alive(task.ghost_pid):
        return
    threads = _query_threads_running(instance)
    if threads is None:
        return
    threshold = task.max_load_threads_running
    try:
        if threads > threshold and task.progress_pct < 100:
            # 暂停
            os.kill(task.ghost_pid, signal.SIGSTOP)
            logger.info("gh-ost paused: task=%s pid=%s threads=%s threshold=%s",
                        task.id, task.ghost_pid, threads, threshold)
            # 不写到 stderr_tail 太多，简单标记
            if "⏸ paused" not in (task.progress_message or ""):
                task.progress_message = (task.progress_message or "") + f" ⏸ paused(thr={threads})"
        else:
            # 如果之前 SIGSTOP 过，恢复（用 SIGCONT）
            # 简化：定期 SIGCONT（如果进程在跑，SIGCONT 是 no-op）
            # 不严格判断 paused 状态 — 简单点
            if threads <= threshold:
                # 仅当 process 存在时
                try:
                    os.kill(task.ghost_pid, signal.SIGCONT)
                except (ProcessLookupError, PermissionError):
                    pass
    except (ProcessLookupError, PermissionError):
        pass


def _finalize_task(task, new_status: str, error_message: str = ""):
    """终态收尾：写状态、停止进程、通知、推进同表 rebuild 队列。

    ## CUSTOM-MODIFIED: v0.3.0-beta 同步 SqlWorkflow.status
    ## gh-ost 完成后必须把工单状态推到 workflow_finish / workflow_exception，
    ## 否则 DBA 详情页的"立即执行"按钮仍会显示，导致双 ALTER 锁等待。
    ## @ 2026-08-10 @ mavis
    关联设计: docs/designs/2026-08-10_gh-ost-detail-design.html §7.3
    """
    task.status = new_status
    task.finished_at = timezone.now()
    if error_message:
        task.error_message = (task.error_message or "") + "\n" + error_message
    if task.ghost_pid:
        try:
            os.kill(task.ghost_pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    task.save()

    # CUSTOM: 同步工单状态 (仅对挂载到 SqlWorkflow 的 task 生效；rebuild 无关联)
    try:
        _sync_workflow_status(task, new_status)
    except Exception:  # noqa: BLE001
        logger.exception("_sync_workflow_status failed: task=%s", task.id)

    # 钉钉通知（best-effort）
    try:
        notify_terminal(task)
    except Exception:  # noqa: BLE001
        logger.exception("notify_terminal failed: task=%s", task.id)
    ## CUSTOM-MODIFIED: v0.4.5-alpha 终态后推进同表 rebuild 队列 @ 2026-08-06 @ mavis
    if task.task_type == "rebuild":
        # 延迟 import 防循环
        from .queue import try_advance_queue
        try:
            try_advance_queue(task.db_name, task.table_name)
        except Exception:  # noqa: BLE001
            logger.exception(
                "try_advance_queue failed after task #%s finalize",
                task.id,
            )


# task 终态 → SqlWorkflow.status 映射表
_WORKFLOW_STATUS_MAP = {
    "success": "workflow_finish",        # cut-over 成功 → 工单正常结束
    "failed": "workflow_exception",      # gh-ost 失败  → 工单执行异常
    "rolled_back": "workflow_exception", # DBA 手动回滚 → 工单执行异常
    # "cancelled" 不在这里 —— cancel 端点单独处理（不要覆盖"用户主动放弃"语义）
}


def _sync_workflow_status(task, new_status: str):
    """CUSTOM: gh-ost 终态时同步 SqlWorkflow.status。

    规则:
      - 仅同步 task_type="ghost"（挂载到 SqlWorkflow）；rebuild task 跳过
      - 仅在工单处于"待执行/执行中"语义时覆盖，避免打乱 manreviewing 等上游状态
      - success → workflow_finish + finish_time
      - failed/rolled_back → workflow_exception + finish_time
    """
    if task.task_type != "ghost":
        return  # rebuild 任务无关联工单
    if not task.workflow_id:
        return  # 没挂工单
    # 延迟 import 防循环
    from sql.models import SqlWorkflow
    try:
        wf = SqlWorkflow.objects.get(pk=task.workflow_id)
    except SqlWorkflow.DoesNotExist:
        logger.warning("_sync_workflow_status: workflow %s not found", task.workflow_id)
        return

    target = _WORKFLOW_STATUS_MAP.get(new_status)
    if not target:
        return  # cancelled / queued/running 不动

    # 仅在工单处于"已审核通过待执行"或"执行中"时同步
    if wf.status not in ("workflow_review_pass", "workflow_executing", "workflow_timingtask"):
        logger.info(
            "_sync_workflow_status: skip task=%s wf=%s current_status=%s (not in expected)",
            task.id, wf.id, wf.status,
        )
        return

    wf.status = target
    wf.finish_time = timezone.now()
    wf.save(update_fields=["status", "finish_time"])
    logger.info(
        "_sync_workflow_status: task=%s wf=%s status=%s → %s",
        task.id, wf.id, _WORKFLOW_STATUS_MAP.get(new_status, "?"), target,
    )


def poll_loop(task_id: int):
    """主循环：每 3s 读 log + 解析 + 写 progress + 状态机。

    终态时自动 return。**外层 try/except 兜底**：任何未捕获异常都写到 task.error_message，
    并把 task 切到 failed 状态，让 DBA 能看到。
    """
    try:
        # reload task
        task = DdlGhostTask.objects.get(pk=task_id)
    except DdlGhostTask.DoesNotExist:
        logger.error("poll_loop: task %s not found", task_id)
        return

    if task.status not in ("queued", "running"):
        logger.warning("poll_loop: task %s status=%s, skip", task_id, task.status)
        return

    log_dir = getattr(settings, "CUSTOM_GH_OST_LOG_DIR", "/var/log/archery/gh_ost")
    log_path = os.path.join(log_dir, f"ghost-{task_id}.log")
    try:
        instance = task.workflow.instance if task.workflow_id else None
    except Exception:  # noqa: BLE001
        instance = None
    last_threads_check = 0

    # 标记 running
    if task.status == "queued":
        task.status = "running"
        task.current_stage = "connecting"
        task.started_at = task.started_at or timezone.now()
        task.save()

    try:
        while True:
            # 进程死了？检查
            try:
                alive = is_alive(task.ghost_pid) if task.ghost_pid else False
            except Exception:  # noqa: BLE001
                logger.exception("is_alive failed")
                alive = False

            if not alive:
                # 进程退出，看最后一行 + returncode
                try:
                    tail = read_log_tail(log_path, max_bytes=8192)
                    result = parse_ghost_log(tail)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("read/parse log failed on dead process")
                    _finalize_task(task, "failed", f"log 读取失败：{exc}")
                    break
                if result.is_failed:
                    _finalize_task(task, "failed", result.error_message or "gh-ost 进程异常退出")
                elif result.is_done:
                    _finalize_task(task, "success", "")
                else:
                    # 没明确成功/失败，但进程死了 — 视为失败
                    _finalize_task(task, "failed", "gh-ost 进程退出但未标记成功")
                break

            # 进程还活着：读 log 解析
            try:
                tail = read_log_tail(log_path, max_bytes=16384)
            except Exception as exc:  # noqa: BLE001
                logger.warning("read_log_tail failed: %s", exc)
                time.sleep(POLL_INTERVAL)
                continue

            if not tail:
                # log 还是空（启动早期）
                time.sleep(POLL_INTERVAL)
                continue

            try:
                result = parse_ghost_log(tail)
            except Exception as exc:  # noqa: BLE001
                logger.exception("parse_ghost_log failed")
                time.sleep(POLL_INTERVAL)
                continue

            # 写 progress 字段
            changed = False
            if result.stage and result.stage != task.current_stage:
                task.current_stage = result.stage
                changed = True
            if result.progress_pct is not None and result.progress_pct != task.progress_pct:
                task.progress_pct = result.progress_pct
                changed = True
            if result.rows_copied is not None and result.rows_copied != task.progress_rows_copied:
                task.progress_rows_copied = result.rows_copied
                changed = True
            if result.rows_total is not None and result.rows_total != task.progress_rows_total:
                task.progress_rows_total = result.rows_total
                changed = True
            if result.eta_seconds is not None and result.eta_seconds != task.progress_eta_seconds:
                task.progress_eta_seconds = result.eta_seconds
                changed = True
            if result.last_message and result.last_message != task.progress_message:
                task.progress_message = result.last_message[:500]
                changed = True
            if result.error_message and not task.error_message:
                task.error_message = result.error_message[:2000]
                changed = True
            # 保存 stderr_tail（最近 8KB）
            if len(tail) > 100:
                task.stderr_tail = tail[-8000:]
                changed = True

            task.last_heartbeat_at = timezone.now()

            # 暂停/恢复（每 10s 一次）
            if instance and time.time() - last_threads_check > THREADS_RUNNING_QUERY_INTERVAL:
                try:
                    _maybe_pause_resume(task, instance)
                except Exception:  # noqa: BLE001
                    logger.exception("maybe_pause_resume failed")
                last_threads_check = time.time()

            if changed:
                try:
                    task.save(update_fields=[
                        "current_stage", "progress_pct", "progress_rows_copied",
                        "progress_rows_total", "progress_eta_seconds",
                        "progress_message", "error_message", "stderr_tail",
                        "last_heartbeat_at",
                    ])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("task.save failed in poll_loop: %s", exc)

            # 解析到 done / failed 立即结束
            if result.is_done:
                _finalize_task(task, "success", "")
                break
            if result.is_failed:
                _finalize_task(task, "failed", result.error_message or "")
                break

            time.sleep(POLL_INTERVAL)
    except Exception as exc:  # noqa: BLE001
        # 任何未捕获异常 — 写 task 错误 + 切 failed
        logger.exception("poll_loop crashed for task %s", task_id)
        try:
            task.refresh_from_db()
            if not task.is_terminal:
                task.status = "failed"
                task.finished_at = timezone.now()
                task.error_message = (task.error_message or "") + f"\n[poller crashed] {type(exc).__name__}: {exc}"
                task.save()
        except Exception:  # noqa: BLE001
            logger.exception("failed to mark task as failed")
        finally:
            with _pollers_lock:
                _active_pollers.pop(task_id, None)


def start_poller(task_id: int) -> bool:
    """启动后台 poller thread。同一 task 已有 poller 在跑则跳过。"""
    with _pollers_lock:
        existing = _active_pollers.get(task_id)
        if existing and existing.is_alive():
            logger.info("poller already running: task=%s", task_id)
            return False
        t = threading.Thread(
            target=poll_loop, args=(task_id,),
            name=f"gh-ost-poller-{task_id}",
            daemon=True,
        )
        t.start()
        _active_pollers[task_id] = t
        logger.info("poller started: task=%s thread=%s", task_id, t.name)
        return True
