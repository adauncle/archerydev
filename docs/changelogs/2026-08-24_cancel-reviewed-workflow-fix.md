# 2026-08-24 cancel 已审核工单抛 "当前审批权限组不存在" bug 修复

## 摘要

修复 Archery 上游 bug: 业务用户/DBA 在工单详情页点"终止流程"按钮, 取消已审核通过的工单, 报错"当前审批权限组不存在, 请联系管理员检查并清洗错误数据"。

## 根因

`sql/utils/workflow_audit.py:430-435` `can_operate` 函数, REJECT 路径无条件查 `Group.objects.get(id=self.audit.current_audit)`。

但**已审核通过的工单** `current_audit = "-1"` (operate_pass 最后一个节点时设置, `workflow_audit.py:477`), `-1` 不是有效的 Group id, 必抛 `Group.DoesNotExist`。

**触发场景** (8/24 用户报):
- 工单 #88 状态 `workflow_review_pass` (3 级审批流 14,15,3 全过)
- user (DBA / admin) 不是 engineer, 走 sql_workflow.py:506-507 `action = WorkflowAction.REJECT`
- can_operate 走 line 430-435 REJECT 路径 → Group.objects.get(id="-1") 失败 → 抛 "当前审批权限组不存在"

**为什么 Archery 上游不修**:
- 这是 Archery 上游历史 bug, 上游逻辑假设 cancel 流程总是用 ABORT (走 line 411-414 不会查 Group)
- 但 cancel 流程里 sql_workflow.py:506-507 把"有 sql_review perm 但不是 engineer" 的人映射到 REJECT, REJECT 在已审核工单上就崩
- 走 REJECT 路径时, current_audit 检查无意义 (已审核完的工单没有"当前节点"概念), 应该跳过

## 修法

`sql/utils/workflow_audit.py:415-440` `can_operate` REJECT 路径, 在查 Group 前先判断:

```python
# CUSTOM-MODIFIED: 8/24 修 cancel 已审核工单抛 "审批权限组不存在" 错
if action == WorkflowAction.REJECT and self.audit.current_audit == "-1":
    # 已审核通过的工单, 取消走 REJECT 路径
    # 权限已经在 can_cancel + has_perm 检查过, 这里直接放过
    return True
```

**修法思路**:
- 已审核通过的工单 (current_audit == "-1") 跳过 Group 检查
- 权限已经在 can_cancel (sql/utils/sql_review.py:88-112) + has_perm("sql.sql_review") 检查过
- caller 决定谁是合法的"驳回人" (DBA / 提交人 / 审核人), 不需要再二次检查 group membership

**为什么不修 sql_workflow.py:506-507 让 DBA 走 ABORT**:
- ABORT 语义是"提交者撤回", DBA 用 ABORT 违和
- ABORT 不改 current_audit, REJECT 改成 current_audit="-1" (workflow_audit.py:531)
- 工单 #88 当前 status=workflow_review_pass, 操作后应该改成 workflow_abort / workflow_reject
  - ABORT: workflow_abort (cancel 流程 sql_workflow.py:518 强制设了 workflow_abort)
  - REJECT: workflow_rejected (但 status 字段被 sql_workflow.py:518 覆盖成 workflow_abort)
  - 所以现在 cancel 流程无论 action 是什么, status 都是 workflow_abort
  - REJECT 走 operate_reject 后, workflow_audit 表 current_status = REJECTED, 但 workflow 表 status 被强制覆盖成 ABORT
  - 这就是为什么用户看不到 REJECTED 状态, 都叫 "终止"

## 演练 (134 dev, 8/24 14:35)

**场景**:
- 工单 #88 status=workflow_review_pass, current_audit="-1"
- user 是有 sql_review perm 的 DBA (非 engineer), 走 REJECT 路径
- 修前: 抛 "当前审批权限组不存在"
- 修后: 走 cancel 流程, workflow.status = "workflow_abort"

**演练脚本**: `scripts/_archive/_drill_cancel_8_24_20260824.py`

**演练步骤** (Django shell):
1. 查工单 #88, 确认 status=workflow_review_pass, current_audit="-1"
2. 模拟 DBA (有 sql.sql_review perm) 走 can_operate(REJECT, actor)
3. 修前抛 "当前审批权限组不存在"
4. 修后返回 True, 可以走 operate_reject

## 推 110 必做

跟 commit `9d66064` (8/24 gh-ost precheck 修正) 一起推, 业务代码改动, 不需要新加 5 步必做步骤。

## 文件改动

- `sql/utils/workflow_audit.py` (1 处改动 + CUSTOM-MODIFIED 注释头, ~10 行)

## 关联

- 8/18 教训: 业务配置 (审批组 ID / 角色 / perm) 必看实际审批日志, 不要从代码脑补
- 8/24 教训 (新): Archery 上游 cancel 流程 + REJECT 路径在已审核工单崩
- 推 110 必做 5 步必做: commit `035850f` + 步骤 13 (8/24 reload SOP)
- troubleshooting.md: 这条 bug 的根因 (8/24 实战, 业务用户报)
