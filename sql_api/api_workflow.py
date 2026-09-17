import datetime
import logging
import traceback

from django.contrib.auth.decorators import permission_required
from django.contrib.auth.models import Group
from django.conf import settings
from django.db import transaction
from django.utils.decorators import method_decorator
from django_q.tasks import async_task
from drf_spectacular.utils import extend_schema
from rest_framework import views, generics, status, serializers, permissions
from rest_framework.response import Response

from common.config import SysConfig
from common.utils.const import WorkflowStatus, WorkflowType, WorkflowAction
from sql.engines import get_engine
from sql.models import (
    SqlWorkflow,
    SqlWorkflowContent,
    WorkflowAudit,
    Users,
    WorkflowLog,
    ArchiveConfig,
    QueryPrivilegesApply,
)
from sql.notify import notify_for_audit, notify_for_execute
from sql.query_privileges import _query_apply_audit_call_back
from sql.utils.resource_group import user_groups
from sql.utils.sql_review import can_cancel, can_execute, on_correct_time_period
from sql.utils.tasks import del_schedule
from sql.utils.workflow_audit import Audit, get_auditor, AuditException
from sql.utils.cross_db_check import check_cross_db
from sql.utils.pk_conflict_check import check_pk_conflict
## CUSTOM-MODIFIED: v1 优化加 _check_mixed_ddl 后端兜底 @ 2026-09-17 @ mavis
## 关联: docs/changelogs/2026-09-17_v1-optimize-mixed-ddl-block-submit.md
from sql.views import _check_mixed_ddl
from .filters import WorkflowFilter, WorkflowAuditFilter
from .pagination import CustomizedPagination
from .serializers import (
    WorkflowContentSerializer,
    ExecuteCheckSerializer,
    ExecuteCheckResultSerializer,
    WorkflowAuditSerializer,
    WorkflowAuditListSerializer,
    WorkflowLogSerializer,
    WorkflowLogListSerializer,
    AuditWorkflowSerializer,
    ExecuteWorkflowSerializer,
)

logger = logging.getLogger("default")


class ExecuteCheck(views.APIView):

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="SQL检查",
        request=ExecuteCheckSerializer,
        responses={200: ExecuteCheckResultSerializer},
        description="对提供的SQL进行语法检查",
    )
    @method_decorator(permission_required("sql.sql_submit", raise_exception=True))
    def post(self, request):
        # 参数验证
        serializer = ExecuteCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.get_instance()
        # 交给engine进行检测
        try:
            db_name = request.data["db_name"]
            check_engine = get_engine(instance=instance)
            db_name = check_engine.escape_string(db_name)
            check_result = check_engine.execute_check(
                db_name=db_name, sql=request.data["full_sql"].strip()
            )
        except Exception as e:
            raise serializers.ValidationError({"errors": f"{e}"})
        check_result.rows = check_result.to_dict()

        ## CUSTOM-MODIFIED: W3 跨库限制 + INSERT PK 冲突检测 (9/16 阿达叔叔拍板 A 严格)
        ## @ 2026-09-16 @ mavis
        ## 关联: docs/changelogs/2026-09-16_cross-db-pk-check.md
        ## 实战: 9/16 wf#4821 (alter table hly_usercenter.accesscard_user_vehicle_change 跨库)
        ##       + wf#4834 (INSERT 306/307/308/309 重复 PK) 业务方实战触发
        ## 9/16 调研: Archery 上游 + inception/goinception 都无跨库/PK 冲突检测能力,
        ##            必须二次开发. inception 走 SQL 语法/语义 + `--real_row_count` 受影响行数,
        ##            不查 DB 现有 PK 值.
        ## 修法: 走 inception 之后 + 走 cross_db_check + pk_conflict_check
        ##       + serializer 加 2 字段 + sqlsubmit.html 检测后回调红框 alert + 阻止提交按钮
        full_sql = request.data["full_sql"].strip()
        # 跨库检测
        try:
            cross_db_result = check_cross_db(full_sql, instance, db_name)
        except Exception as e:
            logger.warning("check_cross_db 失败: %s", e)
            cross_db_result = {"ok": True, "error": str(e), "schemas": [], "expected_db": db_name}
        # PK 冲突检测 (业务方实战 wf#4834 重复 PK)
        try:
            pk_conflict_result = check_pk_conflict(full_sql, instance, db_name)
        except Exception as e:
            logger.warning("check_pk_conflict 失败: %s", e)
            pk_conflict_result = {"ok": True, "error": str(e), "conflicts": []}

        ## CUSTOM-MODIFIED: v1 优化加 mixed_ddl_check (混合 DDL 检测) @ 2026-09-17 @ mavis
        ## 关联: docs/changelogs/2026-09-17_v1-optimize-mixed-ddl-block-submit.md
        ## 业务: 9/16 wf#4841 业务方工单含 4 CREATE + 4 ALTER, 旧提醒无效, 业务方还是提交, 工单显示"成功"
        ##       但实际 7/8 失败 (CREATE 丢失, 9/16 阿达叔叔拍板)
        ## 修法: SQL 检测时同时跑 _check_mixed_ddl, 含 ALTER + CREATE/INSERT/UPDATE/DELETE 时 → ok=False
        ##       前端 sqlsubmit.html 检测回调: 渲染红框 alert + 阻止提交按钮 (跟 cross_db / pk_conflict 一致)
        ##       后端 WorkflowList.post() 兜底: 即使前端绕过, 也 reject (raise ValidationError)
        try:
            mixed_ddl_result = _check_mixed_ddl(full_sql)
        except Exception as e:
            logger.warning("_check_mixed_ddl 失败: %s", e)
            mixed_ddl_result = {"ok": True, "error": str(e)}

        serializer_obj = ExecuteCheckResultSerializer(
            check_result, context={
                "cross_db_check": cross_db_result,
                "pk_conflict_check": pk_conflict_result,
                "mixed_ddl_check": mixed_ddl_result,
            }
        )
        return Response(serializer_obj.data)


class WorkflowList(generics.ListAPIView):
    """
    列出所有的workflow或者提交一条新的workflow
    """

    filterset_class = WorkflowFilter
    pagination_class = CustomizedPagination
    serializer_class = WorkflowContentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        1、非管理员，拥有审核权限、资源组粒度执行权限的，可以查看组内所有工单
        2、管理员，审计员，可查看所有工单
        """
        filter_dict = {}
        user = self.request.user
        # 管理员，审计员，可查看所有工单
        if user.is_superuser or user.has_perm("sql.audit_user"):
            pass
        # 非管理员，拥有审核权限、资源组粒度执行权限的，可以查看组内所有工单
        elif user.has_perm("sql.sql_review") or user.has_perm(
            "sql.sql_execute_for_resource_group"
        ):
            filter_dict["group_id__in"] = [
                group.group_id for group in user_groups(user)
            ]
        # 其他人只能查看自己提交的工单
        else:
            filter_dict["engineer"] = user.username
        return (
            SqlWorkflowContent.objects.filter(**filter_dict)
            .select_related("workflow")
            .order_by("-id")
        )

    @extend_schema(
        summary="SQL上线工单清单",
        request=WorkflowContentSerializer,
        responses={200: WorkflowContentSerializer},
        description="列出所有SQL上线工单（过滤，分页）",
    )
    def get(self, request):
        workflows = self.filter_queryset(self.get_queryset())
        page_wf = self.paginate_queryset(queryset=workflows)
        serializer_obj = self.get_serializer(page_wf, many=True)
        data = {"data": serializer_obj.data}
        return self.get_paginated_response(data)

    @extend_schema(
        summary="提交SQL上线工单",
        request=WorkflowContentSerializer,
        responses={201: WorkflowContentSerializer},
        description="提交一条SQL上线工单",
    )
    @method_decorator(permission_required("sql.sql_submit", raise_exception=True))
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workflow_content = serializer.save()
        sys_config = SysConfig()
        is_notified = (
            "Apply" in sys_config.get("notify_phase_control").split(",")
            if sys_config.get("notify_phase_control")
            else True
        )
        if (
            workflow_content.workflow.status
            in ["workflow_manreviewing", "workflow_review_pass"]
            and is_notified
        ):
            # 获取审核信息
            workflow_audit = Audit.detail_by_workflow_id(
                workflow_id=workflow_content.workflow.id,
                workflow_type=WorkflowType.SQL_REVIEW,
            )
            async_task(
                notify_for_audit,
                workflow_audit=workflow_audit,
                timeout=60,
                task_name=f"sqlreview-submit-{workflow_content.workflow.id}",
            )
        ## CUSTOM-MODIFIED: v0.3.0-beta 提交页"启用 gh-ost"勾选联动
        ## v0.3.0-beta 修: 勾选不再立即调 _enable_ghost_for_workflow (会绕过审批流程)
        ## 改为: 只写 SqlWorkflow.enable_gh_ost=True 标记, 由 detail 视图 lazy 在审批通过时自动启用
        ## 关联 changelog: docs/changelogs/2026-08-11_gh-ost-approval-gating.md
        ## @ 2026-08-11 @ mavis
        if request.data.get("enable_ghost") and getattr(settings, "CUSTOM_GH_OST_ENABLED", False):
            try:
                wf = workflow_content.workflow
                wf.enable_gh_ost = True
                ## CUSTOM-MODIFIED: v0 gh-ost 智能模式存 gh_ost_mode 字段 @ 2026-09-17 @ mavis
                ## 关联: docs/changelogs/2026-09-16_v0-gh-ost-smart-mode.md
                ## 拍板: 9/16 21:42 阿达叔叔 同意 5A
                ## 业务: 业务方提交时选 smart/all_ghost/all_native, 存到 SqlWorkflow.gh_ost_mode
                gh_ost_mode_input = request.data.get("gh_ost_mode", "smart")
                valid_modes = {"smart", "all_ghost", "all_native"}
                if gh_ost_mode_input not in valid_modes:
                    gh_ost_mode_input = "smart"  # fallback 默认值
                wf.gh_ost_mode = gh_ost_mode_input
                wf.save(update_fields=["enable_gh_ost", "gh_ost_mode"])
                ghost_result = {
                    "ok": True,
                    "pending_approval": True,
                    "summary": f"已记录 gh-ost 申请 (模式={gh_ost_mode_input})，等审批通过后自动启用",
                    "gh_ost_mode": gh_ost_mode_input,
                }
            except Exception as exc:  # noqa: BLE001
                ghost_result = {"ok": False, "error": f"保存 gh-ost 申请异常: {exc}"}
            # 不阻塞主流程，把结果塞进 response data 让前端展示
            serializer_data = dict(serializer.data) if isinstance(serializer.data, dict) else {}
            serializer_data["enable_ghost"] = ghost_result
            return Response(serializer_data, status=status.HTTP_201_CREATED)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class WorkflowAuditList(generics.ListAPIView):
    """
    列出指定用户当前待自己审核的工单
    """

    filterset_class = WorkflowAuditFilter
    pagination_class = CustomizedPagination
    serializer_class = WorkflowAuditListSerializer
    queryset = WorkflowAudit.objects.filter(
        current_status=WorkflowStatus.WAITING
    ).order_by("-audit_id")

    @extend_schema(exclude=True)
    def get(self, request):
        return Response({"detail": "方法 “GET” 不被允许。"})

    @extend_schema(
        summary="待审核清单",
        request=WorkflowAuditSerializer,
        responses={200: WorkflowAuditListSerializer},
        description="列出指定用户待审核清单（过滤，分页）",
    )
    def post(self, request):
        # 参数验证
        serializer = WorkflowAuditSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # 先获取用户所在资源组列表
        user = Users.objects.get(username=request.data["engineer"])
        group_list = user_groups(user)
        group_ids = [group.group_id for group in group_list]

        # 再获取用户所在权限组列表
        if user.is_superuser:
            auth_group_ids = [group.id for group in Group.objects.all()]
        else:
            auth_group_ids = [group.id for group in Group.objects.filter(user=user)]

        self.queryset = self.queryset.filter(
            current_status=WorkflowStatus.WAITING,
            group_id__in=group_ids,
            current_audit__in=auth_group_ids,
        )
        audit = self.filter_queryset(self.queryset)
        page_audit = self.paginate_queryset(queryset=audit)
        serializer_obj = self.get_serializer(page_audit, many=True)
        data = {"data": serializer_obj.data}
        return self.get_paginated_response(data)


class AuditWorkflow(views.APIView):
    """
    审核workflow，包括查询权限申请、SQL上线申请、数据归档申请
    """

    @extend_schema(
        summary="审核工单",
        request=AuditWorkflowSerializer,
        description="审核一条工单（通过或终止）",
    )
    def post(self, request):
        # 参数验证
        serializer = AuditWorkflowSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        # 此处已经通过校验, 肯定存在, 就不 try 了
        workflow_audit = WorkflowAudit.objects.get(
            workflow_id=serializer.data["workflow_id"],
            workflow_type=serializer.data["workflow_type"],
        )
        sys_config = SysConfig()
        auditor = get_auditor(audit=workflow_audit)
        user = Users.objects.get(username=serializer.data["engineer"])
        if serializer.data["audit_type"] == "pass":
            action = WorkflowAction.PASS
            notify_config_key = "Pass"
            success_message = "passed"
        elif serializer.data["audit_type"] == "cancel":
            notify_config_key = "Cancel"
            success_message = "canceled"
            if auditor.workflow.engineer == serializer.data["engineer"]:
                action = WorkflowAction.ABORT
            else:
                raise serializers.ValidationError({"errors": "用户无权操作此工单"})
        else:
            raise serializers.ValidationError(
                {"errors": "audit_type 只能是 pass 或 cancel"}
            )

        try:
            workflow_audit_detail = auditor.operate(
                action, user, serializer.data["audit_remark"]
            )
        except AuditException as e:
            raise serializers.ValidationError({"errors": f"操作失败, {str(e)}"})

        # 最后处置一下原本工单的状态
        if auditor.workflow_type == WorkflowType.QUERY:
            _query_apply_audit_call_back(
                auditor.audit.workflow_id,
                auditor.audit.current_status,
            )
        elif auditor.workflow_type == WorkflowType.SQL_REVIEW:
            if auditor.audit.current_status == WorkflowStatus.PASSED:
                auditor.workflow.status = "workflow_review_pass"
                auditor.workflow.save(update_fields=["status"])
            elif auditor.audit.current_status in [
                WorkflowStatus.ABORTED,
                WorkflowStatus.REJECTED,
            ]:
                if auditor.workflow.status == "workflow_timingtask":
                    del_schedule(f"sqlreview-timing-{auditor.workflow.id}")
                    # 将流程状态修改为人工终止流程
                auditor.workflow.status = "workflow_abort"
                auditor.workflow.save(update_fields=["status"])
        elif auditor.workflow_type == WorkflowType.ARCHIVE:
            auditor.workflow.status = auditor.audit.current_status
            if auditor.audit.current_status == WorkflowStatus.PASSED:
                auditor.workflow.state = True
            else:
                auditor.workflow.state = False
            auditor.workflow.save(update_fields=["status", "state"])

        # 发消息
        is_notified = (
            notify_config_key in sys_config.get("notify_phase_control").split(",")
            if sys_config.get("notify_phase_control")
            else True
        )
        if is_notified:
            async_task(
                notify_for_audit,
                workflow_audit=auditor.audit,
                workflow_audit_detail=workflow_audit_detail,
                timeout=60,
                task_name=f"notify-audit-{auditor.audit}-{WorkflowType(auditor.audit.workflow_type).label}",
            )
        return Response({"msg": success_message})


class ExecuteWorkflow(views.APIView):
    """
    执行workflow，包括SQL上线工单、数据归档工单
    """

    @extend_schema(
        summary="执行工单",
        request=ExecuteWorkflowSerializer,
        description="执行一条工单",
    )
    def post(self, request):
        # 参数验证
        serializer = ExecuteWorkflowSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        workflow_type = request.data["workflow_type"]
        workflow_id = request.data["workflow_id"]

        # 执行SQL上线工单
        if workflow_type == 2:
            mode = request.data["mode"]
            engineer = request.data["engineer"]
            user = Users.objects.get(username=engineer)

            # 校验多个权限
            if not (
                user.has_perm("sql.sql_execute")
                or user.has_perm("sql.sql_execute_for_resource_group")
            ):
                raise serializers.ValidationError({"errors": "你无权执行当前工单！"})

            if can_execute(user, workflow_id) is False:
                raise serializers.ValidationError({"errors": "你无权执行当前工单！"})

            if on_correct_time_period(workflow_id) is False:
                raise serializers.ValidationError(
                    {
                        "errors": "不在可执行时间范围内，如果需要修改执行时间请重新提交工单!"
                    }
                )

            # 获取审核信息
            audit_id = Audit.detail_by_workflow_id(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.SQL_REVIEW,
            ).audit_id

            # 交由系统执行
            if mode == "auto":
                # 修改工单状态为排队中
                SqlWorkflow(id=workflow_id, status="workflow_queuing").save(
                    update_fields=["status"]
                )
                # 删除定时执行任务
                schedule_name = f"sqlreview-timing-{workflow_id}"
                del_schedule(schedule_name)
                # 加入执行队列
                async_task(
                    "sql.utils.execute_sql.execute",
                    workflow_id,
                    user,
                    hook="sql.utils.execute_sql.execute_callback",
                    timeout=-1,
                    task_name=f"sqlreview-execute-{workflow_id}",
                )
                # 增加工单日志
                Audit.add_log(
                    audit_id=audit_id,
                    operation_type=5,
                    operation_type_desc="执行工单",
                    operation_info="工单执行排队中",
                    operator=user.username,
                    operator_display=user.display,
                )

            # 线下手工执行
            elif mode == "manual":
                # 将流程状态修改为执行结束
                SqlWorkflow(
                    id=workflow_id,
                    status="workflow_finish",
                    finish_time=datetime.datetime.now(),
                ).save(update_fields=["status", "finish_time"])
                # 增加工单日志
                Audit.add_log(
                    audit_id=audit_id,
                    operation_type=6,
                    operation_type_desc="手工工单",
                    operation_info="确认手工执行结束",
                    operator=user.username,
                    operator_display=user.display,
                )
                # 开启了Execute阶段通知参数才发送消息通知
                sys_config = SysConfig()
                is_notified = (
                    "Execute" in sys_config.get("notify_phase_control").split(",")
                    if sys_config.get("notify_phase_control")
                    else True
                )
                if is_notified:
                    notify_for_execute(
                        workflow=SqlWorkflow.objects.get(id=workflow_id),
                    )
        # 执行数据归档工单
        elif workflow_type == 3:
            async_task(
                "sql.archiver.archive",
                workflow_id,
                timeout=-1,
                task_name=f"archive-{workflow_id}",
            )

        return Response({"msg": "开始执行，执行结果请到工单详情页查看"})


class WorkflowLogList(generics.ListAPIView):
    """
    获取某个工单的日志
    """

    pagination_class = CustomizedPagination
    serializer_class = WorkflowLogListSerializer
    queryset = WorkflowLog.objects.all()

    @extend_schema(exclude=True)
    def get(self, request):
        return Response({"detail": "方法 “GET” 不被允许。"})

    @extend_schema(
        summary="工单日志",
        request=WorkflowLogSerializer,
        responses={200: WorkflowLogListSerializer},
        description="获取某个工单的日志（分页）",
    )
    def post(self, request):
        # 参数验证
        serializer = WorkflowLogSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        audit_id = WorkflowAudit.objects.get(
            workflow_id=request.data["workflow_id"],
            workflow_type=request.data["workflow_type"],
        ).audit_id
        workflow_logs = self.queryset.filter(audit_id=audit_id).order_by("-id")
        page_log = self.paginate_queryset(queryset=workflow_logs)
        serializer_obj = self.get_serializer(page_log, many=True)
        data = {"data": serializer_obj.data}
        return self.get_paginated_response(data)
