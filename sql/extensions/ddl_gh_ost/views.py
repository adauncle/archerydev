"""gh-ost 二次开发 — Django 视图。

## CUSTOM-MODIFIED: v0.4.5-alpha 加 rebuild 端点 @ 2026-08-06 @ mavis
关联设计: docs/designs/2026-08-05_gh-ost-product-design.html v0.4.5 §5

alpha 阶段暴露：
    - ``/gh_ost/precheck/<workflow_id>/`` POST  跑预检（仅 admin/staff 可见）
    - ``/gh_ost/enable/<workflow_id>/``  POST  启用 gh-ost + 写 task
    - ``/gh_ost/start/<workflow_id>/``   POST  启动（alpha: 标 running，不真起进程）
    - ``/gh_ost/cancel/<workflow_id>/``  POST  取消
    - ``/gh_ost/status/<workflow_id>/``  GET   进度查询（前端 polling）
    - ``/gh_ost/progress/<workflow_id>/`` GET  渲染进度面板（Django template + JS polling）

v0.4.5-alpha 新增（碎片回收）：
    - ``/gh_ost/rebuild/list/?instance_id=N`` GET   列 instance 下可重建表（DBA 选表用）
    - ``/gh_ost/rebuild/start/``             POST  触发 rebuild task（写 task + 启 gh-ost + poller）

## CUSTOM-MODIFIED: gh-ost 任务管理列表页 @ 2026-08-12 @ mavis
## 关联: docs/designs/2026-08-05_gh-ost-product-design.html v0.3.0 完整版 §"DBA admin 列表页"
## 业务: Django admin 后台有 ext_ddl_ghost_task, 但 DBA 不知道去 admin 后台翻。
##       这个独立页面挂在 Archery 主菜单"DBA 工具"下, 列表 + 状态统计 + 取消/重试/回滚 一站式。
## CUSTOM-MODIFIED: 任务列表页 perm 守卫 (view_ddlghosttask) @ 2026-08-12 @ mavis
## 关联: docs/changelogs/2026-08-12_gh-ost-task-list-permission.md
## 业务: 跟其他 SQL 页面一样可分给不同权限组, 由 DBA 在 admin 后台点"权限组"分配。
##       Django admin 自动给 DdlGhostTask 注册 4 个标准 perm (view/add/change/delete),
##       无需 migration, DBA 勾选即生效。
    - ``/gh_ost/admin_list/``  GET   任务管理列表 (需 ``ddl_gh_ost.view_ddlghosttask`` 权限)

设计参考：docs/designs/2026-08-05_gh-ost-product-design.html §6/§10
"""

import json
import logging
import re
from typing import Optional

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_GET, require_POST

from sql.models import Instance, SqlWorkflow, SqlWorkflowContent

from .models import DdlGhostTask
from .services.db import _get_creds
from .services.poller import start_poller
from .services.precheck import run_all_prechecks
from .services.rebuild import start_rebuild_process
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
    result = _enable_ghost_for_workflow(workflow, created_by=request.user.username)
    status_code = 200 if result["ok"] else (
        400 if "error" in result else 422
    )
    return JsonResponse(result, status=status_code)


## CUSTOM-MODIFIED: v0.3.0-beta 提交页集成 —— 抽 helper 函数让 WorkflowSubmit.post 复用
## 核心逻辑：parse + precheck + 写 DdlGhostTask。返回 dict 给上层自行序列化。
## @ 2026-08-10 @ mavis
def _enable_ghost_for_workflow(workflow: SqlWorkflow, created_by: str) -> dict:
    """对工单启用 gh-ost：parse + precheck + 写 DdlGhostTask。

    Returns:
        {"ok": True,  "passed": True,  "summary": ..., "task_id": ..., "status": "queued"}
        {"ok": False, "passed": False, "summary": ..., "checks": [...], "task_id": ...} (precheck 未过)
        {"ok": False, "error": "未找到 ALTER TABLE 语句"}
        {"ok": False, "error": "task 已在执行中（status=...），不能重复启用"}
    """
    parsed = _parse_first_alter(_workflow_sql_text(workflow))
    if not parsed:
        return {"ok": False, "error": "未找到 ALTER TABLE 语句"}

    db_name = parsed["db"] or workflow.db_name
    table_name = parsed["table"]

    # 已经存在 task？
    existing = DdlGhostTask.objects.filter(workflow=workflow).first()
    if existing and existing.status in ("running", "cut_over", "queued"):
        return {
            "ok": False,
            "error": f"task 已在执行中（status={existing.status}），不能重复启用",
        }

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
            passed=False, report=report, created_by=created_by,
        )
        return {
            "ok": False,
            "passed": False,
            "summary": report["summary"],
            "checks": report["checks"],
            "task_id": task.id,
        }

    # 预检通过 → 写 task（status=queued，alpha 阶段不进 running）
    task = _upsert_task(
        workflow, parsed, db_name, table_name,
        passed=True, report=report, created_by=created_by,
    )
    return {
        "ok": True,
        "passed": True,
        "summary": report["summary"],
        "task_id": task.id,
        "status": task.status,
    }


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

    ## CUSTOM-MODIFIED: 端点加 perm 守卫 (change_ddlghosttask) @ 2026-08-13 @ mavis
    ## 关联: docs/changelogs/2026-08-13_gh-ost-action-endpoint-perm.md
    ## 业务: A 方案, 跟 cancel/retry/rollback 同样套路, RD 没 perm 时返 403 JSON。
    ##      进度面板"启动 gh-ost"按钮 AJAX 调用, 防止 RD 绕过前端守卫直接 fetch。
    """
    perm_resp = _require_change_perm(request, "start")
    if perm_resp is not None:
        return perm_resp
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
    """重试 task：仅当 status in (failed, cancelled) 才能 retry。重新走 start 路径。

    ## CUSTOM-MODIFIED: 端点加 perm 守卫 (change_ddlghosttask) @ 2026-08-13 @ mavis
    ## 关联: docs/changelogs/2026-08-13_gh-ost-action-endpoint-perm.md
    ## 业务: A 方案, 跟 view_ddlghosttask 同样套路, DBA 在 admin 后台分配,
    ##      0 DB 改动, 端点是硬墙 (RD 怎么点都 403)。
    """
    perm_resp = _require_change_perm(request, "retry")
    if perm_resp is not None:
        return perm_resp
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

    ## CUSTOM-MODIFIED: 端点加 perm 守卫 (change_ddlghosttask) @ 2026-08-13 @ mavis
    ## 关联: docs/changelogs/2026-08-13_gh-ost-action-endpoint-perm.md

    注意：cut-over 成功（status=success）后影子表是 _<table>_gho，
    实际表已经 rename 过了，回滚意味着 drop 影子表 + 改 status=rolled_back。
    但 cut-over 成功后影子表其实已经不在了，需要 drop 旧表（如果存在）。
    """
    perm_resp = _require_change_perm(request, "rollback")
    if perm_resp is not None:
        return perm_resp
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
    """取消 task：SIGTERM gh-ost 进程 + 标 cancelled。

    ## CUSTOM-MODIFIED: 端点加 perm 守卫 (change_ddlghosttask) @ 2026-08-13 @ mavis
    ## 关联: docs/changelogs/2026-08-13_gh-ost-action-endpoint-perm.md
    """
    perm_resp = _require_change_perm(request, "cancel")
    if perm_resp is not None:
        return perm_resp
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
## CUSTOM-MODIFIED: v0.3.0-beta 前端 UI 集成 —— 允许 progress 页被 detail.html iframe 嵌入
## Django 默认 XFrameOptionsMiddleware 设 X-Frame-Options: DENY，拒绝所有 iframe
## @ 2026-08-10 @ mavis
@xframe_options_exempt
def progress_page(request: HttpRequest, workflow_id: int) -> HttpResponse:
    """渲染 gh-ost 进度面板（admin 内部可访问，前端集成留给 beta）。

    模板路径：``sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/progress.html``
    """
    workflow = get_object_or_404(SqlWorkflow, pk=workflow_id)
    task = DdlGhostTask.objects.filter(workflow=workflow).first()
    ## CUSTOM-MODIFIED: v0.3.0-beta 视图 —— is_admin_user 给模板判断"查看 admin 详情"按钮显隐
    ## 仅 is_superuser 才显示（避免普通用户点跳 admin 登录页 UX 差）
    ## @ 2026-08-10 @ mavis
    is_admin_user = bool(request.user.is_authenticated and request.user.is_superuser)
    ## CUSTOM-MODIFIED: progress.html 加 is_admin_or_dba 控制"启动 gh-ost" / "取消迁移" 按钮显隐 @ 2026-08-13 @ mavis
    ## 关联: docs/changelogs/2026-08-13_gh-ost-progress-page-button-perm.md
    ## 业务: 跟 task_list.html 列表行守卫保持一致, RD 视角 (oa_tester_1) 看进度面板不应该看到运维操作按钮。
    ##      _is_admin_or_dba helper 跟 admin_list 视图共用 (DBA 跟 DBA 组长), 跟 _require_change_perm (perm 硬墙) 解耦。
    is_admin_or_dba = _is_admin_or_dba(request.user)
    return render(request, "ddl_gh_ost/progress.html", {
        "workflow": workflow,
        "task": task,
        "is_admin_user": is_admin_user,
        "is_admin_or_dba": is_admin_or_dba,
    })


# ===========================================================================
# CUSTOM-MODIFIED: v0.4.5-alpha 视图 —— 碎片回收 @ 2026-08-06 @ mavis
# 关联设计: docs/designs/2026-08-05_gh-ost-product-design.html v0.4.5 §5
# ===========================================================================

@login_required
@require_GET
def rebuild_list(request: HttpRequest) -> JsonResponse:
    """返回 instance 下可重建的表列表（DBA 选表用）。

    查 INFORMATION_SCHEMA.TABLES，列 InnoDB 表 + DATA_FREE > 0 的表，按碎片率倒序。

    入参:
        GET ?instance_id=N  必填，archery Instance.id

    返回:
        {
            "ok": true,
            "instance_id": N,
            "instance_name": "...",
            "tables": [
                {"db": "archery_dev", "table": "accesscard_black_detail",
                 "data_free_mb": 1024, "size_mb": 4096, "data_free_pct": 25.0},
                ...
            ]
        }

    错误:
        404: instance 不存在
        500: 连 MySQL 失败（dev 134 instance 历史密文需 .env 兜底）

    权限 (8/25 16:09 改 perm 守卫, 跟 rebuild_select_page 一致):
        需 ``ddl_gh_ost.view_ddlghosttask`` perm, 没 perm 返 403 JSON
        (不能 raise PermissionDenied, 否则前端 AJAX 拿到整页 HTML 源码, 8/13 教训)
    """
    # 8/25 改 perm 守卫
    if not request.user.has_perm("ddl_gh_ost.view_ddlghosttask"):
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    "您没有查看碎片回收表列表的权限, 请联系 DBA 在 admin 后台 "
                    "/admin/auth/group/ 权限组中分配 'Can view gh-ost 任务'。"
                ),
            },
            status=403,
        )
    instance_id = request.GET.get("instance_id")
    if not instance_id:
        return JsonResponse({"ok": False, "error": "instance_id 必填"}, status=400)
    try:
        instance = Instance.objects.get(pk=int(instance_id))
    except (Instance.DoesNotExist, ValueError):
        return JsonResponse({"ok": False, "error": f"instance #{instance_id} 不存在"}, status=404)

    # 走 precheck 那套凭据（db.py 内部有 .env 兜底逻辑）
    try:
        user, password, (host, port) = _get_creds(instance)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({
            "ok": False,
            "error": f"取凭据失败：{exc}",
            "hint": "dev 134 instance 是历史 mirage 密文，配置 CUSTOM_GH_OST_PRECHECK_* 兜底",
        }, status=500)

    # 直连 MySQL 查 INFORMATION_SCHEMA（不走 Django ORM）
    import pymysql
    try:
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            connect_timeout=5, autocommit=True,
        )
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({
            "ok": False,
            "error": f"连 MySQL 失败：{exc}",
            "host": host, "port": port,
        }, status=500)

    try:
        with conn.cursor() as cur:
            # 8/25 改: LEFT JOIN INNODB_TABLESPACES 拿 FILE_SIZE (ibd 实际大小),
            #       8.0.22 INFORMATION_SCHEMA.TABLES.DATA_FREE 字段严重虚高
            #       (返回 tablespace 预分配, 不是真可清理碎片, 误导 DBA 看到 99.3% 假象).
            #       真实碎片率 = (FILE_SIZE - DATA - INDEX) / FILE_SIZE
            cur.execute('''
                SELECT t.TABLE_SCHEMA, t.TABLE_NAME,
                       t.DATA_FREE, t.DATA_LENGTH, t.INDEX_LENGTH,
                       COALESCE(its.FILE_SIZE, t.DATA_LENGTH + t.INDEX_LENGTH) AS ibd_size
                FROM INFORMATION_SCHEMA.TABLES t
                LEFT JOIN INFORMATION_SCHEMA.INNODB_TABLESPACES its
                  ON its.NAME = CONCAT(t.TABLE_SCHEMA, '/', t.TABLE_NAME)
                WHERE t.ENGINE = 'InnoDB'
                  AND t.TABLE_SCHEMA NOT IN ('mysql', 'information_schema',
                                           'performance_schema', 'sys')
                  AND t.TABLE_TYPE = 'BASE TABLE'
                ORDER BY t.DATA_FREE DESC
                LIMIT 200
            ''')
            rows = cur.fetchall()
    finally:
        conn.close()

    tables = []
    for schema, name, data_free, data_len, idx_len, ibd_size in rows:
        data_free = data_free or 0
        data_len = data_len or 0
        idx_len = idx_len or 0
        ibd_size = ibd_size or 0
        total_mb = (data_len + idx_len) / 1024 / 1024
        # 真实 ibd 文件大小
        ibd_mb = ibd_size / 1024 / 1024
        # 8/25 改: 用 ibd 实际大小算碎片率, 不用 INFORMATION_SCHEMA.TABLES.DATA_FREE
        # 关联: docs/changelogs/2026-08-25_v0405-fragmentation-algorithm-fix.md
        # 真实 free = ibd 实际 - data - index
        # pct = free / ibd_size
        # 8.0.22 文档: DATA_FREE 字段是 tablespace 预分配, 不代表可清理
        #              实际 ibd 128KB 的表 DATA_FREE 报 9MB (虚高 70 倍)
        real_free_bytes = max(0, ibd_size - data_len - idx_len)
        real_free_mb = real_free_bytes / 1024 / 1024
        pct = (real_free_bytes / ibd_size * 100) if ibd_size > 0 else 0.0
        tables.append({
            "db": schema,
            "table": name,
            "data_free_mb": round(real_free_mb, 2),  # 8/25: 真实 free (ibd - data - idx)
            "size_mb": round(total_mb, 2),
            "ibd_size_mb": round(ibd_mb, 2),          # 8/25 新增: ibd 实际大小
            "data_free_pct": round(pct, 1),             # 8/25: 真实 pct
        })

    return JsonResponse({
        "ok": True,
        "instance_id": instance.id,
        "instance_name": instance.instance_name,
        "tables": tables,
    })


@login_required
@require_POST
def rebuild_start(request: HttpRequest) -> JsonResponse:
    """DBA 选表触发 rebuild task。

    入参（JSON body 或 form-encoded）:
        instance_id: int, 必填
        db: str, 必填
        table: str, 必填

    流程:
        1. 灰度开关校验（CUSTOM_GH_OST_REBUILD_ENABLED）
        2. 入参校验
        3. 同表冲突检查（已有 running/queued 则拒绝）
        4. 写 task（task_type=rebuild, workflow=NULL, target_table=db.table）
        5. start_rebuild_process Popen gh-ost
        6. 写 PID + started_at + status=running
        7. 启动 poller 3s 轮询

    返回:
        {"ok": true, "task_id": N, "status": "running", "pid": P, "target_table": "db.table"}

    权限 (8/25 16:09 改 perm 守卫, 触发动作比 view 更严):
        需 ``ddl_gh_ost.add_ddlghosttask`` perm (Django admin 自动注册的标准 perm)。
        跟 view 守卫的区别: view 让人"看", add 让人"做"。
        触发 rebuild 是"做"动作, 必须 add perm。
        superuser 自动通过, 没 perm 返 403 JSON (不 raise PermissionDenied, 8/13 教训)。
    """
    # 0. perm 守卫 (8/25 加, add_ddlghosttask 比 view_ddlghosttask 更严)
    if not request.user.has_perm("ddl_gh_ost.add_ddlghosttask"):
        logger.warning(
            "用户 %s 访问 /gh_ost/rebuild/start/ 被拒: 无 add_ddlghosttask 权限",
            request.user.username,
        )
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    "您没有触发碎片回收的权限, 请联系 DBA 在 admin 后台 "
                    "/admin/auth/group/ 权限组中分配 'Can add gh-ost 任务'。"
                ),
            },
            status=403,
        )

    # 1. 灰度开关
    if not getattr(settings, "CUSTOM_GH_OST_REBUILD_ENABLED", True):
        return JsonResponse({
            "ok": False,
            "error": "rebuild 功能未启用（设 CUSTOM_GH_OST_REBUILD_ENABLED=True 开启）",
        }, status=403)

    # 2. 入参（兼容 form-encoded + JSON body）
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "JSON body 解析失败"}, status=400)
        instance_id = payload.get("instance_id")
        db = payload.get("db")
        table = payload.get("table")
    else:
        instance_id = request.POST.get("instance_id")
        db = request.POST.get("db")
        table = request.POST.get("table")

    if not all([instance_id, db, table]):
        return JsonResponse({
            "ok": False,
            "error": "instance_id / db / table 必填",
        }, status=400)
    try:
        instance = Instance.objects.get(pk=int(instance_id))
    except (Instance.DoesNotExist, ValueError):
        return JsonResponse({"ok": False, "error": f"instance #{instance_id} 不存在"}, status=404)

    ## CUSTOM-MODIFIED: v0.4.5-alpha 改 409 拒绝为排队入队 @ 2026-08-06 @ mavis
    ## CUSTOM-MODIFIED: v0.4.5-alpha 修 queue 漏洞加 instance 字段 @ 2026-08-10 @ mavis
    ## CUSTOM-MODIFIED: v0.4.5 拍板改 ENGINE+ROW_FORMAT+CHARSET @ 2026-08-13 @ mavis
    # 3. 查原表属性, 拼 alter 子句 (8/13 拍板)
    # 业务: rebuild 任务触发时查 information_schema.tables 拿原表 ENGINE/ROW_FORMAT/CHARSET/COLLATION,
    #       拼 ENGINE+ROW_FORMAT+CHARSET 形式的 alter (3 层防护确保 5.7/8.0 都触发物理重写,
    #       字符集不漂, COMMENT 业务描述保留).
    table_info = _fetch_table_info_for_rebuild(instance, db, table)
    rebuild_alter = _build_rebuild_alter_clause(table_info)

    # 4. 写 task（直接入队，queue 自动推进）
    # 同表已有 running/cut_over 任务时，本 task 进入 queued 状态等前序完成
    task = DdlGhostTask.objects.create(
        workflow=None,           # rebuild 不挂工单
        task_type="rebuild",
        db_name=db,
        table_name=table,
        target_table=f"{db}.{table}",
        instance=instance,        # CUSTOM: rebuild 任务必填 instance（gh-ost 连接凭据源）
        enabled=True,
        status="queued",
        created_by=request.user.username,
        max_load_threads_running=30,
        timeout_seconds=7200,
        # 8/13 拍板: 5 字段记录"这次 rebuild 改了什么"
        rebuilt_charset=table_info["charset"],
        rebuilt_row_format=table_info["row_format"],
        rebuilt_collation=table_info["collation"],
        rebuilt_alter_full=rebuild_alter,
    )
    logger.info(
        "rebuild task created: task_id=%s db=%s table=%s user=%s alter=%s",
        task.id, db, table, request.user.username, rebuild_alter,
    )

    # 4. 调 queue 推进 —— 如果同表无 running 任务，本 task 立即启动；否则排队等
    from .services.queue import get_queue_position, try_advance_queue
    queue_pos_before = get_queue_position(task)
    advanced = try_advance_queue(db, table)
    # 重新读 task 拿最新 status（queue 推进会改 status / ghost_pid / started_at）
    task.refresh_from_db()
    if advanced is None:
        # queue 空，理论上不可能（本 task 刚 create），但兜底
        return JsonResponse({"ok": False, "error": "queue 推进异常，请联系 DBA"}, status=500)
    if task.id != advanced.id:
        # 推进的是别人（前面有任务），本 task 排队
        return JsonResponse({
            "ok": True,
            "task_id": task.id,
            "status": task.status,
            "queue_position": queue_pos_before,
            "target_table": task.target_table,
            "advanced_task_id": advanced.id,
            "msg": f"已入队，前面 task #{advanced.id} 在执行",
        })

    # 5. 本 task 已被 queue 推进，PID 写好，poller 启了
    logger.info(
        "rebuild task started: task_id=%s pid=%s target=%s user=%s",
        task.id, task.ghost_pid, task.target_table, request.user.username,
    )
    return JsonResponse({
        "ok": True,
        "task_id": task.id,
        "status": task.status,
        "pid": task.ghost_pid,
        "target_table": task.target_table,
    })


# ===========================================================================
# CUSTOM-MODIFIED: v0.4.5-alpha 视图 —— rebuild 进度面板 + 状态查询 @ 2026-08-06 @ mavis
# ===========================================================================

@login_required
@require_GET
## CUSTOM-MODIFIED: v0.3.0-beta 前端 UI 集成 —— 允许 rebuild progress 页被 iframe 嵌入
## @ 2026-08-10 @ mavis
@xframe_options_exempt
def rebuild_progress_page(request: HttpRequest, task_id: int) -> HttpResponse:
    """渲染 rebuild 进度面板（admin 内部可访问）。

    模板路径:``sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/progress_rebuild.html``

    权限 (8/25 16:09 改 perm 守卫, 跟 rebuild_select_page 一致):
        需 ``ddl_gh_ost.view_ddlghosttask`` perm, 没 perm 返 403 HTML 错误页
        (跟 admin_list 一致, render 端点用 raise PermissionDenied 即可)
    """
    # 8/25 加 perm 守卫
    if not request.user.has_perm("ddl_gh_ost.view_ddlghosttask"):
        raise PermissionDenied(
            "您没有查看 gh-ost 任务进度的权限, 请联系 DBA 在 admin 后台 "
            "/admin/auth/group/ 权限组中分配 'Can view gh-ost 任务'。"
        )
    task = get_object_or_404(DdlGhostTask, pk=task_id, task_type="rebuild")
    return render(request, "ddl_gh_ost/progress_rebuild.html", {
        "task": task,
    })


@login_required
@require_GET
def rebuild_status(request: HttpRequest, task_id: int) -> JsonResponse:
    """rebuild 任务进度查询（前端 polling 3s 一次，复用 ghost status 字段）。

    权限 (8/25 16:09 加 perm 守卫, 跟 rebuild_list 一致):
        需 ``ddl_gh_ost.view_ddlghosttask`` perm, 没 perm 返 403 JSON
        (AJAX polling 端点必须返 JSON, 不能 raise, 8/13 教训)

    入参:
        GET /gh_ost/rebuild/status/<task_id>/

    返回:
        与 ghost status 端点相同字段（pct / rows / speed / eta / threads_running / message 等）
    """
    # 8/25 加 perm 守卫 (status 是 AJAX polling 端点, 返 JSON 不用 raise)
    if not request.user.has_perm("ddl_gh_ost.view_ddlghosttask"):
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    "您没有查看 gh-ost 任务状态的权限, 请联系 DBA 在 admin 后台 "
                    "/admin/auth/group/ 权限组中分配 'Can view gh-ost 任务'。"
                ),
            },
            status=403,
        )
    task = DdlGhostTask.objects.filter(pk=task_id, task_type="rebuild").first()
    if not task:
        return JsonResponse({"ok": False, "error": "rebuild task 不存在"}, status=404)
    return JsonResponse({
        "ok": True,
        "task_id": task.id,
        "task_type": task.task_type,
        "target_table": task.target_table,
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
# CUSTOM-MODIFIED: gh-ost 任务管理列表页 @ 2026-08-12 @ mavis
# 关联设计: docs/designs/2026-08-05_gh-ost-product-design.html v0.3.0 §"DBA admin 列表页"
# 业务背景: Django admin 后台有 ext_ddl_ghost_task, 但 DBA 不知道去 admin 后台翻。
#           这是一个独立的产品级页面, 挂在 Archery 主菜单, 列表 + 状态统计 + 取消/重试/回滚 一站式。
# 关联 changelog: docs/changelogs/2026-08-12_gh-ost-task-list-page.md
# ===========================================================================

@login_required
@require_GET
def admin_list(request: HttpRequest) -> HttpResponse:
    """gh-ost 任务管理列表页 (DBA 运维入口).

    URL: GET /gh_ost/admin_list/
    权限: 需 ``ddl_gh_ost.view_ddlghosttask`` 权限 (Django admin 自动注册的标准 perm)。
          superuser 自动通过。DBA 在 admin 后台 ``/admin/auth/group/`` 给目标组
          勾上"Can view gh-ost 任务"即可分配, 无需改代码 / 无需 migration。
          没有 perm 的用户: 菜单不显示 + 直接访问 URL 返回 403。

    可见性 (C 方案延伸, 2026-08-13):
      - ``is_superuser`` 或属于 ``DBA / DBA组长`` 组 → 看全量 (运维视角)
      - 其他有 perm 的用户 (RD 组长 / 高级 RD 等) → 只看自己提交的 task
        (走 ``workflow__engineer == request.user.username`` 过滤)
      - 4 张状态统计卡跟随列表范围 (DBA 看全量, RD 看自己的)

    Query params:
        - task_type: "ghost" | "rebuild" | "" (全部)
        - status: "active" | "success" | "failed" | "cancelled" | "" (全部)
        - q: 关键字 (工单名 / db.表)
    """
    from django.db.models import Q  # 局部 import 避免顶层污染

    # 0. perm 守卫 (跟其他 SQL 页面一致, 可在 admin 后台分配)
    if not request.user.has_perm("ddl_gh_ost.view_ddlghosttask"):
        logger.warning(
            "用户 %s 访问 /gh_ost/admin_list/ 被拒: 无 view_ddlghosttask 权限",
            request.user.username,
        )
        raise PermissionDenied("您没有查看 gh-ost 任务管理列表的权限, 请联系 DBA 在 admin 后台权限组中分配。")

    # 0.5 角色判定 (DBA 视角 vs 提交人视角)
    is_admin_or_dba = _is_admin_or_dba(request.user)

    # 1. 拿筛选参数
    filter_type = request.GET.get("task_type", "").strip()
    filter_status = request.GET.get("status", "").strip()
    filter_q = request.GET.get("q", "").strip()

    # 2. 构造 query
    qs = DdlGhostTask.objects.select_related("workflow", "workflow__instance").order_by("-id")

    if filter_type in ("ghost", "rebuild"):
        qs = qs.filter(task_type=filter_type)

    # status 状态筛选 (active 是多个 in 查询)
    if filter_status == "active":
        qs = qs.filter(status__in=("pending", "precheck_failed", "queued", "running", "cut_over", "connecting", "copying"))
    elif filter_status in ("success", "failed", "cancelled"):
        qs = qs.filter(status=filter_status)

    # 关键字搜索
    if filter_q:
        qs = qs.filter(
            Q(workflow__workflow_name__icontains=filter_q)
            | Q(workflow__db_name__icontains=filter_q)
            | Q(target_table__icontains=filter_q)
        )

    # 2.5 提交人过滤 (C 方案延伸: 非 DBA 视角只看自己)
    #    ghost 场景 task.workflow 有 engineer; rebuild 场景 workflow=NULL,
    #    对 RD 来说 rebuild 看不到任何 task (他本来也不该管 rebuild)。
    if not is_admin_or_dba:
        qs = qs.filter(workflow__engineer=request.user.username)

    # 3. 拿全部 (生产场景 task 量不大, 一次性渲染简单, 真多了再分页)
    tasks = list(qs[:200])  # 限 200 防爆

    # 4. 状态统计 (DBA 看全量, RD 看自己的 — 跟列表范围一致)
    stat_qs = DdlGhostTask.objects.all()
    if not is_admin_or_dba:
        stat_qs = stat_qs.filter(workflow__engineer=request.user.username)
    all_count = stat_qs.count()
    active_count = stat_qs.filter(
        status__in=("pending", "precheck_failed", "queued", "running", "cut_over", "connecting", "copying")
    ).count()
    success_count = stat_qs.filter(status="success").count()
    failed_count = stat_qs.filter(status__in=("failed", "rolled_back")).count()

    return render(request, "ddl_gh_ost/task_list.html", {
        "tasks": tasks,
        "total": all_count,
        "active_count": active_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "filter_type": filter_type,
        "filter_status": filter_status,
        "filter_q": filter_q,
        "is_admin_or_dba": is_admin_or_dba,
    })


# ===========================================================================
# CUSTOM-MODIFIED: 任务列表页可见性角色判定 @ 2026-08-13 @ mavis
# 关联: docs/changelogs/2026-08-13_gh-ost-admin-list-scope.md
# 业务: DBA 视角看全量, 普通用户 (RD 等) 只看自己提交的 task。
#       替代 hardcode `is_superuser`, 走 group name 白名单 (DBA / DBA组长),
#       跟 Archery 上游 workflow_audit_setting 审批组命名保持一致。
# ===========================================================================
def _is_admin_or_dba(user) -> bool:
    """判定用户是否"运维视角" — 看 gh-ost 任务全量。

    True:  superuser 或属于 ``DBA`` / ``DBA组长`` 组 → 看全量
    False: 其他用户 → 只看自己提交的 task (workflow.engineer == user.username)

    设计原因: Archery 上游没有统一的 "is_dba" 字段, 审批组 (workflow_audit_setting)
    用 group.id 配, 这里走 group.name 简单白名单。后续若需要更细粒度 (按部门),
    改这里 + task_list.html 头部提示即可, 不影响 perm 守卫。
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=("DBA", "DBA组长")).exists()


# ===========================================================================
# CUSTOM-MODIFIED: v0.4.5 选表页面 (DBA 主动重建入口) @ 2026-08-25 @ mavis
# 关联设计: docs/designs/2026-08-13_v0405-ghost-rebuild-design.md §6.3
# 业务背景:
#   设计稿 §6.3 计划建一个"DBA 选表页面" — 业务前端 3 步流程 (选 instance → 看 top
#   碎片表 → 点开始)。原计划 8/12 写但被 gh-ost 任务管理列表页 + 字段 diff 等优先级
#   挤掉, 8/13 v0.4.5 拍板 3 决策时只补了 admin 后台 batch_rebuild action (方案 A),
#   独立选表页面 (方案 B) 留到 8/25 补。
#   8/25 用户拍板走方案 B: 不进 admin 后台, 主菜单入口一气呵成。
#
# 流程:
#   1. GET /gh_ost/rebuild/select/  → 渲染 select.html, 传可用 instance 列表
#   2. 前端选 instance → AJAX GET /gh_ost/rebuild/list/?instance_id=N 拿 top 表
#   3. 前端勾表 + 点开始 → AJAX POST /gh_ost/rebuild/start/ 触发
#   4. 拿到 task_id → 跳 /gh_ost/rebuild/progress/<task_id>/ 看 polling
# ===========================================================================

@login_required
@require_GET
def rebuild_select_page(request: HttpRequest) -> HttpResponse:
    """DBA 选表页面 —— 业务前端入口（不走 admin 后台）。

    URL: GET /gh_ost/rebuild/select/

    权限 (8/25 16:09 用户拍板改 perm 守卫, 跟 admin_list 一致):
        需 ``ddl_gh_ost.view_ddlghosttask`` perm (Django admin 自动注册的标准 perm)。
        superuser 自动通过。DBA 在 admin 后台 ``/admin/auth/group/`` 给目标组
        勾上 "Can view gh-ost 任务" 即可分配, 无需改代码 / 无需 migration。
        没有 perm 的用户: 菜单不显示 + 直接访问 URL 返回 403。

    设计原因 (8/25 拍板, 跟 admin_list 守卫统一):
        - 之前用 _is_admin_or_dba group 守卫 (写死 DBA/DBA组长), 不可分配
        - 改为 perm 后, 4 个端点 (rebuild_select/list/status/progress) 用 view 守卫,
          rebuild_start 用 add 守卫 (触发动作更严)
        - 110 prod 默认所有 group 都没 perm, RD 默认 403 (跟现状一致)
        - DBA 想临时给运维负责人开放, admin 后台勾 perm 即可, 不需要改代码

    模板: ddl_gh_ost/rebuild_select.html (Element UI + 3 步流程)

    关联 changelog: docs/changelogs/2026-08-25_v0405-rebuild-perm-guard.md
    """
    # 0. perm 守卫 (跟 admin_list 一致, 可在 admin 后台分配)
    if not request.user.has_perm("ddl_gh_ost.view_ddlghosttask"):
        logger.warning(
            "用户 %s 访问 /gh_ost/rebuild/select/ 被拒: 无 view_ddlghosttask 权限",
            request.user.username,
        )
        raise PermissionDenied(
            "您没有访问碎片回收页面的权限, 请联系 DBA 在 admin 后台 "
            "/admin/auth/group/ 权限组中分配 'Can view gh-ost 任务'。"
        )

    # 1. 拿所有 instance 列表, 按 instance_name 排序
    #    设计: 跟 admin_list 一致, 列所有 instance, 不按用户过滤
    #    (DBA 一般有所有 instance 凭据, 走 _get_creds 内部 .env 兜底)
    instances = list(
        Instance.objects.all().order_by("instance_name")
    )

    # 2. 当前 instance_id (URL ?instance_id=N, 用来刷新页面时保留选中)
    try:
        current_instance_id = int(request.GET.get("instance_id", "0") or "0")
    except (TypeError, ValueError):
        current_instance_id = 0

    return render(request, "ddl_gh_ost/rebuild_select.html", {
        "instances": instances,
        "current_instance_id": current_instance_id,
    })


# ===========================================================================
# CUSTOM-MODIFIED: gh-ost 任务运维操作 perm 守卫 (change_ddlghosttask) @ 2026-08-13 @ mavis
# 关联: docs/changelogs/2026-08-13_gh-ost-action-endpoint-perm.md
# 业务: cancel / retry / rollback 3 个端点统一加 perm 守卫, 跟 view_ddlghosttask 同样套路。
#       0 DB 改动, DBA 在 admin 后台勾选 "Can change gh-ost 任务" 即生效。
# ===========================================================================
def _require_change_perm(request, action: str = ""):
    """gh-ost 任务运维操作端点统一 perm 守卫。

    调用方: ``start`` / ``cancel`` / ``retry`` / ``rollback`` 4 端点, 任何登录用户都能访问
            但需要 ``ddl_gh_ost.change_ddlghosttask`` 权限才能执行。

    ## CUSTOM-MODIFIED: 改 return JsonResponse (status=403) 替代 raise PermissionDenied @ 2026-08-13 @ mavis
    ## 关联: docs/changelogs/2026-08-13_gh-ost-action-endpoint-perm.md (后续)
    ## 业务: progress.html 进度面板"启动 gh-ost" / "取消迁移" 按钮 AJAX 调端点。
    ##      RD 没 perm 时, raise PermissionDenied → Django middleware 返 403 HTML 错误页,
    ##      前端 alert() 弹了整页 HTML 源码 ("<!DOCTYPE html>...") 而不是 JSON 错误。
    ##      改成返 JsonResponse 让前端 alert 看到结构化错误信息。

    行为: 没 perm → 返 ``JsonResponse({"ok": False, "error": "..."}, status=403)``
          有 perm → 返 ``None``, 调用方继续执行。

    Returns:
        None: 有 perm, 调用方继续
        JsonResponse (status=403): 没 perm, 调用方直接 return

    Args:
        request: Django request
        action: 端点动作名 (start / cancel / retry / rollback), 仅用于日志记录

    设计原因:
      - 跟 view_ddlghosttask 同样套路, admin 后台 4 个标准 perm 自动注册 (view/add/change/delete)
      - 0 DB 改动, DBA 在 admin 后台 /admin/auth/group/<id>/change/ 勾选即生效
      - superuser 自动通过 (Django has_perm 对 is_superuser 永远 True)
      - 不写死 group name, 跟 view 守卫保持一致 (避免产品混淆)

    与 _is_admin_or_dba 的区别:
      - _is_admin_or_dba: 前端列表页"看全量 vs 看自己" 的角色判定, 跟 group 绑定
      - _require_change_perm: 端点硬墙, 跟 perm 绑定
      - 两者解耦: 列表页可以按角色给某些人看全量, 但端点永远需要 perm
    """
    if not request.user.has_perm("ddl_gh_ost.change_ddlghosttask"):
        logger.warning(
            "用户 %s 访问 gh-ost %s 端点被拒: 无 change_ddlghosttask 权限",
            request.user.username, action or "unknown",
        )
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    f"您没有 gh-ost 任务 {action} 权限。"
                    "请联系 DBA 在 admin 后台 /admin/auth/group/ 权限组中分配 \"Can change gh-ost 任务\"。"
                ),
            },
            status=403,
        )
    return None


# ===========================================================================
# CUSTOM-MODIFIED: v0.4.5 拍板 3 决策改 ENGINE+ROW_FORMAT+CHARSET @ 2026-08-13 @ mavis
# 关联: docs/changelogs/2026-08-13_v0405-rebuilt-fields.md
#       docs/designs/2026-08-13_v0405-ghost-rebuild-design.md §4
# 业务: rebuild 任务触发时查 information_schema.tables 拿原表属性,
#       拼 ENGINE+ROW_FORMAT+CHARSET+COLLATION 形式的 alter (3 层防护确保
#       5.7 触发物理重写, 字符集不漂, COMMENT 业务描述保留).
#
# 8/25 16:55 用户拍板回滚方案 C (改字符集), 因 8.0.22 改 CHARSET 也走 INSTANT
# 跳过, 改碎片率算法 (用 INNODB_TABLESPACES.FILE_SIZE) 才能让 DBA 看到真实碎片率.
# 关联: docs/changelogs/2026-08-25_v0405-fragmentation-algorithm-fix.md
# ===========================================================================
def _fetch_table_info_for_rebuild(instance, db_name: str, table_name: str) -> dict:
    """rebuild 场景专用: 查 information_schema.tables 拿原表 ENGINE/ROW_FORMAT/CHARSET/COLLATION.

    Returns:
        {
            "engine": "InnoDB",
            "row_format": "Dynamic",
            "charset": "utf8mb4",                  # 从 TABLE_COLLATION 解析
            "collation": "utf8mb4_general_ci",
        }

    Raises:
        TableNotExistForRebuildError: 表不存在
    """
    import pymysql
    user, password = (
        instance.get_username_password()
        if hasattr(instance, "get_username_password")
        else (instance.user, instance.password)
    )
    conn = pymysql.connect(
        host=instance.host, port=instance.port, user=user, password=password,
        database=db_name, connect_timeout=5, autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ENGINE, ROW_FORMAT, TABLE_COLLATION "
                "FROM information_schema.tables "
                "WHERE table_schema=%s AND table_name=%s",
                (db_name, table_name),
            )
            row = cur.fetchone()
            if not row:
                raise TableNotExistForRebuildError(
                    f"表 {db_name}.{table_name} 不存在或无权限"
                )
            engine, row_format, collation = row
            # 从 TABLE_COLLATION 提取 charset
            # utf8mb4_general_ci → utf8mb4
            # utf8mb4_bin → utf8mb4
            # latin1_swedish_ci → latin1
            charset = collation.split("_")[0] if "_" in collation else collation
            return {
                "engine": engine,
                "row_format": row_format,
                "charset": charset,
                "collation": collation,
            }
    finally:
        conn.close()


def _build_rebuild_alter_clause(table_info: dict) -> str:
    """rebuild 场景的 alter 子句 (8/13 拍板方案, 8/25 16:55 回滚方案 C 改字符集).

    设计 (3 层防护, 8/13 拍板, 字符集不漂):
        ALTER TABLE t
          ENGINE=InnoDB,                          # 原表就是 InnoDB, no-op (但 5.7 走 COPY 触发)
          ROW_FORMAT=Dynamic,                     # 原表就是 Dynamic, 5.7 走 COPY 触发整表重写
          DEFAULT CHARACTER SET=utf8mb4           # 原表就是 utf8mb4, no-op
          COLLATE=utf8mb4_general_ci;             # 跟原表一致, 0 风险飘字段

    5.7 vs 8.0 行为 (8/25 16:50 重新验证):
        - 5.7: ENGINE 改 InnoDB 走 COPY 触发整表重写, DATA_FREE 归零
        - 8.0.12+: ENGINE 改 InnoDB 改自己走 INSTANT 跳过, 不重写 (8/25 16:50 验)
        - 8.0.22: CHARSET 改自己 / COLLATION 改自己 走 INPLACE 跳过, 不重写 (8/25 16:50 验)
        - 8.0.22: 4 子句全 no-op → MySQL 走完全 INSTANT 跳过, gh-ost 看到 success 但不重写

    8/25 16:55 撤方案 C 原因: 改字符集 (utf8→utf8mb4) 对 8.0.22 也走 INSTANT 跳过,
    反而永久改字符集, 得不偿失. 真实修法: 改碎片率算法 (用 INNODB_TABLESPACES.FILE_SIZE),
    让 DBA 看到真实碎片率, 不被 8.0.22 虚高的 DATA_FREE 字段误导.

    不动 COMMENT 业务描述 (数据治理关键).
    """
    return (
        f"ENGINE={table_info['engine']}, "
        f"ROW_FORMAT={table_info['row_format']}, "
        f"DEFAULT CHARACTER SET={table_info['charset']} "
        f"COLLATE={table_info['collation']}"
    )


class TableNotExistForRebuildError(Exception):
    """rebuild 目标表不存在."""
    pass


# ===========================================================================
# CUSTOM-MODIFIED: v0.3.x 字段 diff 端点 @ 2026-08-12 @ mavis
# 关联: docs/designs/2026-08-12_gh-ost-column-diff-mockup.html
# 业务: SQL 检测结果页 / 详情页大表 alert 都调这个端点, 给 8 维字段 diff + 11 条风险规则
# 关联 changelog: docs/changelogs/2026-08-12_gh-ost-column-diff.md
# ===========================================================================

@login_required
@require_POST
def column_diff(request: HttpRequest) -> JsonResponse:
    """字段 diff 端点.

    URL: POST /gh_ost/column_diff/
    入参 (form data 或 JSON body):
        - instance_id: int (Instance.id)
        - db_name: str
        - sql_content: str (通常是一条 ALTER TABLE)
        - table_name: str (可选, 不传从 SQL 解析)

    返回: 见 services.column_diff.column_diff_full 返回结构

    注: 普通 Django WSGIRequest 没有 .data 属性 (那是 DRF 的), 用 getattr 兜底
    """
    # 兼容 form data 和 JSON body
    def _get(key):
        v = request.POST.get(key)
        if v is None:
            v = getattr(request, "data", {}).get(key)
        return v

    try:
        instance_id = int(_get("instance_id"))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "instance_id 必填且为整数"}, status=400)
    db_name = (_get("db_name") or "").strip()
    sql_content = (_get("sql_content") or "").strip()
    table_name = (_get("table_name") or "").strip() or None

    if not db_name or not sql_content:
        return JsonResponse({"ok": False, "error": "db_name 和 sql_content 必填"}, status=400)

    from sql.models import Instance
    try:
        instance = Instance.objects.get(pk=instance_id)
    except Instance.DoesNotExist:
        return JsonResponse({"ok": False, "error": f"instance {instance_id} 不存在"}, status=404)

    from .services.column_diff import column_diff_full
    result = column_diff_full(instance, db_name, sql_content, table_name=table_name)
    return JsonResponse(result)
