import simplejson as json
from django.contrib.auth.models import Group
from django.http import HttpResponse

from common.utils.const import WorkflowStatus
from common.utils.extend_json_encoder import ExtendJSONEncoder, ExtendJSONEncoderFTime
from sql.models import SqlWorkflow, WorkflowAudit, WorkflowLog
from sql.utils.resource_group import user_groups


# 获取审核列表
def lists(request):
    # 获取用户信息
    user = request.user

    limit = int(request.POST.get("limit"))
    offset = int(request.POST.get("offset"))
    workflow_type = int(request.POST.get("workflow_type"))
    limit = offset + limit
    search = request.POST.get("search", "")

    # 先获取用户所在资源组列表
    group_list = user_groups(user)
    group_ids = [group.group_id for group in group_list]
    # 再获取用户所在权限组列表
    if user.is_superuser:
        auth_group_ids = [group.id for group in Group.objects.all()]
    else:
        auth_group_ids = [group.id for group in Group.objects.filter(user=user)]

    # 只返回所在资源组当前待自己审核的数据
    workflow_audit = WorkflowAudit.objects.filter(
        workflow_title__icontains=search,
        current_status=WorkflowStatus.WAITING,
        group_id__in=group_ids,
        current_audit__in=auth_group_ids,
        ## CUSTOM-MODIFIED: 9/15 待办列表加 wf.status 守卫, 终态 wf 不显示 (DBA-bug-7) @ 2026-09-15 @ mavis
        ## 根因: 待办列表只看 audit.current_status, 不联动 wf.status. wf 终止后 (workflow_abort/finish/exception/reject)
        ##       audit 表没联动 (D11 hotfix workflow_terminal_handler 漏 audit 联动), 待办列表还显示终态 wf
        ##       (马克群 9/15 18:16 反馈 wf#4827-#4830 4 个镜像工单已经 workflow_abort 还出现)
        ## 修法: 加 wf.status__in 守卫, 终态 wf 直接排除 (前端兜底, 不依赖 audit 联动)
        ## 关联: docs/changelogs/2026-09-15_todo-list-final-state-wf.md
        ## 实战新发现 (跨项目可复用): 待办/审批列表 query 设计 checklist 必加 1 条: 必加 wf.status IN (活态) 兜底过滤
        workflow_id__in=SqlWorkflow.objects.filter(
            status__in=("workflow_manreviewing", "workflow_review_pass", "workflow_timingtask")
        ).values_list("id", flat=True),
    )
    # 过滤工单类型
    if workflow_type != 0:
        workflow_audit = workflow_audit.filter(workflow_type=workflow_type)

    audit_list_count = workflow_audit.count()
    audit_list = workflow_audit.order_by("-audit_id")[offset:limit].values(
        "audit_id",
        "workflow_type",
        "workflow_title",
        "create_user_display",
        "create_time",
        "current_status",
        "audit_auth_groups",
        "current_audit",
        "group_name",
    )

    # QuerySet 序列化
    rows = [row for row in audit_list]

    result = {"total": audit_list_count, "rows": rows}
    # 返回查询结果
    return HttpResponse(
        json.dumps(result, cls=ExtendJSONEncoder, bigint_as_string=True),
        content_type="application/json",
    )


# 获取工单日志
def log(request):
    workflow_id = request.POST.get("workflow_id")
    workflow_type = request.POST.get("workflow_type")
    try:
        audit_id = WorkflowAudit.objects.get(
            workflow_id=workflow_id, workflow_type=workflow_type
        ).audit_id
        workflow_logs = (
            WorkflowLog.objects.filter(audit_id=audit_id)
            .order_by("-id")
            .values(
                "operation_type_desc",
                "operation_info",
                "operator_display",
                "operation_time",
            )
        )
        count = WorkflowLog.objects.filter(audit_id=audit_id).count()
    except Exception:
        workflow_logs = []
        count = 0

    # QuerySet 序列化
    rows = [row for row in workflow_logs]
    result = {"total": count, "rows": rows}
    # 返回查询结果
    return HttpResponse(
        json.dumps(result, cls=ExtendJSONEncoderFTime, bigint_as_string=True),
        content_type="application/json",
    )
