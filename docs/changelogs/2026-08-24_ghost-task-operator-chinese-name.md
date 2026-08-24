# 2026-08-24 ghost task operator 显示 "中文名 (审批节点)"

## 摘要

修复 gh-ost 任务详情页"错误/备注" 栏显示 "工单被 mkq 拒绝/撤回" 的 UX 问题, 改成显示"工单被 马克群 (研发组长) 审批驳回" 之类的完整中文信息。

## 根因

`sql/sql_workflow.py:529` (cancel 视图) 用 `request.user.username` 拼 error_message:
```python
cleanup_pending_ghost_tasks(
    sql_workflow,
    operator=request.user.username,  # "mkq" 拼音缩写
    reason="拒绝/撤回",               # 写死
)
```

业务用户/DBA 看到 "工单被 mkq 拒绝/撤回", 不知道 mkq 是谁, 也不知道是"驳回"还是"撤回"。

**两个问题**:
1. **operator 用 username** (拼音缩写 "mkq") 而不是 display (中文名"马克群")
2. **reason 写死 "拒绝/撤回"** - 但 action 有两种 (ABORT 工程师撤回 / REJECT DBA 驳回), 工单 #89 user 是 DBA 走 REJECT 路径, 显示"拒绝/撤回" 措辞不准
3. **没拼审批节点信息** - 业务用户不知道是哪个审批节点驳回的 (研发组长 / DBA组长 / DBA)

## 修法

`sql/sql_workflow.py:498-554` cancel 视图:

```python
## 1. reason 跟 action 联动 (不再写死)
if action == WorkflowAction.ABORT:
    abort_reason = "提交人撤回"
else:  # REJECT
    abort_reason = "审批驳回"

## 2. operator 显示 "中文名 (审批节点)"
operator_cn = request.user.display or request.user.username
operator_with_group = operator_cn  # fallback
try:
    from django.contrib.auth.models import Group
    wf_audit = sql_workflow.get_audit() if hasattr(sql_workflow, "get_audit") else None
    group_id_str = None
    if wf_audit and wf_audit.current_audit and wf_audit.current_audit != "-1":
        group_id_str = wf_audit.current_audit  # 审核中工单
    elif sql_workflow.audit_auth_groups:
        group_id_str = (sql_workflow.audit_auth_groups or "").split(",")[0].strip()  # 兜底
    if group_id_str:
        try:
            g = Group.objects.get(id=int(group_id_str))
            operator_with_group = f"{operator_cn} ({g.name})"
        except (Group.DoesNotExist, ValueError):
            pass
except Exception:
    pass  # 拿 group 失败不影响主流程

cleanup_pending_ghost_tasks(
    sql_workflow,
    operator=operator_with_group,
    reason=abort_reason,
)
```

**关键点**:
1. **reason 跟 action 联动** - 不再写死"拒绝/撤回"
2. **operator 用 display 优先** - 拿中文名, username 兜底
3. **拼审批节点** - 优先用 `wf.audit.current_audit` 拿 group, 兜底用 `wf.audit_auth_groups` 第一个
4. **拿不到 group fallback** - 只显示 display, 不阻塞主流程
5. **OA 回调路径不动** - `oa_callback_handler.py:343` 已经传中文名 (用 `actor_label["operator"]`)

## 演练 (134 dev, 8/24 16:50)

**工单 #89** (DBA 马克群 取消):
- `User mkq: display='马克群'`
- `Workflow #89: status=workflow_abort, audit_auth_groups='14,3'`
- `WorkflowAudit: current_audit=-1` (审核已通过)
- 兜底取 `audit_auth_groups` 第一个 group = '14'
- 查 `Group.objects.get(id=14).name = '研发组长'`
- **最终 operator: `马克群 (研发组长)`**
- **error_message: `[aborted] 工单被 马克群 (研发组长) 审批驳回`**

**演练脚本**: `scripts/_archive/_drill_chinese_name_2_20260824.py`

## 边界 case

| 工单状态 | wf.audit.current_audit | 走的分支 | 显示 |
|---|---|---|---|
| `workflow_manreviewing` (审核中) | "14" (研发组长) | current_audit | `马克群 (研发组长)` |
| `workflow_review_pass` (已通过) | "-1" | audit_auth_groups 第一个 | `马克群 (研发组长)` |
| `workflow_abort` (已终止) | "-1" | audit_auth_groups 第一个 | `马克群 (研发组长)` |
| `workflow_review_reject` (已驳回) | "-1" | audit_auth_groups 第一个 | `马克群 (研发组长)` |
| wf 拿不到 audit | N/A | audit_auth_groups | `马克群 (研发组长)` |
| group 不存在 | N/A | fallback | `马克群` (无节点) |

## 推 110 必做

跟 commit `0b62856` (column_diff modal template) 一起推 110, 5 步必做步骤 13 覆盖。

## 文件改动

- `sql/sql_workflow.py` (1 处: cancel 视图 operator + reason 逻辑)

## 关联

- 8/11 commit `664058c` 审批守卫 (cancel 视图加清理逻辑)
- 8/13 抽公共 helper (`sql/services/ghost_task_sync.py` + `oa_callback_handler.py:343`)
- 8/17 修 cancel 流程 (commit `25ce9b3`)
- 8/24 一天 6 个 bug 修复中的第 6 个
