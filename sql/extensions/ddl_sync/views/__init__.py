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

from ..models import DdlSyncPair, DdlSyncTable, DdlSyncHistory, DdlSyncAuditLog
from ..forms import DdlSyncPairForm


# ============================================================
# CUSTOM-MODIFIED: D35-Pending 操作日志 helper @ 2026-09-09 @ mavis
# 关联: docs/plans/2026-09-04_ddl-sync-w2-d35-pending-audit-log.md
# 业务: 5 view 埋点 emit 6 类 action, 业务方一眼看出谁什么时候做了什么操作
# 设计: 公共 helper 统一写日志, 5 view 各自埋点
# ============================================================
def _write_audit_log(pair, action, operator, detail=None, request=None):
    """统一写 DdlSyncAuditLog, 任何写操作后调一次即可

    ## CUSTOM-MODIFIED: v0.6.0-alpha-1 接 request 自动拿 IP / UA @ 2026-09-10 @ mavis
    ## 关联: docs/plans/2026-09-10_d35-oplog-roadmap.html 阶段 1.5
    ## 历史数据补录场景可传 request=None (v0.6.0-alpha-2 1.1 用, is_backfilled=True 区分)

    Args:
        pair: DdlSyncPair
        action: str (DdlSyncAuditLog.ACTION_CHOICES 之一)
        operator: request.user (或 None, 历史数据补录场景)
        detail: dict (会 json.dumps 成 detail_json, 可选)
        request: HttpRequest (可选, 传了就拿 client_ip / user_agent)
    """
    import json
    # 1.5: 从 request 拿 IP / UA
    client_ip = None
    user_agent = ""
    if request is not None:
        # 优先 X-Forwarded-For (有反代时), 否则 REMOTE_ADDR
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        client_ip = (xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")) or None
        user_agent = (request.META.get("HTTP_USER_AGENT", "") or "")[:256]
    try:
        DdlSyncAuditLog.objects.create(
            pair=pair,
            action=action,
            operator=operator if (operator and getattr(operator, "is_authenticated", False)) else None,
            operator_display=operator.username if (operator and getattr(operator, "is_authenticated", False)) else "",
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else "",
            client_ip=client_ip,
            user_agent=user_agent,
        )
    except Exception:
        # 日志写入失败不应阻塞主操作 (跟 D22 sync_trigger 错误兜底同套路)
        import logging
        logging.getLogger("default").exception("DdlSyncAuditLog 写入失败: pair=%s action=%s", pair.id, action)


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

    ## CUSTOM-MODIFIED: 同步表清单加分页 + 行数选择 @ 2026-09-08 @ mavis
    - tables 分页: 默认 50/页, 可选 50/100/200, URL 加 ?tables_page=N&tables_per_page=50
    - 行数选择下拉: tab 内右上角, 跟 history 导出按钮同一行
    - 实战背景: 业务方库对有 606 张表, 老代码写死 [:200], 看不到 200+ 部分

    ## CUSTOM-MODIFIED: 同步表清单加 server-side 黑白名单筛选 + 搜索 @ 2026-09-09 @ mavis (D38 续 3)
    - URL 加 ?sync_type=whitelist|blacklist&search=keyword
    - 实战背景: 业务方 12:22 反馈"再看看黑白名单筛选问题", 老 client-side JS filter 不持久化 / 分页不感知
    - server-side filter 让 URL 持久化 + 分页按过滤后数量 + 可分享链接
    """
    pair = get_object_or_404(
        DdlSyncPair.objects.select_related("source_instance", "target_instance", "created_by"),
        pk=pair_id,
    )

    # 同步表清单 tab - 同步表清单加分页 + 行数选择 + 黑白名单筛选 + 搜索 (D38 续 3)
    TABLES_PER_PAGE_CHOICES = [50, 100, 200]
    tables_per_page_param = request.GET.get("tables_per_page", 50)
    try:
        tables_per_page = int(tables_per_page_param)
        if tables_per_page not in TABLES_PER_PAGE_CHOICES:
            tables_per_page = 50
    except (ValueError, TypeError):
        tables_per_page = 50
    # 黑白名单 server-side filter (D38 续 3)
    sync_type_filter = request.GET.get("sync_type", "").strip()
    if sync_type_filter not in ("whitelist", "blacklist"):
        sync_type_filter = ""
    # 搜索 server-side filter (D38 续 3)
    search_filter = request.GET.get("search", "").strip()
    tables_qs = pair.tables.all().order_by("sync_type", "table_name")
    if sync_type_filter:
        tables_qs = tables_qs.filter(sync_type=sync_type_filter)
    if search_filter:
        tables_qs = tables_qs.filter(table_name__icontains=search_filter)
    table_count = tables_qs.count()
    tables_paginator = Paginator(tables_qs, tables_per_page)
    tables_page_num = request.GET.get("tables_page", 1)
    try:
        tables_page_obj = tables_paginator.get_page(tables_page_num)
    except Exception:
        tables_page_obj = tables_paginator.get_page(1)
    tables = tables_page_obj.object_list

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

    # CUSTOM-MODIFIED: D35-Pending 操作日志 tab @ 2026-09-09 @ mavis
    # 关联: docs/plans/2026-09-04_ddl-sync-w2-d35-pending-audit-log.md (方案 A 落地)
    ## CUSTOM-MODIFIED: v0.6.0-alpha-1 9 类 action + view 端预解析 detail_json @ 2026-09-10 @ mavis
    ## 1.2 detail_json 表格化: view 端 json.loads -> dict, 模板用 if action 渲染
    ## 关联: docs/plans/2026-09-10_d35-oplog-roadmap.html 阶段 1.2
    ## 9 类 action: create / edit / enable / disable / one_click / bulk_import / add_table / delete_table / transform_change
    # 按时间倒序, 每页 20 条 (跟 history 一致)
    LOGS_PER_PAGE = 20
    audit_logs_qs = pair.audit_logs.select_related("operator").order_by("-created_at")
    audit_logs_count = audit_logs_qs.count()
    audit_logs_paginator = Paginator(audit_logs_qs, LOGS_PER_PAGE)
    audit_logs_page_num = request.GET.get("logs_page", 1)
    try:
        audit_logs_page_obj = audit_logs_paginator.get_page(audit_logs_page_num)
    except Exception:
        audit_logs_page_obj = audit_logs_paginator.get_page(1)
    # 1.2: view 端预解析 detail_json, 模板直接用 if action 渲染
    import json as _json
    audit_logs = []
    for _log in audit_logs_page_obj.object_list:
        _log.detail_parsed = {}
        if _log.detail_json:
            try:
                _log.detail_parsed = _json.loads(_log.detail_json)
            except (ValueError, TypeError):
                _log.detail_parsed = {"_raw": _log.detail_json}
        audit_logs.append(_log)

    context = {
        "pair": pair,
        "tables": tables,
        "table_count": table_count,
        "tables_paginator": tables_paginator,
        "tables_page_obj": tables_page_obj,
        "tables_per_page": tables_per_page,
        "tables_per_page_choices": TABLES_PER_PAGE_CHOICES,
        "sync_type_filter": sync_type_filter,  # D38 续 3 server-side filter
        "search_filter": search_filter,  # D38 续 3 server-side filter
        "history": history,
        "history_count": history_count,
        "history_page_obj": history_page_obj,
        "history_paginator": history_paginator,
        "audit_logs": audit_logs,  # D35-Pending 操作日志
        "audit_logs_count": audit_logs_count,
        "audit_logs_page_obj": audit_logs_page_obj,
        "audit_logs_paginator": audit_logs_paginator,
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
                # CUSTOM-MODIFIED: D35-Pending 操作日志埋点 @ 2026-09-09 @ mavis
                # 关联: docs/plans/2026-09-04_ddl-sync-w2-d35-pending-audit-log.md (方案 A)
                ## CUSTOM-MODIFIED: v0.6.0-alpha-1 埋点加 request 拿 IP/UA @ 2026-09-10 @ mavis
                _write_audit_log(
                    pair=pair, action="create", operator=request.user,
                    detail={"name": pair.name, "sync_mode": pair.sync_mode, "enabled": pair.enabled},
                    request=request,
                )
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
        # CUSTOM-MODIFIED: D35-Pending 操作日志埋点 @ 2026-09-09 @ mavis
        # 关联: docs/plans/2026-09-04_ddl-sync-w2-d35-pending-audit-log.md (方案 A)
        # 业务: 启用/禁用 (D7 阶段 1 设计) 走 pair_edit 改 enabled 字段, 必识别
        #       "仅 enabled 字段变化" 走 enable/disable 独立 action, 其他字段变化走 edit
        # 实战: 之前 D35-Pending 拍板的 pair_toggle 端点一直没实现 (urls.py line 11 注释)
        # 捕获原 enabled 状态, form 校验后再判断
        old_enabled = pair.enabled
        old_sync_mode = pair.sync_mode

        form = DdlSyncPairForm(request.POST, instance=pair)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
                # 重新查一次拿新值 (form.save() 已经 in-place 改)
                new_enabled = pair.enabled
                new_sync_mode = pair.sync_mode

                # 决定 action: 仅 enabled 字段变化 → enable/disable, 其他 → edit
                if new_enabled != old_enabled and new_sync_mode == old_sync_mode:
                    action = "enable" if new_enabled else "disable"
                    ## CUSTOM-MODIFIED: v0.6.0-alpha-1 enable/disable 详情升级 @ 2026-09-10 @ mavis
                    ## 1.3 库对前后 diff: 加 who/when/operate_from/operate_to 字段
                    detail = {
                        "from": old_enabled,
                        "to": new_enabled,
                        "operate_from": old_enabled,  # D35 老 schema 兼容
                        "operate_to": new_enabled,
                    }
                else:
                    action = "edit"
                    ## CUSTOM-MODIFIED: v0.6.0-alpha-1 edit 详情升级, 记录 old/new 实际值 @ 2026-09-10 @ mavis
                    ## 1.3 库对前后 diff: changed_fields + changes 字段 (每个字段 old/new)
                    ## 关联: docs/plans/2026-09-10_d35-oplog-roadmap.html 阶段 1.3
                    changed_fields = [k for k in form.changed_data if k != "updated_at"]
                    # 实际 old/new 值 (form.initial 是原值, form.cleaned_data 是新值)
                    changes = {}
                    for f in changed_fields:
                        old_val = form.initial.get(f)
                        new_val = form.cleaned_data.get(f)
                        # JSONField (pending_tables / filter_rule) 已经是 dict, 不用 dump
                        if isinstance(old_val, (dict, list)):
                            changes[f] = {"old": old_val, "new": new_val}
                        else:
                            changes[f] = {"old": old_val, "new": new_val}
                    detail = {
                        "changed_fields": changed_fields,
                        "changes": changes,
                        "enabled": {"from": old_enabled, "to": new_enabled} if new_enabled != old_enabled else None,
                    }

                ## CUSTOM-MODIFIED: v0.6.0-alpha-1 埋点加 request 拿 IP/UA @ 2026-09-10 @ mavis
                _write_audit_log(pair=pair, action=action, operator=request.user, detail=detail, request=request)
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
