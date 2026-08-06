"""gh-ost 二次开发 — Django 视图。

alpha 阶段暴露：
    - ``/gh_ost/precheck/<workflow_id>/`` POST  跑预检（仅 admin/staff 可见）
    - ``/gh_ost/enable/<workflow_id>/``  POST  启用 gh-ost + 写 task
    - ``/gh_ost/start/<workflow_id>/``   POST  启动（alpha: 标 running，不真起进程）
    - ``/gh_ost/cancel/<workflow_id>/``  POST  取消
    - ``/gh_ost/status/<workflow_id>/``  GET   进度查询（前端 polling）
    - ``/gh_ost/progress/<workflow_id>/`` GET  渲染进度面板（Django template + JS polling）

设计参考：docs/designs/2026-08-05_gh-ost-product-design.html §6/§10
"""

import json
import logging
import re
from typing import Optional

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from sql.models import SqlWorkflow, SqlWorkflowContent

from .models import DdlGhostTask
from .services.db import _get_creds
from .services.poller import start_poller
from .services.precheck import run_all_prechecks
from .services.runner import start_ghost_process, stop_ghost_process

logger = logging.getLogger("default")


# ===========================================================================
# 工具：取工单 SQL 文本（走 OneToOne）
# ===========================================================================
def _workflow_sql_text(workflow: SqlWorkflow) -> str:
    """取工单的 SQL 文本。SqlWorkflowContent 走 OneToOne 反向默认名 ``sqlworkflowcontent``。"""
    try:
        return SqlWorkflowContent.objects.get(workflow=workflow).sql_content or ""
    except SqlWorkflowContent.DoesNotExist:
        return ""


# ===========================================================================
# 工具：解析 SQL 提取首条 ALTER + 表名
# ===========================================================================
_FIRST_ALTER_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+`?(?P<schema>[^`\s.()]+(?:\.`?[^`\s.()]+`?)?`?\.)?`?"
    r"(?P<table>[^`\s(]+)`?",
    re.IGNORECASE | re.DOTALL,
)


def _parse_first_alter(sql_content: str) -> Optional[dict]:
    """提取 SQL 文本里的第一条 ALTER TABLE，兼容 ``db.table`` 写法。

    返回 {"db": "db1", "table": "t1", "full": "ALTER TABLE ..."}，解析失败返回 None。
    """
    if not sql_content:
        return None
    # 按分号切，取第一条非空
    statements = [s.strip() for s in sql_content.split(";") if s.strip()]
    for stmt in statements:
        # 去掉前导注释
        lines = []
        for line in stmt.splitlines():
            stripped = line.strip()
            if stripped.startswith("--") or not stripped:
                continue
            lines.append(line)
        cleaned = "\n".join(lines).strip()
        m = _FIRST_ALTER_RE.match(cleaned)
        if m:
            schema = m.group("schema") or ""
            table = m.group("table") or ""
            schema = schema.rstrip(".").strip("`")
            table = table.strip("`")
            return {
                "db": schema or None,
                "table": table,
                "full": cleaned,
            }
    return None


# ===========================================================================
# 视图：预检
# ===========================================================================
@login_required
@require_POST
def precheck(request: HttpRequest, workflow_id: int) -> JsonResponse:
    """跑预检 5 道关，返回 JSON 报告。**不写 task**（仅展示）。"""
    workflow = get_object_or_404(SqlWorkflow, pk=workflow_id)
    parsed = _parse_first_alter(_workflow_sql_text(workflow))
    if not parsed:
        return JsonResponse({
            "ok": False,
            "passed": False,
            "summary": "未找到 ALTER TABLE 语句",
            "checks": [],
        }, status=400)

    db_name = parsed["db"] or workflow.db_name
    table_name = parsed["table"]
    if not db_name or not table_name:
        return JsonResponse({
            "ok": False,
            "passed": False,
            "summary": "无法解析 db/table",
            "checks": [],
        }, status=400)

    instance = workflow.instance
    report = run_all_prechecks(
        workflow=workflow,
        instance=instance,
        db_name=db_name,
        table_name=table_name,
        alter_sql=parsed["full"],
    )
    return JsonResponse({
        "ok": True,
        "passed": report["passed"],
        "summary": report["summary"],
        "checks": report["checks"],
        "db": db_name,
        "table": table_name,
        "alter_sql": parsed["full"][:500],
        "table_size_bytes": report["table_size_bytes"],
    })


# ===========================================================================
# 视图：进度查询（前端 polling，3s 一次）
# ===========================================================================


# ===========================================================================
# 视图：启用 gh-ost + 写 task
# ===========================================================================
@login_required
@require_POST
def enable(request: HttpRequest, workflow_id: int) -> JsonResponse:
    """启用 gh-ost：预检通过后写 DdlGhostTask（alpha 不启进程）。"""
    workflow = get_object_or_404(SqlWorkflow, pk=workflow_id)

    parsed = _parse_first_alter(_workflow_sql_text(workflow))
    if not parsed:
        return JsonResponse({"ok": False, "error": "未找到 ALTER TABLE 语句"}, status=400)

    db_name = parsed["db"] or workflow.db_name
    table_name = parsed["table"]

    # 已经存在 task？
    existing = DdlGhostTask.objects.filter(workflow=workflow).first()
    if existing and existing.status in ("running", "cut_over", "queued"):
        return JsonResponse({
            "ok": False,
            "error": f"task 已在执行中（status={existing.status}），不能重复启用",
        }, status=409)

    instance = workflow.instance
    report = run_all_prechecks(
        workflow=workflow,
        instance=instance,
        db_name=db_name,
        table_name=table_name,
        alter_sql=parsed["full"],
    )
    if not report["passed"]:
        # 仍然写一条 task 记录（precheck_failed），便于审计
        task = _upsert_task(
            workflow, parsed, db_name, table_name,
            passed=False, report=report, created_by=request.user.username,
        )
        return JsonResponse({
            "ok": False,
            "passed": False,
            "summary": report["summary"],
            "checks": report["checks"],
            "task_id": task.id,
        }, status=422)

    # 预检通过 → 写 task（status=queued，alpha 阶段不进 running）
    task = _upsert_task(
        workflow, parsed, db_name, table_name,
        passed=True, report=report, created_by=request.user.username,
    )
    return JsonResponse({
        "ok": True,
        "passed": True,
        "summary": report["summary"],
        "task_id": task.id,
        "status": task.status,
    })


def _upsert_task(workflow, parsed, db_name, table_name,
                 passed: bool, report: dict, created_by: str) -> DdlGhostTask:
    """创建或更新 task（alpha 阶段如果 precheck 失败 → 写 failed record）。"""
    defaults = {
        "enabled": True,
        "precheck_passed": passed,
        "precheck_report": report,
        "precheck_at": timezone.now(),
        "alter_statement": parsed["full"][:5000],
        "db_name": db_name or "",
        "table_name": table_name or "",
        "ghost_table_name": f"_{table_name}_gho" if table_name else "",
        "original_table_size_bytes": report.get("table_size_bytes") or None,
        "status": "queued" if passed else "precheck_failed",
        "created_by": created_by or "",
    }
    if passed:
        # 拿到 audit（如果工单已提交）
        audit = workflow.get_audit() if hasattr(workflow, "get_audit") else None
        if audit:
            defaults["audit"] = audit

    task, _created = DdlGhostTask.objects.update_or_create(
        workflow=workflow, defaults=defaults,
    )
    return task


# ===========================================================================
# 视图：启动（alpha 标 running + 假进度，不真启 gh-ost）
# ===========================================================================
@login_required
@require_POST
def start(request: HttpRequest, workflow_id: int) -> JsonResponse:
    """beta 阶段：真启 gh-ost 子进程 + 启动后台 poller。

    流程：
        1. 拿 task，状态校验
        2. ``runner.start_ghost_process`` Popen gh-ost
        3. 写 PID + started_at
        4. 启动 ``poller.start_poller`` daemon thread（3s 轮询）
        5. 返回 ok
    """
    task = get_object_or_404(DdlGhostTask, workflow_id=workflow_id)
    if task.status != "queued":
        return JsonResponse({
            "ok": False,
            "error": f"当前状态 {task.status}，不能启动（需 queued）",
        }, status=409)
    if not task.precheck_passed:
        return JsonResponse({
            "ok": False,
            "error": "预检未通过，不能启动",
        }, status=409)

    instance = task.workflow.instance if task.workflow_id else None
    if instance is None:
        return JsonResponse({
            "ok": False,
            "error": "工单没有关联实例，无法启动 gh-ost",
        }, status=400)

    # 真启 gh-ost
    try:
        pid = start_ghost_process(task, instance=instance)
    except Exception as exc:  # noqa: BLE001
        logger.exception("start_ghost_process failed: task=%s", task.id)
        task.status = "failed"
        task.error_message = f"启动 gh-ost 失败：{exc}"
        task.finished_at = timezone.now()
        task.save()
        return JsonResponse({
            "ok": False,
            "error": f"启动 gh-ost 失败：{exc}",
        }, status=500)

    task.ghost_pid = pid
    task.status = "running"
    task.started_at = timezone.now()
    task.current_stage = "connecting"
    task.progress_pct = 0
    task.progress_message = "gh-ost 已启动，等待连接"
    task.last_heartbeat_at = timezone.now()
    task.save()

    # 启动后台 poller
    try:
        start_poller(task.id)
    except Exception:  # noqa: BLE001
        logger.exception("start_poller failed: task=%s", task.id)
        # poller 启失败不回滚 gh-ost 进程，让它继续；poller 死了 task 永远 running
        # 给 task 加 error_message 提示 DBA 手动处理
        task.error_message = "poller 启失败 — gh-ost 在跑但没人在轮询，请 DBA 介入"
        task.save()

    logger.info(
        "gh-ost started: task_id=%s pid=%s workflow=%s user=%s",
        task.id, pid, workflow_id, request.user.username,
    )
    return JsonResponse({
        "ok": True, "status": task.status, "task_id": task.id, "pid": pid,
    })


# ===========================================================================
# 视图：重试
# ===========================================================================
@login_required
@require_POST
def retry(request: HttpRequest, workflow_id: int) -> JsonResponse:
    """重试 task：仅当 status in (failed, cancelled) 才能 retry。重新走 start 路径。"""
    task = DdlGhostTask.objects.filter(workflow_id=workflow_id).first()
    if not task:
        return JsonResponse({"ok": False, "error": "task 不存在"}, status=404)
    if task.status not in ("failed", "cancelled"):
        return JsonResponse({
            "ok": False,
            "error": f"当前状态 {task.status}，只能重试 failed/cancelled",
        }, status=409)
    if not task.precheck_passed:
        return JsonResponse({
            "ok": False,
            "error": "预检未通过，不能重试（请重新 enable）",
        }, status=409)

    # 重置 task
    task.status = "queued"
    task.started_at = None
    task.finished_at = None
    task.ghost_pid = None
    task.current_stage = ""
    task.progress_pct = 0
    task.progress_rows_copied = None
    task.progress_rows_total = None
    task.progress_eta_seconds = None
    task.progress_speed_rows_per_sec = None
    task.progress_message = "重试中"
    task.stderr_tail = ""
    task.error_message = ""
    task.last_heartbeat_at = None
    task.save()

    # 复用 start 逻辑
    instance = task.workflow.instance if task.workflow_id else None
    if instance is None:
        return JsonResponse({"ok": False, "error": "工单无关联实例"}, status=400)

    try:
        pid = start_ghost_process(task, instance=instance)
    except Exception as exc:  # noqa: BLE001
        task.status = "failed"
        task.error_message = f"重试启动失败：{exc}"
        task.finished_at = timezone.now()
        task.save()
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    task.ghost_pid = pid
    task.status = "running"
    task.started_at = timezone.now()
    task.last_heartbeat_at = timezone.now()
    task.save()

    try:
        start_poller(task.id)
    except Exception:  # noqa: BLE001
        logger.exception("start_poller failed on retry: task=%s", task.id)

    return JsonResponse({"ok": True, "status": task.status, "task_id": task.id, "pid": pid})


# ===========================================================================
# 视图：回滚（drop 影子表 + 标 rolled_back）
# ===========================================================================
@login_required
@require_POST
def rollback(request: HttpRequest, workflow_id: int) -> JsonResponse:
    """DBA 手动回滚：drop 影子表 + 标 rolled_back。

    注意：cut-over 成功（status=success）后影子表是 _<table>_gho，
    实际表已经 rename 过了，回滚意味着 drop 影子表 + 改 status=rolled_back。
    但 cut-over 成功后影子表其实已经不在了，需要 drop 旧表（如果存在）。
    """
    task = DdlGhostTask.objects.filter(workflow_id=workflow_id).first()
    if not task:
        return JsonResponse({"ok": False, "error": "task 不存在"}, status=404)
    if task.status not in ("success", "failed", "cancelled"):
        return JsonResponse({
            "ok": False,
            "error": f"当前状态 {task.status}，只能在终态后回滚",
        }, status=409)

    # drop 影子表（如果存在）
    instance = task.workflow.instance if task.workflow_id else None
    dropped = []
    errors = []
    if instance:
        try:
            from .db import _get_creds
            import pymysql
            user, password, (host, port) = _get_creds(instance)
            conn = pymysql.connect(
                host=host, port=port, user=user, password=password,
                database=task.db_name, connect_timeout=5, autocommit=True,
            )
            try:
                with conn.cursor() as cur:
                    for tbl in [task.ghost_table_name, f"_{task.table_name}_del"]:
                        if not tbl:
                            continue
                        try:
                            cur.execute(f"DROP TABLE IF EXISTS `{task.db_name}`.`{tbl}`")
                            dropped.append(tbl)
                        except Exception as exc:  # noqa: BLE001
                            errors.append(f"{tbl}: {exc}")
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"connect: {exc}")

    task.status = "rolled_back"
    task.finished_at = timezone.now()
    task.error_message = (task.error_message or "") + f"\n[rollback] dropped={dropped} errors={errors}"
    task.save()

    logger.info("gh-ost rolled back: task=%s dropped=%s", task.id, dropped)
    return JsonResponse({
        "ok": True,
        "status": task.status,
        "dropped": dropped,
        "errors": errors,
    })


# ===========================================================================
# 视图：取消
# ===========================================================================
@login_required
@require_POST
def cancel(request: HttpRequest, workflow_id: int) -> JsonResponse:
    """取消 task：SIGTERM gh-ost 进程 + 标 cancelled。"""
    task = DdlGhostTask.objects.filter(workflow_id=workflow_id).first()
    if not task:
        return JsonResponse({"ok": False, "error": "task 不存在"}, status=404)
    if task.is_terminal:
        return JsonResponse({
            "ok": False,
            "error": f"已终态（{task.status}），不能取消",
        }, status=409)

    # 停 gh-ost 进程
    if task.ghost_pid:
        stop_ghost_process(task.ghost_pid, timeout=5)

    task.status = "cancelled"
    task.finished_at = timezone.now()
    task.error_message = "用户手动取消"
    task.save()

    # 钉钉通知
    try:
        from .services.notify import notify_terminal
        notify_terminal(task)
    except Exception:  # noqa: BLE001
        logger.exception("notify_terminal failed in cancel")

    logger.info("gh-ost cancelled task_id=%s user=%s", task.id, request.user.username)
    return JsonResponse({"ok": True, "status": task.status})


# ===========================================================================
# 视图：进度查询（前端 polling，3s 一次）
# ===========================================================================
@login_required
@require_GET
def status(request: HttpRequest, workflow_id: int) -> JsonResponse:
    task = DdlGhostTask.objects.filter(workflow_id=workflow_id).first()
    if not task:
        return JsonResponse({"ok": False, "error": "task 不存在"}, status=404)
    return JsonResponse({
        "ok": True,
        "task_id": task.id,
        "status": task.status,
        "current_stage": task.current_stage,
        "progress": {
            "pct": task.progress_pct,
            "rows_copied": task.progress_rows_copied,
            "rows_total": task.progress_rows_total,
            "speed": task.progress_speed_rows_per_sec,
            "eta_seconds": task.progress_eta_seconds,
            "threads_running": task.progress_threads_running,
            "message": task.progress_message,
        },
        "last_heartbeat_at": (
            task.last_heartbeat_at.isoformat() if task.last_heartbeat_at else None
        ),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "duration_seconds": task.duration_seconds,
        "stderr_tail": task.stderr_tail[-2000:],
        "error_message": task.error_message,
    })


# ===========================================================================
# 视图：进度面板页面（Django template + JS polling）
# ===========================================================================
@login_required
@require_GET
def progress_page(request: HttpRequest, workflow_id: int) -> HttpResponse:
    """渲染 gh-ost 进度面板（admin 内部可访问，前端集成留给 beta）。

    模板路径：``sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/progress.html``
    """
    workflow = get_object_or_404(SqlWorkflow, pk=workflow_id)
    task = DdlGhostTask.objects.filter(workflow=workflow).first()
    return render(request, "ddl_gh_ost/progress.html", {
        "workflow": workflow,
        "task": task,
    })
