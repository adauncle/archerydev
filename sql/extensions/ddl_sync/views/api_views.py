"""DDL 跨库同步 5 AJAX 端点

## CUSTOM-MODIFIED: v0.5.0-alpha 5 AJAX 端点 @ 2026-09-01 @ mavis
## 关联 changelog: docs/changelogs/2026-09-01_ddl-sync-w2-d9-perm-guard.md

## CUSTOM-MODIFIED: D9 阶段 2 — 8/13 教训应用 5 个 perm 守卫全改 @ 2026-09-01 @ mavis
## 5 个 `@permission_required(..., raise_exception=True)` 全部改为 `@require_perm(perm_codename)`
## 原因: 8/13 实战 ProgressError 中间件返 HTML 错误页, AJAX 端点前端 await r.text() 拿到整页 HTML
## 修复: 自定义 require_perm 装饰器返 JsonResponse({"ok": False, "error": "权限不足..."}, status=403)
## 验证: curl 测 403 返 JSON 不返 HTML

设计参考: docs/designs/2026-09-01_ddl-sync-implementation-design.md §2.2

5 AJAX 端点契约 (W1-D3 §2.2):

- POST /ddl_sync/pair/<int:pair_id>/compute_diff/
  请求: 无 body
  响应: {"ok": true, "data": {"whitelist": [...], "blacklist": [...], "orphans": [...]}, "msg": "..."}

- POST /ddl_sync/pair/<int:pair_id>/one_click_setup/
  请求: {"accept_whitelist": [...], "accept_blacklist": [...]}
  响应: {"ok": true, "data": {"whitelist_count": int, "blacklist_count": int, "duration_ms": int}, "msg": "..."}

- POST /ddl_sync/pair/<int:pair_id>/bulk_import/
  请求: {"table_names": [...], "sync_type": "whitelist"/"blacklist"}
  响应: {"ok": true, "data": {"imported_count": int, "skipped_count": int, "duration_ms": int}, "msg": "..."}

- POST /ddl_sync/pair/<int:pair_id>/add_table/
  请求: {"table_name": str, "sync_type": "whitelist"/"blacklist", "transform_rule": {}}
  响应: {"ok": true, "data": {"table_id": int}, "msg": "..."}

- GET /ddl_sync/history/?pair=<int:pair_id>&status=<str>&page=<int>
  响应: {"ok": true, "data": {"results": [...], "total": int, "page": int}}

避坑 (W1-D3 §8 + W1-D4 §4 实战):
- 8/13 AJAX 守卫: perm 守卫返 JsonResponse(403) 不 raise PermissionDenied (D9 阶段 2 必改)
- 5 类异常: 用户输入错 (400) / 库对配置错 (400) / 库连接错 (500) / DDL 转换错 (400) / target_workflow 执行错 (500)
"""

import json
import logging

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import DdlSyncPair, DdlSyncTable, DdlSyncHistory
from ..services.compute_diff import compute_diff, ComputeDiffError
from ..services.one_click_setup import one_click_setup, OneClickSetupError
from ..services.bulk_import import bulk_import_tables, BulkImportError
from ..services.table_service import add_sync_table, TableServiceError
from ..services.perm_guard import require_perm

logger = logging.getLogger("default")


# ===== 通用辅助 =====

def _json_error(message: str, status: int = 400):
    """统一返 JSON 错误 (避坑 8/13: 不 raise PermissionDenied 返 HTML 错误页)"""
    return JsonResponse({"ok": False, "error": message}, status=status)


def _json_success(data: dict, message: str = ""):
    """统一返 JSON 成功"""
    return JsonResponse({"ok": True, "data": data, "msg": message})


# ===== 端点 1: R2 差集计算 =====

@csrf_exempt
@require_http_methods(["POST"])
@require_perm("change_ddlsyncpair")
def compute_diff_view(request, pair_id):
    """R2 一键配差集计算"""
    pair = get_object_or_404(DdlSyncPair, pk=pair_id)

    if not pair.enabled:
        return _json_error("库对已禁用, 请先启用", status=400)

    try:
        result = compute_diff(pair)
        return _json_success(
            data=result,
            message=f"扫了 {len(result['whitelist']) + len(result['blacklist'])} 张业务库表 + "
                    f"{len(result['whitelist']) + len(result['orphans'])} 张历史库表, "
                    f"差集计算完成",
        )
    except ComputeDiffError as e:
        return _json_error(str(e), status=500)
    except Exception as e:
        logger.exception(f"compute_diff pair={pair_id} 失败")
        return _json_error(f"差集计算失败: {e}", status=500)


# ===== 端点 2: R2 一键配 =====

@csrf_exempt
@require_http_methods(["POST"])
@require_perm("change_ddlsyncpair")
def one_click_setup_view(request, pair_id):
    """R2 一键配 bulk_create 事务"""
    pair = get_object_or_404(DdlSyncPair, pk=pair_id)

    if not pair.enabled:
        return _json_error("库对已禁用, 请先启用", status=400)

    # 解析 body (支持 form data + JSON)
    try:
        if request.content_type == "application/json":
            body = json.loads(request.body)
        else:
            body = request.POST
        accept_whitelist = body.get("accept_whitelist", [])
        accept_blacklist = body.get("accept_blacklist", [])
    except (json.JSONDecodeError, KeyError) as e:
        return _json_error(f"请求体解析失败: {e}", status=400)

    if not isinstance(accept_whitelist, list) or not isinstance(accept_blacklist, list):
        return _json_error("accept_whitelist / accept_blacklist 必须是数组", status=400)

    try:
        result = one_click_setup(pair, accept_whitelist, accept_blacklist)
        total = result["whitelist_count"] + result["blacklist_count"]
        return _json_success(
            data=result,
            message=f"一键配 {total} 张同步表完成 ({result['duration_ms']}ms)",
        )
    except OneClickSetupError as e:
        return _json_error(str(e), status=500)


# ===== 端点 3: R1 批量导入 =====

@csrf_exempt
@require_http_methods(["POST"])
@require_perm("change_ddlsyncpair")
def bulk_import_view(request, pair_id):
    """R1 批量导入 bulk_create 事务"""
    pair = get_object_or_404(DdlSyncPair, pk=pair_id)

    if not pair.enabled:
        return _json_error("库对已禁用, 请先启用", status=400)

    try:
        if request.content_type == "application/json":
            body = json.loads(request.body)
        else:
            body = request.POST
        table_names = body.get("table_names", [])
        sync_type = body.get("sync_type", "whitelist")
    except (json.JSONDecodeError, KeyError) as e:
        return _json_error(f"请求体解析失败: {e}", status=400)

    if not isinstance(table_names, list):
        return _json_error("table_names 必须是数组", status=400)

    try:
        result = bulk_import_tables(pair, table_names, sync_type)
        return _json_success(
            data=result,
            message=f"批量导入 {result['imported_count']} 张完成 "
                    f"(跳过 {result['skipped_count']} 张已存在, {result['duration_ms']}ms)",
        )
    except BulkImportError as e:
        return _json_error(str(e), status=400)


# ===== 端点 4: 单张加同步表 =====

@csrf_exempt
@require_http_methods(["POST"])
@require_perm("add_ddlsynctable")
def add_table_view(request, pair_id):
    """单张加同步表 (R1 兜底)"""
    pair = get_object_or_404(DdlSyncPair, pk=pair_id)

    if not pair.enabled:
        return _json_error("库对已禁用, 请先启用", status=400)

    try:
        if request.content_type == "application/json":
            body = json.loads(request.body)
        else:
            body = request.POST
        table_name = body.get("table_name", "").strip()
        sync_type = body.get("sync_type", "whitelist")
        transform_rule = body.get("transform_rule", {}) or {}
    except (json.JSONDecodeError, KeyError) as e:
        return _json_error(f"请求体解析失败: {e}", status=400)

    if not table_name:
        return _json_error("table_name 不能为空", status=400)

    try:
        obj = add_sync_table(pair, table_name, sync_type, transform_rule)
        return _json_success(
            data={"table_id": obj.id},
            message=f"添加同步表 {table_name} 成功",
        )
    except TableServiceError as e:
        return _json_error(str(e), status=400)


# ===== 端点 5: 同步历史列表 =====

@require_http_methods(["GET"])
@require_perm("view_ddlsyncpair")
def history_list_view(request):
    """同步历史列表 (DBA 视角)"""
    pair_id = request.GET.get("pair", "").strip()
    status_filter = request.GET.get("status", "").strip()
    page_number = int(request.GET.get("page", 1))

    qs = DdlSyncHistory.objects.select_related("pair", "source_workflow", "target_workflow")
    if pair_id:
        qs = qs.filter(pair_id=pair_id)
    if status_filter:
        qs = qs.filter(sync_status=status_filter)
    qs = qs.order_by("-created_at")

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(page_number)

    results = []
    for h in page_obj:
        results.append({
            "id": h.id,
            "pair_id": h.pair_id,
            "pair_name": h.pair.name,
            "source_workflow_id": h.source_workflow_id,
            "target_workflow_id": h.target_workflow_id,
            "table_name": h.table_name,
            "ddl_text": h.ddl_text[:200] + ("..." if len(h.ddl_text) > 200 else ""),
            "transformed_ddl_text": h.transformed_ddl_text[:200] + ("..." if len(h.transformed_ddl_text) > 200 else ""),
            "sync_status": h.sync_status,
            "error_message": h.error_message,
            "created_at": h.created_at.isoformat() if h.created_at else None,
            "finished_at": h.finished_at.isoformat() if h.finished_at else None,
        })

    return _json_success(
        data={
            "results": results,
            "total": paginator.count,
            "page": page_obj.number,
            "has_next": page_obj.has_next(),
        },
        message=f"返回 {len(results)} 条历史 (共 {paginator.count} 条)",
    )
