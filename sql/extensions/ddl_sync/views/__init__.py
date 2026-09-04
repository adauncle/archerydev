"""DDL 跨库同步 views —— 库对管理 view

## CUSTOM-MODIFIED: v0.5.0-alpha DDL 跨库同步 views @ 2026-09-01 @ mavis
设计参考: docs/designs/2026-09-01_ddl-sync-implementation-design.md §1 §2

D7 阶段 1 包含 4 个 view (库对管理 CRUD):
- pair_list — 库对列表 (DBA 视角)
- pair_detail — 库对详情 (4 tab + 5 按钮, D8 写模板 + JS)
- pair_create — 创建库对
- pair_edit — 编辑库对

5 AJAX 端点 (D8 写):
- compute_diff / one_click_setup / bulk_import / add_table / history_list

4 perm 4 判定 (跟 8/12 gh-ost list 套路):
- 业务 RD 看不到库对管理菜单 (跳 history_list 自己的)
- DBA 组长: view + add + change + delete 全
- DBA 执行: view + change (不能 delete)
- 副总/superuser: 全部
"""

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from sql.models import Users

from ..models import DdlSyncPair, DdlSyncTable, DdlSyncHistory
from ..forms import DdlSyncPairForm


@permission_required("ddl_sync.view_ddlsyncpair", raise_exception=True)
def pair_list(request):
    """库对列表页 - DBA 视角

    4 perm 4 判定: view 必有
    显示所有库对 (DBA 视角), 业务 RD 用 history_list 自己的
    """
    # 搜索 + 过滤
    keyword = request.GET.get("keyword", "").strip()
    sync_mode_filter = request.GET.get("sync_mode", "").strip()
    enabled_filter = request.GET.get("enabled", "").strip()

    qs = DdlSyncPair.objects.select_related("source_instance", "target_instance", "created_by").annotate(
        table_count=Count("tables"),
        history_count=Count("history"),
    )
    if keyword:
        qs = qs.filter(
            Q(name__icontains=keyword) |
            Q(source_db__icontains=keyword) |
            Q(target_db__icontains=keyword)
        )
    if sync_mode_filter:
        qs = qs.filter(sync_mode=sync_mode_filter)
    if enabled_filter == "true":
        qs = qs.filter(enabled=True)
    elif enabled_filter == "false":
        qs = qs.filter(enabled=False)

    # 分页
    paginator = Paginator(qs, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "keyword": keyword,
        "sync_mode_filter": sync_mode_filter,
        "enabled_filter": enabled_filter,
        "total_count": paginator.count,
    }
    return render(request, "ddl_sync/pair_list.html", context)


@permission_required("ddl_sync.view_ddlsyncpair", raise_exception=True)
def pair_detail(request, pair_id):
    """库对详情页 - 4 tab + 5 按钮 (D7 阶段 1 只占位, D8 写模板 + JS)

    ## CUSTOM-MODIFIED: D33 同步历史加分页 + 导出 Excel 入口 @ 2026-09-04 @ mavis
    - history 分页: 每页 20 条, URL 加 ?history_page=N
    - 导出按钮: tab 内右上角, 跳 /ddl_sync/pair/<id>/history_export/
    - 实战背景: 业务方长期使用后, 库对历史可能积累到 100+ 条, 单页 50 行太多
    """
    pair = get_object_or_404(
        DdlSyncPair.objects.select_related("source_instance", "target_instance", "created_by"),
        pk=pair_id,
    )

    # 同步表清单 tab (前 200 张, 分页)
    tables = pair.tables.all().order_by("sync_type", "table_name")[:200]
    table_count = pair.tables.count()

    # 同步历史 tab - D33 改: 加分页 (每页 HISTORY_PER_PAGE 条)
    HISTORY_PER_PAGE = 20
    history_qs = pair.history.select_related("source_workflow", "target_workflow").order_by("-created_at")
    history_count = history_qs.count()
    history_paginator = Paginator(history_qs, HISTORY_PER_PAGE)
    history_page_num = request.GET.get("history_page", 1)
    try:
        history_page_obj = history_paginator.get_page(history_page_num)
    except Exception:
        history_page_obj = history_paginator.get_page(1)
    history = history_page_obj.object_list

    context = {
        "pair": pair,
        "tables": tables,
        "table_count": table_count,
        "history": history,
        "history_count": history_count,
        "history_page_obj": history_page_obj,
        "history_paginator": history_paginator,
    }
    return render(request, "ddl_sync/pair_detail.html", context)


@permission_required("ddl_sync.view_ddlsynctable", raise_exception=True)
@require_http_methods(["GET"])
def pair_history_export(request, pair_id):
    """导出库对同步历史为 Excel (.xlsx)

    ## CUSTOM-MODIFIED: D33 同步历史导出 Excel @ 2026-09-04 @ mavis
    - 用 openpyxl 写 .xlsx (项目 requirements.txt 已依赖 openpyxl==3.1.5)
    - 字段: ID / 表名 / 业务库工单 / 历史库镜像工单 / 状态 / 创建时间 / 完成时间 / 错误信息
    - 文件名: ddl_sync_history_<pair_id>_<timestamp>.xlsx (ASCII safe, 防 GBK 编码)
    - 业务方需求: 同步历史多了, 需要 Excel 导出做业务汇报 + 离线分析
    """
    from openpyxl import Workbook
    from django.utils import timezone

    pair = get_object_or_404(
        DdlSyncPair.objects.select_related("source_instance", "target_instance"),
        pk=pair_id,
    )
    histories = pair.history.select_related("source_workflow", "target_workflow").order_by("-created_at")

    wb = Workbook()
    ws = wb.active
    ws.title = "sync_history"
    headers = ["ID", "表名", "业务库工单", "历史库镜像工单", "状态", "创建时间", "完成时间", "错误信息"]
    ws.append(headers)
    # 表头加粗
    from openpyxl.styles import Font, Alignment
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
    # 列宽
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 16
    ws.column_dimensions["F"].width = 20
    ws.column_dimensions["G"].width = 20
    ws.column_dimensions["H"].width = 50

    for h in histories:
        ws.append([
            h.id,
            h.table_name,
            h.source_workflow_id or "",
            h.target_workflow_id or "",
            h.get_sync_status_display(),
            h.created_at.strftime("%Y-%m-%d %H:%M:%S") if h.created_at else "",
            h.finished_at.strftime("%Y-%m-%d %H:%M:%S") if h.finished_at else "",
            (h.error_message or "")[:1000],  # 截 1000 字避免撑爆
        ])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ddl_sync_history_pair{pair_id}_{timestamp}.xlsx"
    # ASCII 文件名 (中文 filename 在 PowerShell GBK 终端会有编码问题)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


@permission_required("ddl_sync.add_ddlsyncpair", raise_exception=True)
@require_http_methods(["GET", "POST"])
def pair_create(request):
    """创建库对"""
    if request.method == "POST":
        form = DdlSyncPairForm(request.POST)
        if form.is_valid():
            pair = form.save(commit=False)
            pair.created_by = request.user
            try:
                with transaction.atomic():
                    pair.save()
                messages.success(request, f"库对 '{pair.name}' 创建成功")
                return HttpResponseRedirect(reverse("ddl_sync:pair_detail", args=(pair.id,)))
            except Exception as e:
                messages.error(request, f"创建库对失败: {e}")
    else:
        form = DdlSyncPairForm()

    context = {
        "form": form,
        "action": "create",
    }
    return render(request, "ddl_sync/pair_form.html", context)


@permission_required("ddl_sync.change_ddlsyncpair", raise_exception=True)
@require_http_methods(["GET", "POST"])
def pair_edit(request, pair_id):
    """编辑库对"""
    pair = get_object_or_404(DdlSyncPair, pk=pair_id)

    if request.method == "POST":
        form = DdlSyncPairForm(request.POST, instance=pair)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
                messages.success(request, f"库对 '{pair.name}' 更新成功")
                return HttpResponseRedirect(reverse("ddl_sync:pair_detail", args=(pair.id,)))
            except Exception as e:
                messages.error(request, f"更新库对失败: {e}")
    else:
        form = DdlSyncPairForm(instance=pair)

    context = {
        "form": form,
        "pair": pair,
        "action": "edit",
    }
    return render(request, "ddl_sync/pair_form.html", context)
