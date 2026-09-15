# 待办列表 终态 wf 显示修复 (DBA-bug-7)

> **DBA 实战**: 马克群 9/15 18:16 在 110 prod `/workflow/` 待办列表反馈 "wf#4827-#4830 4 个镜像工单已经 workflow_abort 还出现, 这种你觉得合理吗?"
>
> 9/15 18:30 排查 `_todo_list_wf_110.py` + `_wf4827_log_110.py` 推 110 prod 跑, 锁根因。

## 现象

- **触发工单**: 业务方实战 wf#4827-#4830 (DDL 跨库同步镜像工单, 目标 = history 变更 / hly_accesscard)
- **现状**:
  - 登录用户 mkq (马克群, is_superuser=False, groups=['DBA']) 看 `/workflow/` 待办列表
  - wf#4827 / #4828 / #4829 / #4830 4 个镜像工单**已经 workflow_abort** (业务方 gcl 自己 abort)
  - 但待办列表**仍然**显示这 4 个 wf, 审核状态 "待审"
  - wf#4827-#4830 audit 表: `current_status=0` (WAITING), `current_audit=3`, `next_audit=-1`

## 根因 (2 层)

### 1. Archery 上游设计 bug — 待办列表只看 audit, 不联动 wf.status

```python
# common/workflow.py:32 (老逻辑)
workflow_audit = WorkflowAudit.objects.filter(
    workflow_title__icontains=search,
    current_status=WorkflowStatus.WAITING,  # ← 只看 audit 表
    group_id__in=group_ids,
    current_audit__in=auth_group_ids,
)
```

**问题**: 待办列表过滤 `audit.current_status == WAITING`, 但 wf 终止后 audit 没联动, 待办列表**仍然**返回终态 wf。

### 2. D11 hotfix + D23 联动是局部的 — 没联动 audit.current_status

```python
# sql/extensions/ddl_sync/services/sync_trigger.py:362 D11 hotfix
@receiver(post_save, sender=SqlWorkflow)
def workflow_terminal_handler(sender, instance, created, **kwargs):
    """源工单终止 → 联动镜像工单同样终止 + DdlSyncHistory 切终态."""
    # 联动 wf.status = workflow_abort
    h.target_workflow.status = instance.status
    h.target_workflow.save()
    # 联动 DdlSyncHistory.sync_status = skipped/failed
    h.save()
    # ❌ 没联动 audit.current_status = ABORTED
```

**问题**: D11 hotfix (9/2) 只联动 wf.status + DdlSyncHistory, **没联动** audit 表。导致 wf.status=workflow_abort 但 audit.current_status=WAITING (实测确认 wf#4827-#4830)。

## 修法 (A+D 组合, 跟 DBA-bug-6 / D11 hotfix 同款实战接龙)

### 修法 A: common/workflow.py 加 wf.status 守卫 (前端兜底)

```python
# 修后 (line 32)
workflow_audit = WorkflowAudit.objects.filter(
    ...
    current_status=WorkflowStatus.WAITING,
    group_id__in=group_ids,
    current_audit__in=auth_group_ids,
    ## CUSTOM-MODIFIED: 9/15 待办列表加 wf.status 守卫 (前端兜底)
    workflow_id__in=SqlWorkflow.objects.filter(
        status__in=("workflow_manreviewing", "workflow_review_pass", "workflow_timingtask")
    ).values_list("id", flat=True),
)
```

**关键**: 加 `workflow_id__in` 子查询过滤 wf.status, 终态 wf 直接排除, 不依赖 audit 状态。

### 修法 D: sync_trigger.py 两个 handler 联动 audit.current_status (后端联动)

```python
# D11 hotfix workflow_terminal_handler
@receiver(post_save, sender=SqlWorkflow)
def workflow_terminal_handler(sender, instance, created, **kwargs):
    ...
    h.target_workflow.status = instance.status
    h.target_workflow.save()
    # NEW: 联动 target_workflow audit 表
    from sql.models import. WorkflowAudit
    from common.utils.const import WorkflowStatus
    target_audits = WorkflowAudit.objects.filter(workflow_id=h.target_workflow_id)
    for ta in target_audits:
        ta.current_status = WorkflowStatus.ABORTED  # 或对应 REJECTED/ABORTED
        ta.next_audit = "-1"
        ta.save()
    h.save()

# D23 target_workflow_status_handler 同样加 audit 联动
```

**关键**: 后端联动 audit, 让 audit.current_status 跟 wf.status 同步, 待办列表过滤**自然**就不返回终态 wf。

## 验证

### 134 dev

- 演练脚本 (`_dba_bug7_drill_134.py`): 造一个 wf_abort 终态 wf + 验证
  - audit.current_status = ABORTED (D 修法生效)
  - 待办 API 返回 0 行 (A + D 都生效)
  - 活态 wf 待办列表**正常**显示

### 110 prod

- 推完 common/workflow.py + sync_trigger.py + kill -TERM 5 workers reload (9/15 实战法)
- 演练: wf#4827-#4830 终态工单 audit.current_status 联动 ABORTED
- mkq 登录 `/workflow/` 待办列表 wf#4827-#4830 不再显示
- 业务方回归: 活态 wf 待办列表**正常**显示

## 实战新发现 (跨项目可复用)

- **Archery 上游设计漏洞**: 待办/审批列表 query 只看 audit 表, 不联动 wf.status (DBA-bug-7) - 跨项目写待办/审批列表 query 时, 必加 `wf.status IN (活态)` 兜底过滤 (前端兜底, 不依赖 audit 联动). 实战踩坑: 9/15 马克群反馈 wf#4827-#4830 4 个镜像工单 workflow_abort 还出现, 排查发现 `common/workflow.py:32` 只看 `audit.current_status=WAITING`, **不联动 wf.status**, 终态 wf 还在列表里.
- **D11 hotfix 联动是局部的** (DBA-bug-7 实战新发现) - 跨项目写 wf.status 联动时, 必**同时联动**所有相关表 (wf.status + audit.current_status + DdlSyncHistory), 别只联动一两个表. 实战踩坑: 9/2 D11 hotfix `workflow_terminal_handler` 只联动 wf.status + DdlSyncHistory, 没联动 audit 表, 导致 audit.current_status 仍是 WAITING, 待办列表不更新. 修法: **必加 audit.current_status 联动** (跟 D25 error_message 联动一致).
- **reload gunicorn 必排除 master** (9/15 实战新发现 - 已经入库) - 跨项目 reload gunicorn 必先找 master pid (启动时间最早的), kill -TERM 只针对非 master 的 worker pids, master 不动.

## 同源 entry (实战接龙)

- 9/11 17:55 DBA-bug-1 (大表 DDL alert 解析 drop index 失败)
- 9/11 18:50 DBA-bug-2 (反引号 schema 解析 + 主页面 banner)
- 9/11 19:30 DBA-bug-3 (ADD/DROP INDEX 大表 alert 丢失)
- 9/11 20:10 DBA-bug-3 hotfix (Django 跨行 {# #} 注释)
- 9/12 10:50 DBA-bug-4 (DDL 跨库业务方选错库大表 alert 不触发)
- 9/12 10:55 DBA-bug-5 (DDL 跨库镜像工单 + 历史库表不存在)
- 9/12 11:35 DBA-bug-5a (sync_trigger.py regex 漏反引号 schema)
- 9/14 10:11 archery 账号密码被改 (DBA 一条龙全包实战)
- 9/15 16:43 镜像工单取消按钮终态隐藏 (DBA-bug-6)
- 9/15 17:34 gunicorn reload 事故 (实战新发现入库)
- **9/15 18:16 待办列表终态 wf 显示修复 (DBA-bug-7, A+D 组合)**