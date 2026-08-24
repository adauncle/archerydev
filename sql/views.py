# -*- coding: UTF-8 -*-
import os
import traceback

from django.contrib.auth.decorators import permission_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseRedirect, FileResponse, Http404, JsonResponse
from django.urls import reverse

from django.conf import settings
from common.config import SysConfig
from sql.engines import get_engine, engine_map
from common.utils.permission import superuser_required
from common.utils.convert import Convert
from sql.utils.tasks import task_info
from sql.offlinedownload import OffLineDownLoad
from sql.utils.resource_group import user_groups, user_instances

from .models import (
    Users,
    SqlWorkflow,
    QueryPrivileges,
    ResourceGroup,
    QueryPrivilegesApply,
    Config,
    SQL_WORKFLOW_CHOICES,
    InstanceTag,
    Instance,
    QueryLog,
    ArchiveConfig,
    AuditEntry,
    TwoFactorAuthConfig,
)
from sql.utils.workflow_audit import Audit, AuditV2, AuditException
from sql.utils.sql_review import (
    can_execute,
    can_timingtask,
    can_cancel,
    can_view,
    can_rollback,
)
from common.utils.const import Const, WorkflowType, WorkflowAction
from sql.utils.resource_group import user_groups, user_instances

import logging

logger = logging.getLogger("default")


def index(request):
    index_path_url = SysConfig().get("index_path_url", "sqlworkflow")
    return HttpResponseRedirect(f"/{index_path_url.strip('/')}/")


def login(request):
    """登录页面"""
    if request.user and request.user.is_authenticated:
        return HttpResponseRedirect("/")

    return render(
        request,
        "login.html",
        context={
            "sign_up_enabled": SysConfig().get("sign_up_enabled"),
            "oidc_enabled": settings.ENABLE_OIDC,
            "dingding_enabled": settings.ENABLE_DINGDING,
            "cas_enabled": settings.ENABLE_CAS,
            "oidc_btn_name": SysConfig().get("oidc_btn_name", "以OIDC登录"),
        },
    )


def twofa(request):
    """2fa认证页面"""
    if request.user.is_authenticated:
        return HttpResponseRedirect("/")

    username = request.session.get("user")
    if username:
        verify_mode = request.session.get("verify_mode")
        twofa_enabled = TwoFactorAuthConfig.objects.filter(username=username)
        user_auth_types = [twofa.auth_type for twofa in twofa_enabled]

        auth_types = []
        for user_auth_type in user_auth_types:
            auth_type = {}
            auth_type["code"] = user_auth_type
            if user_auth_type == "totp":
                auth_type["display"] = "Google身份验证器"
            elif user_auth_type == "sms":
                auth_type["display"] = "短信验证码"
            auth_types.append(auth_type)
        if "sms" in user_auth_types:
            phone = TwoFactorAuthConfig.objects.get(
                username=username, auth_type="sms"
            ).phone
        else:
            phone = 0
    else:
        return HttpResponseRedirect("/login/")

    return render(
        request,
        "2fa.html",
        context={
            "verify_mode": verify_mode,
            "auth_types": auth_types,
            "username": username,
            "phone": phone,
        },
    )


@permission_required("sql.menu_dashboard", raise_exception=True)
def dashboard(request):
    """dashboard页面"""
    return render(request, "dashboard.html")


def sqlworkflow(request):
    """SQL上线工单列表页面"""
    user = request.user
    # 过滤筛选项的数据
    filter_dict = dict()
    # 管理员，可查看所有工单
    if user.is_superuser or user.has_perm("sql.audit_user"):
        pass
    # 非管理员，拥有审核权限、资源组粒度执行权限的，可以查看组内所有工单
    elif user.has_perm("sql.sql_review") or user.has_perm(
        "sql.sql_execute_for_resource_group"
    ):
        # 先获取用户所在资源组列表
        group_list = user_groups(user)
        group_ids = [group.group_id for group in group_list]
        filter_dict["group_id__in"] = group_ids
    # 其他人只能查看自己提交的工单
    else:
        filter_dict["engineer"] = user.username
    instance_id = (
        SqlWorkflow.objects.filter(**filter_dict).values("instance_id").distinct()
    )
    instance = Instance.objects.filter(pk__in=instance_id).order_by(
        Convert("instance_name", "gbk").asc()
    )
    resource_group_id = (
        SqlWorkflow.objects.filter(**filter_dict).values("group_id").distinct()
    )
    resource_group = ResourceGroup.objects.filter(group_id__in=resource_group_id)

    return render(
        request,
        "sqlworkflow.html",
        {
            "status_list": SQL_WORKFLOW_CHOICES,
            "instance": instance,
            "resource_group": resource_group,
        },
    )


def sqlexportworkflow(request):
    """SQL数据导出工单列表页面"""
    user = request.user
    # 获取所有配置项
    storage_type = SysConfig().get("storage_type")
    # 离线下载权限判断
    can_offline_download = user.is_superuser or user.has_perm("sql.offline_download")
    # 过滤筛选项的数据
    filter_dict = dict()
    # 管理员，可查看所有工单
    if user.is_superuser or user.has_perm("sql.audit_user"):
        pass
    # 非管理员，拥有审核权限、资源组粒度执行权限的，可以查看组内所有工单
    elif user.has_perm("sql.sql_review") or user.has_perm(
        "sql.sql_execute_for_resource_group"
    ):
        # 先获取用户所在资源组列表
        group_list = user_groups(user)
        group_ids = [group.group_id for group in group_list]
        filter_dict["group_id__in"] = group_ids
    # 其他人只能查看自己提交的工单
    else:
        filter_dict["engineer"] = user.username
    instance_id = (
        SqlWorkflow.objects.filter(**filter_dict).values("instance_id").distinct()
    )
    instance = Instance.objects.filter(pk__in=instance_id).order_by(
        Convert("instance_name", "gbk").asc()
    )
    resource_group_id = (
        SqlWorkflow.objects.filter(**filter_dict).values("group_id").distinct()
    )
    resource_group = ResourceGroup.objects.filter(group_id__in=resource_group_id)

    return render(
        request,
        "sqlexportworkflow.html",
        {
            "status_list": SQL_WORKFLOW_CHOICES,
            "instance": instance,
            "resource_group": resource_group,
            "storage_type": storage_type,
            "can_offline_download": can_offline_download,
        },
    )


@permission_required("sql.sql_submit", raise_exception=True)
def submit_sql(request):
    """提交SQL的页面"""
    user = request.user
    # 获取组信息
    group_list = user_groups(user)

    # 获取系统配置
    archer_config = SysConfig()

    # 主动创建标签
    InstanceTag.objects.get_or_create(
        tag_code="can_write", defaults={"tag_name": "支持上线", "active": True}
    )

    ## CUSTOM-MODIFIED: v0.3.0-beta 提交页 "启用 gh-ost" 勾选联动 —— 模板用 enable_ghost
    ## @ 2026-08-10 @ mavis
    enable_ghost = bool(getattr(settings, "CUSTOM_GH_OST_ENABLED", False))

    context = {
        "group_list": group_list,
        "enable_backup_switch": archer_config.get("enable_backup_switch"),
        "engines": engine_map,
        "enable_ghost": enable_ghost,
    }
    return render(request, "sqlsubmit.html", context)


def _workflow_sql_text(workflow: SqlWorkflow) -> str:
    """拿工单的 SQL 文本, 兼容老工单无 content 行的情况."""
    try:
        return workflow.sqlworkflowcontent.sql_content or ""
    except SqlWorkflowContent.DoesNotExist:
        return ""


def _parse_first_alter(sql_content: str) -> dict:
    """简化版 ALTER 解析, 拿 db + table.

    跟 gh-ost 的 _parse_first_alter 等价, 这里不引跨 app 函数避免启动期循环.
    返回 {"db": str|None, "table": str|None, "full": str|None}, 失败返 None.
    """
    import re
    if not sql_content:
        return None
    m = re.match(
        r"^\s*ALTER\s+TABLE\s+(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?",
        sql_content.strip(),
        re.IGNORECASE,
    )
    if not m:
        return None
    schema = (m.group("schema") or "").strip("`")
    table = (m.group("table") or "").strip("`")
    return {"db": schema or None, "table": table or None, "full": m.group(0)}


def _get_table_size_info(instance, db_name: str, table_name: str) -> dict:
    """CUSTOM: 查 instance 库的某表大小 + 行数.

    返回 {"rows": int, "size_mb": float, "table_name": str}, 查不到返 None.
    用于大表 DDL 防呆检测 (详情页红色 alert + 立即执行 confirm).
    """
    import logging
    logger = logging.getLogger("default")
    if not (instance and db_name and table_name):
        return None
    try:
        # 用 PyMySQL 直连 (走 instance user/password 凭据, 兼容 ssh tunnel 通过查询 engine)
        from sql.models import Instance
        # 取明文凭据
        user, password = instance.get_username_password() if hasattr(instance, "get_username_password") else (instance.user, instance.password)
        host = instance.host
        port = instance.port
        import pymysql
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            database=db_name, connect_timeout=5, autocommit=True,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT TABLE_ROWS, DATA_LENGTH + INDEX_LENGTH "
                    "FROM information_schema.tables "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                    (db_name, table_name),
                )
                row = cur.fetchone()
                if not row:
                    return None
                rows = int(row[0] or 0)
                size_bytes = int(row[1] or 0)
                return {
                    "rows": rows,
                    "size_mb": round(size_bytes / 1024 / 1024, 1),
                    "table_name": table_name,
                }
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        logger.exception("_get_table_size_info failed: %s.%s", db_name, table_name)
        return None


def detail(request, workflow_id):
    """展示SQL工单详细页面"""
    workflow_detail = get_object_or_404(SqlWorkflow, pk=workflow_id)
    audit_handler = AuditV2(workflow=workflow_detail)
    if not can_view(request.user, workflow_id):
        raise PermissionDenied
    review_info = audit_handler.get_review_info()

    ## CUSTOM-MODIFIED: v0.3.0-beta 接前端 UI —— 详情页展示 gh-ost 启用按钮 / 进度面板
    ## 关键修复: 必须前移到 is_can_execute 计算之前，否则 Python UnboundLocalError
    ## 关联设计: docs/designs/2026-08-05_gh-ost-product-design.html §启用 gh-ost
    ## @ 2026-08-10 @ mavis
    ## CUSTOM-MODIFIED: v0.3.0-beta 审批守卫 + lazy auto-enable
    ## - 去掉 manreviewing: 审批前不能点启用 (用户报的真 bug)
    ## - lazy auto-enable: enable_gh_ost=True + status=review_pass + 没 task → 渲染前自动调 _enable_ghost_for_workflow
    ## 关联 changelog: docs/changelogs/2026-08-11_gh-ost-approval-gating.md
    ## @ 2026-08-11 @ mavis
    has_ghost_task = False
    can_enable_ghost = False
    ghost_task = None
    has_active_ghost_task = False  # active task 在跑时禁用原路径"立即执行"按钮
    ghost_task_is_terminal = False  # 终态历史 (UI 区分 active vs terminal)

    # CUSTOM: v0.3.0-beta 大表 DDL 防呆 —— 解析首条 ALTER 查表大小
    ## 业务: 防止 RD 漏勾 gh-ost 时 DBA 走原路径"立即执行" 锁表
    ## 阈值: 行数 ≥ 10w 或 大小 ≥ 100MB 视为大表
    ## @ 2026-08-11 @ mavis
    big_table_alert = None  # None or dict{rows, size_mb, table_name}
    if workflow_detail.status == "workflow_review_pass" and not has_ghost_task:
        try:
            sql_text = _workflow_sql_text(workflow_detail)
            parsed = _parse_first_alter(sql_text)
            if parsed and parsed.get("table"):
                size_info = _get_table_size_info(
                    instance=workflow_detail.instance,
                    db_name=parsed.get("db") or workflow_detail.db_name,
                    table_name=parsed["table"],
                )
                if size_info:
                    row_threshold = int(getattr(settings, "CUSTOM_BIG_TABLE_ROW_THRESHOLD", 100000))
                    size_threshold_mb = int(getattr(settings, "CUSTOM_BIG_TABLE_SIZE_THRESHOLD_MB", 100))
                    if (size_info["rows"] >= row_threshold
                            or size_info["size_mb"] >= size_threshold_mb):
                        big_table_alert = {
                            "table_name": parsed["table"],
                            "rows": size_info["rows"],
                            "size_mb": size_info["size_mb"],
                            "row_threshold": row_threshold,
                            "size_threshold_mb": size_threshold_mb,
                        }
        except Exception:  # noqa: BLE001
            logger.exception("big_table_alter detect crashed: wf=%s", workflow_detail.id)

    if getattr(settings, "CUSTOM_GH_OST_ENABLED", False):
        from sql.extensions.ddl_gh_ost.models import DdlGhostTask

        # ===== lazy auto-enable: 审批通过 + 提交人勾了 gh-ost → 自动启用 =====
        if (
            getattr(workflow_detail, "enable_gh_ost", False)
            and workflow_detail.status == "workflow_review_pass"
        ):
            try:
                existing = DdlGhostTask.objects.filter(workflow=workflow_detail).first()
                if existing is None:
                    # 审批通过且没 task → 自动启用
                    from sql.extensions.ddl_gh_ost.views import _enable_ghost_for_workflow
                    auto_result = _enable_ghost_for_workflow(
                        workflow_detail, created_by=f"lazy-auto(提交人={workflow_detail.engineer})"
                    )
                    if not auto_result.get("ok"):
                        # 不阻塞详情页渲染, 记录 warning
                        logger.warning(
                            "lazy auto-enable failed: wf=%s result=%s",
                            workflow_detail.id, auto_result,
                        )
            except Exception:  # noqa: BLE001
                logger.exception("lazy auto-enable crashed: wf=%s", workflow_detail.id)

        try:
            ghost_task = DdlGhostTask.objects.get(workflow=workflow_detail)
            has_ghost_task = True
            ghost_task_is_terminal = ghost_task.is_terminal
            # 关键修复: 修复 #1 - 避免 gh-ost 与原路径"立即执行"冲突
            # active 状态 (queued/running/cut_over/precheck_failed) 都视为在跑
            has_active_ghost_task = ghost_task.status in (
                "queued", "running", "cut_over", "precheck_failed"
            )
        except DdlGhostTask.DoesNotExist:
            ghost_task = None
        # 启用条件: superuser / DBA 组 / 工单 submitter
        from django.contrib.auth.models import Group
        user = request.user
        is_submitter = (user.username == workflow_detail.engineer)
        is_dba_group = user.groups.filter(name__in=["DBA", "DBA组长"]).exists()
        # 已存在 task (不论 active/terminal) → 不再显示"启用"按钮
        # 终态 task 想要重启用走 /gh_ost/retry/ 端点 (仅 failed/cancelled 可用)
        # CUSTOM-MODIFIED: 审批守卫 —— 去掉 manreviewing, 仅 review_pass + timingtask
        # CUSTOM-MODIFIED: v0.3.0-beta DBA 兜底 —— 任何有 sql.sql_review 权限的 DBA 都能启用
        ## 业务背景: DBA 是兜底角色, RD 漏勾 gh-ost 时 DBA 必须能启用, 不能让流程卡住
        ## 134 dev 上 DBA user 没绑 "DBA"/"DBA组长" auth_group, 改用 has_perm 更准
        ## @ 2026-08-11 @ mavis
        can_enable_ghost = (
            (user.is_superuser
             or user.has_perm("sql.sql_review")  # DBA 兜底: 有审阅 perm 就能启用
             or is_dba_group                      # 兼容老路径: auth_group 是 DBA/DBA组长
             or is_submitter)
            and workflow_detail.status in ("workflow_review_pass", "workflow_timingtask")
            and not has_ghost_task
        )

    # 自动审批不通过的不需要获取下列信息
    if workflow_detail.status != "workflow_autoreviewwrong":
        # 是否可审核
        is_can_review = Audit.can_review(request.user, workflow_id, 2)
        # 是否可执行 TODO 这几个判断方法入参都修改为workflow对象，可减少多次数据库交互
        ## CUSTOM-MODIFIED: v0.3.0-beta 修复 gh-ost 与原路径"立即执行"冲突
        ## 关键修复: has_active_ghost_task=True 时禁用立即执行按钮，避免双 ALTER
        ## task 终态 (cancelled/failed/rolled_back) 后 has_active_ghost_task=False
        ## 立即执行按钮重新可见，DBA 可点"取消迁移"否决后走原路径
        ## @ 2026-08-10 @ mavis
        is_can_execute = can_execute(request.user, workflow_id) and not has_active_ghost_task
        # 是否可定时执行
        is_can_timingtask = can_timingtask(request.user, workflow_id)
        # 是否可取消
        is_can_cancel = can_cancel(request.user, workflow_id)
        # 是否可查看回滚信息
        is_can_rollback = can_rollback(request.user, workflow_id)

        # 获取审核日志
        try:
            audit_detail = Audit.detail_by_workflow_id(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.SQL_REVIEW,
            )
            audit_id = audit_detail.audit_id
            last_operation_info = (
                Audit.logs(audit_id=audit_id).latest("id").operation_info
            )
        except Exception as e:
            logger.debug(f"无审核日志记录，错误信息{e}")
            last_operation_info = ""
    else:
        is_can_review = False
        is_can_execute = False
        is_can_timingtask = False
        is_can_cancel = False
        is_can_rollback = False
        last_operation_info = None

    # 获取定时执行任务信息
    if workflow_detail.status == "workflow_timingtask":
        job_id = Const.workflowJobprefix["sqlreview"] + "-" + str(workflow_id)
        job = task_info(job_id)
        if job:
            run_date = job.next_run
        else:
            run_date = ""
    else:
        run_date = ""

    # 添加当前审核人信息
    current_reviewers = []
    for node in review_info.nodes:
        if node.is_current_node == False:
            continue
        for user in node.group.user_set.filter(is_active=1):
            # 确保 group_name 和 group.name 类型一致
            group_names = [group.group_name for group in user_groups(user)]
            if workflow_detail.group_name in group_names:
                current_reviewers.append(user)

    # 获取是否开启手工执行确认
    manual = SysConfig().get("manual")

    context = {
        "workflow_detail": workflow_detail,
        "current_reviewers": current_reviewers,
        "last_operation_info": last_operation_info,
        "is_can_review": is_can_review,
        "is_can_execute": is_can_execute,
        "is_can_timingtask": is_can_timingtask,
        "is_can_cancel": is_can_cancel,
        "is_can_rollback": is_can_rollback,
        "review_info": review_info,
        "manual": manual,
        "run_date": run_date,
        "has_ghost_task": has_ghost_task,
        "can_enable_ghost": can_enable_ghost,
        "ghost_task": ghost_task,
        "ghost_task_is_terminal": ghost_task_is_terminal,
        # CUSTOM: 提交人申请 gh-ost 标记 (审批前显示"等审批", 审批后自动启用)
        "enable_gh_ost_marked": bool(getattr(workflow_detail, "enable_gh_ost", False)),
        # CUSTOM: 大表 DDL 防呆 (None = 不触发, dict = 触发红色 alert)
        "big_table_alert": big_table_alert,
    }
    return render(request, "detail.html", context)


def rollback(request):
    """展示回滚的SQL页面"""
    workflow_id = request.GET.get("workflow_id")
    if not can_rollback(request.user, workflow_id):
        raise PermissionDenied
    download = request.GET.get("download")
    if workflow_id == "" or workflow_id is None:
        context = {"errMsg": "workflow_id参数为空."}
        return render(request, "error.html", context)
    workflow = SqlWorkflow.objects.get(id=int(workflow_id))

    # 直接下载回滚语句
    if download:
        try:
            query_engine = get_engine(instance=workflow.instance)
            list_backup_sql = query_engine.get_rollback(workflow=workflow)
        except Exception as msg:
            logger.error(traceback.format_exc())
            context = {"errMsg": msg}
            return render(request, "error.html", context)

        # 获取数据，存入目录
        path = os.path.join(settings.BASE_DIR, "downloads/rollback")
        os.makedirs(path, exist_ok=True)
        file_name = f"{path}/rollback_{workflow_id}.sql"
        with open(file_name, "w") as f:
            for sql in list_backup_sql:
                f.write(f"/*{sql[0]}*/\n{sql[1]}\n")
        # 返回
        response = FileResponse(open(file_name, "rb"))
        response["Content-Type"] = "application/octet-stream"
        response["Content-Disposition"] = (
            f'attachment;filename="rollback_{workflow_id}.sql"'
        )
        return response
    # 异步获取，并在页面展示，如果数据量大加载会缓慢
    else:
        rollback_workflow_name = (
            f"【回滚工单】原工单Id:{workflow_id} ,{workflow.workflow_name}"
        )
        context = {
            "workflow_detail": workflow,
            "rollback_workflow_name": rollback_workflow_name,
        }
        return render(request, "rollback.html", context)


@permission_required("sql.menu_sqlanalyze", raise_exception=True)
def sqlanalyze(request):
    """SQL分析页面"""
    return render(request, "sqlanalyze.html")


@permission_required("sql.menu_query", raise_exception=True)
def sqlquery(request):
    """SQL在线查询页面"""
    # 主动创建标签
    InstanceTag.objects.get_or_create(
        tag_code="can_read", defaults={"tag_name": "支持查询", "active": True}
    )
    # 收藏语句
    user = request.user
    group_list = user_groups(user)
    storage_type = SysConfig().get("storage_type")

    favorites = QueryLog.objects.filter(username=user.username, favorite=True).values(
        "id", "alias"
    )
    can_download = 1 if user.has_perm("sql.query_download") or user.is_superuser else 0
    can_offline_download = user.has_perm("sql.offline_download") or user.is_superuser
    context = {
        "favorites": favorites,
        "can_download": can_download,
        "engines": engine_map,
        "group_list": group_list,
        "storage_type": storage_type,
        "can_offline_download": can_offline_download,
    }
    return render(request, "sqlquery.html", context)


@permission_required("sql.menu_queryapplylist", raise_exception=True)
def queryapplylist(request):
    """查询权限申请列表页面"""
    user = request.user
    # 获取资源组
    group_list = user_groups(user)

    context = {"group_list": group_list, "engines": engine_map}
    return render(request, "queryapplylist.html", context)


def queryapplydetail(request, apply_id):
    """查询权限申请详情页面"""
    workflow_detail = QueryPrivilegesApply.objects.get(apply_id=apply_id)
    # 获取当前审批和审批流程
    audit_handler = AuditV2(workflow=workflow_detail)
    review_info = audit_handler.get_review_info()

    # 是否可审核
    is_can_review = Audit.can_review(request.user, apply_id, 1)
    # 获取审核日志
    if workflow_detail.status == 2:
        try:
            audit_id = Audit.detail_by_workflow_id(
                workflow_id=apply_id, workflow_type=1
            ).audit_id
            last_operation_info = (
                Audit.logs(audit_id=audit_id).latest("id").operation_info
            )
        except Exception as e:
            logger.debug(f"无审核日志记录，错误信息{e}")
            last_operation_info = ""
    else:
        last_operation_info = ""

    # 添加当前审核人信息
    current_reviewers = []
    for node in review_info.nodes:
        if node.is_current_node == False:
            continue
        for user in node.group.user_set.filter(is_active=1):
            # 确保 group_name 和 group.name 类型一致
            group_names = [group.group_name for group in user_groups(user)]
            if workflow_detail.group_name in group_names:
                current_reviewers.append(user)

    context = {
        "workflow_detail": workflow_detail,
        "current_reviewers": current_reviewers,
        "review_info": review_info,
        "last_operation_info": last_operation_info,
        "is_can_review": is_can_review,
    }
    return render(request, "queryapplydetail.html", context)


def queryuserprivileges(request):
    """查询权限管理页面"""
    # 获取所有用户
    user_list = (
        QueryPrivileges.objects.filter(is_deleted=0).values("user_display").distinct()
    )
    context = {"user_list": user_list}
    return render(request, "queryuserprivileges.html", context)


@permission_required("sql.menu_sqladvisor", raise_exception=True)
def sqladvisor(request):
    """SQL优化工具页面"""
    return render(request, "sqladvisor.html")


@permission_required("sql.menu_slowquery", raise_exception=True)
def slowquery(request):
    """SQL慢日志页面"""
    return render(request, "slowquery.html")


@permission_required("sql.menu_instance", raise_exception=True)
def instance(request):
    """实例管理页面"""
    # 获取实例标签
    tags = InstanceTag.objects.filter(active=True)
    return render(request, "instance.html", {"tags": tags, "engines": engine_map})


@permission_required("sql.menu_instance_account", raise_exception=True)
def instanceaccount(request):
    """实例账号管理页面"""
    return render(request, "instanceaccount.html")


@permission_required("sql.menu_database", raise_exception=True)
def database(request):
    """实例数据库管理页面"""
    # 获取所有有效用户，通知对象
    active_user = Users.objects.filter(is_active=1)

    return render(request, "database.html", {"active_user": active_user})


@permission_required("sql.menu_dbdiagnostic", raise_exception=True)
def dbdiagnostic(request):
    """会话管理页面"""
    return render(request, "dbdiagnostic.html")


@permission_required("sql.menu_data_dictionary", raise_exception=True)
def data_dictionary(request):
    """数据字典页面"""
    return render(request, "data_dictionary.html", locals())


@permission_required("sql.menu_param", raise_exception=True)
def instance_param(request):
    """实例参数管理页面"""
    return render(request, "param.html")


@permission_required("sql.menu_param_compare", raise_exception=True)
def param_compare(request):
    """参数对比页面"""
    return render(request, "param_compare.html")


@permission_required("sql.menu_my2sql", raise_exception=True)
def my2sql(request):
    """my2sql页面"""
    return render(request, "my2sql.html")


@permission_required("sql.menu_schemasync", raise_exception=True)
def schemasync(request):
    """数据库差异对比页面"""
    return render(request, "schemasync.html")


@permission_required("sql.menu_archive", raise_exception=True)
def archive(request):
    """归档列表页面"""
    # 获取资源组
    group_list = user_groups(request.user)
    ins_list = user_instances(request.user, db_type=["mysql"]).order_by(
        Convert("instance_name", "gbk").asc()
    )
    return render(
        request, "archive.html", {"group_list": group_list, "ins_list": ins_list}
    )


def archive_detail(request, id):
    """归档详情页面"""
    archive_config = ArchiveConfig.objects.get(pk=id)
    # 获取当前审批和审批流程、是否可审核
    audit_handler = AuditV2(
        workflow=archive_config, resource_group=archive_config.resource_group
    )
    review_info = audit_handler.get_review_info()
    try:
        audit_handler.can_operate(WorkflowAction.PASS, request.user)
        can_review = True
    except AuditException:
        can_review = False
    # 获取审核日志
    if archive_config.status == 2:
        try:
            audit_id = Audit.detail_by_workflow_id(
                workflow_id=id, workflow_type=3
            ).audit_id
            last_operation_info = (
                Audit.logs(audit_id=audit_id).latest("id").operation_info
            )
        except Exception as e:
            logger.debug(f"归档配置{id}无审核日志记录，错误信息{e}")
            last_operation_info = ""
    else:
        last_operation_info = ""

    # 添加当前审核人信息
    current_reviewers = []
    for node in review_info.nodes:
        if node.is_current_node == False:
            continue
        for user in node.group.user_set.filter(is_active=1):
            # 确保 group_name 和 group.name 类型一致
            group_names = [group.group_name for group in user_groups(user)]
            if archive_config.resource_group.group_name in group_names:
                current_reviewers.append(user)

    context = {
        "archive_config": archive_config,
        "current_reviewers": current_reviewers,
        "review_info": review_info,
        "last_operation_info": last_operation_info,
        "can_review": can_review,
    }
    return render(request, "archivedetail.html", context)


@superuser_required
def config(request):
    """配置管理页面"""
    # 获取所有资源组名称
    group_list = ResourceGroup.objects.all()
    # 获取所有权限组
    auth_group_list = Group.objects.all()
    # 获取所有实例标签
    instance_tags = InstanceTag.objects.all()
    # 支持自动审核的数据库类型
    db_type = ["mysql", "oracle", "mongo", "clickhouse", "redis", "doris", "tdengine"]
    # 获取所有配置项
    all_config = Config.objects.all().values("item", "value")
    sys_config = {}
    for items in all_config:
        sys_config[items["item"]] = items["value"]

    # 设置OPENAI部分配置不存在时的默认值
    if not sys_config.get("default_chat_model", ""):
        sys_config["default_chat_model"] = "gpt-3.5-turbo"
    if not sys_config.get("default_query_template", ""):
        sys_config["default_query_template"] = (
            "你是一个熟悉 {{db_type}} 的工程师, 我会给你一些基本信息和要求, 你会生成一个查询语句给我使用, 不要返回任何注释和序号, 仅返回查询语句：{{table_schema}} \n {{user_input}}"
        )

    context = {
        "group_list": group_list,
        "auth_group_list": auth_group_list,
        "instance_tags": instance_tags,
        "db_type": db_type,
        "config": sys_config,
        "workflow_choices": WorkflowType,
    }
    return render(request, "config.html", context)


@superuser_required
def group(request):
    """资源组管理页面"""
    return render(request, "group.html")


@superuser_required
def groupmgmt(request, group_id):
    """资源组组关系管理页面"""
    group = ResourceGroup.objects.get(group_id=group_id)
    return render(request, "groupmgmt.html", {"group": group})


def workflows(request):
    """待办列表页面"""
    return render(request, "workflow.html")


def workflowsdetail(request, audit_id):
    """待办详情"""
    # 按照不同的workflow_type返回不同的详情
    audit_detail = Audit.detail(audit_id)
    if not audit_detail:
        raise Http404("不存在对应的工单记录")
    if audit_detail.workflow_type == WorkflowType.QUERY:
        return HttpResponseRedirect(
            reverse("sql:queryapplydetail", args=(audit_detail.workflow_id,))
        )
    elif audit_detail.workflow_type == WorkflowType.SQL_REVIEW:
        return HttpResponseRedirect(
            reverse("sql:detail", args=(audit_detail.workflow_id,))
        )
    elif audit_detail.workflow_type == WorkflowType.ARCHIVE:
        return HttpResponseRedirect(
            reverse("sql:archive_detail", args=(audit_detail.workflow_id,))
        )


@permission_required("sql.menu_document", raise_exception=True)
def dbaprinciples(request):
    """SQL文档页面 - 显示 MySQL 数据库设计规范。

    ## CUSTOM-MODIFIED: 8/24 修 FileNotFoundError @ 2026-08-24 @ mavis
    ## 关联: docs/changelogs/2026-08-24_dbaprinciples-file-not-found.md
    ## 根因 (8/24): Archery 上游 views.py:870 读 docs/docs.md, 但仓库里没这个文件
    ##       134 dev 实际有 docs/upstream/docs.md (项目自己维护的 MySQL 设计规范)
    ## 修法: 优先读 docs/upstream/docs.md, 兜底读 docs/architecture.md, 都没有显示友好提示
    """
    candidates = [
        os.path.join(settings.BASE_DIR, "docs/upstream/docs.md"),
        os.path.join(settings.BASE_DIR, "docs/architecture.md"),
    ]
    md = None
    for file in candidates:
        if os.path.exists(file):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    md = f.read().replace("\n", "\\n")
                logger.info("dbaprinciples 读 %s (%d chars)", file, len(md))
                break
            except OSError as exc:
                logger.warning("dbaprinciples 读 %s 失败: %s", file, exc)
                continue
    if md is None:
        md = (
            "# 文档暂未提供\n\n"
            "请运维管理员将 MySQL 数据库设计规范放到以下任一位置:\n\n"
            "- `docs/upstream/docs.md`\n"
            "- `docs/architecture.md`\n\n"
            "推荐放 `docs/upstream/docs.md` (跟 134 dev 一致)。\n"
        )
    return render(request, "dbaprinciples.html", {"md": md})


@permission_required("sql.audit_user", raise_exception=True)
def audit(request):
    """通用审计日志页面"""
    _action_types = AuditEntry.objects.values_list("action").distinct()
    action_types = [i[0] for i in _action_types]
    return render(request, "audit.html", {"action_types": action_types})


@permission_required("sql.audit_user", raise_exception=True)
def audit_sqlquery(request):
    """SQL在线查询页面审计"""
    user = request.user
    favorites = QueryLog.objects.filter(username=user.username, favorite=True).values(
        "id", "alias"
    )
    return render(request, "audit_sqlquery.html", {"favorites": favorites})


def audit_sqlworkflow(request):
    """SQL上线工单列表页面"""
    user = request.user
    # 过滤筛选项的数据
    filter_dict = dict()
    # 管理员，可查看所有工单
    if user.is_superuser or user.has_perm("sql.audit_user"):
        pass
    # 非管理员，拥有审核权限、资源组粒度执行权限的，可以查看组内所有工单
    elif user.has_perm("sql.sql_review") or user.has_perm(
        "sql.sql_execute_for_resource_group"
    ):
        # 先获取用户所在资源组列表
        group_list = user_groups(user)
        group_ids = [group.group_id for group in group_list]
        filter_dict["group_id__in"] = group_ids
    # 其他人只能查看自己提交的工单
    else:
        filter_dict["engineer"] = user.username
    instance_id = (
        SqlWorkflow.objects.filter(**filter_dict).values("instance_id").distinct()
    )
    instance = Instance.objects.filter(pk__in=instance_id)
    resource_group_id = (
        SqlWorkflow.objects.filter(**filter_dict).values("group_id").distinct()
    )
    resource_group = ResourceGroup.objects.filter(group_id__in=resource_group_id)

    return render(
        request,
        "audit_sqlworkflow.html",
        {
            "status_list": SQL_WORKFLOW_CHOICES,
            "instance": instance,
            "resource_group": resource_group,
        },
    )


@permission_required("sql.sqlexport_submit", raise_exception=True)
def sqlexportsubmit(request):
    """SQL导出工单页面"""
    # 主动创建标签
    InstanceTag.objects.get_or_create(
        tag_code="can_read", defaults={"tag_name": "支持查询", "active": True}
    )
    # 收藏语句
    user = request.user
    group_list = user_groups(user)
    # 获取所有配置项
    max_export_rows = SysConfig().get("max_export_rows")
    max_export_rows = int(max_export_rows) if max_export_rows else 10000

    favorites = QueryLog.objects.filter(username=user.username, favorite=True).values(
        "id", "alias"
    )
    can_download = user.has_perm("sql.query_download") or user.is_superuser
    can_offline_download = user.has_perm("sql.offline_download") or user.is_superuser
    context = {
        "favorites": favorites,
        "can_download": can_download,
        "engines": engine_map,
        "group_list": group_list,
        "max_export_rows": max_export_rows,
        "can_offline_download": can_offline_download,
    }
    return render(request, "sqlexportsubmit.html", context)


@permission_required("sql.sqlexport_submit", raise_exception=True)
def sqlexport_pre_check(request):
    """数据导出提交前预检，按各引擎查询规则校验并统计导出行数。"""
    result = {"status": 0, "msg": "ok", "data": {}}
    instance_name = request.POST.get("instance_name")
    db_name = request.POST.get("db_name")
    sql_content = request.POST.get("sql_content")

    if not instance_name or not db_name or not sql_content:
        result["status"] = 1
        result["msg"] = "页面提交参数可能为空"
        return JsonResponse(result)

    try:
        instance = user_instances(request.user, tag_codes=["can_read"]).get(
            instance_name=instance_name
        )
    except Instance.DoesNotExist:
        result["status"] = 1
        result["msg"] = "你所在组未关联该实例"
        return JsonResponse(result)

    instance.sql_content = sql_content
    instance.selected_db_name = db_name
    check_result = OffLineDownLoad().pre_count_check(workflow=instance)
    result["data"] = {
        "error_count": check_result.error_count,
        "warning_count": check_result.warning_count,
        "rows": check_result.to_dict(),
    }
    if check_result.error_count:
        result["status"] = 1
        result["msg"] = check_result.rows[0].errormessage if check_result.rows else ""
    return JsonResponse(result)
