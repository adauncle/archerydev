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
    """库对详情页 - 4 tab + 5 按钮 (D7 阶段 1 只占位, D8 写模板 + JS)"""
    pair = get_object_or_404(
        DdlSyncPair.objects.select_related("source_instance", "target_instance", "created_by"),
        pk=pair_id,
    )

    # 同步表清单 tab (前 200 张, 分页)
    tables = pair.tables.all().order_by("sync_type", "table_name")[:200]
    table_count = pair.tables.count()

    # 同步历史 tab (前 50 条)
    history = pair.history.select_related("source_workflow", "target_workflow").order_by("-created_at")[:50]
    history_count = pair.history.count()

    context = {
        "pair": pair,
        "tables": tables,
        "table_count": table_count,
        "history": history,
        "history_count": history_count,
    }
    return render(request, "ddl_sync/pair_detail.html", context)


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
