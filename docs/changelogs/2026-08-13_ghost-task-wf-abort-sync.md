# 2026-08-13 DdlGhostTask 跟 SqlWorkflow 终止状态联动 (抽公共 helper)

## 业务背景

8/13 用户反馈工单 #38 (status=`workflow_abort` "人工终止流程") 的 DdlGhostTask task #46 状态还是 `queued` (排队中)。

详情页出现状态分裂:
- Archery 上游工单: 人工终止流程 (红色字)
- gh-ost 进度面板: 排队中 0% (没启动)
- 任务管理列表页: task #46 排队中, 0/0 rows

DBA 视觉混乱: 不知道这个 task 是不是该处理、是不是该清理。

## 根因

工单 #38 是通过**钉钉 OA 终止动作**触发的, 走的是 `sql/extensions/dingtalk_oa/services/oa_callback_handler.py:288-339` `_apply_abort` 函数:

```python
SqlWorkflow.objects.filter(id=audit_locked.workflow_id).update(
    status="workflow_abort"
)
```

直接 `.update()`, 绕过了 `sql/sql_workflow.py:482-564` `cancel()` 视图里的清理 DdlGhostTask 逻辑
(8/11 commit `664058c` 加的, 在 `if getattr(settings, "CUSTOM_GH_OST_ENABLED", False):` 块里)。

**所以两个终止路径**:
1. Archery 上游 cancel 视图 (`/cancel/` POST, 流程里点的"终止"): 8/11 加的清理逻辑生效 ✓
2. **钉钉 OA `_apply_abort` 回调**: 8/11 漏改这条路径, 直接 update status 绕过了清理 ✗

## 修法

### 修法: 抽公共 helper, 两个路径都调

新建 `sql/services/ghost_task_sync.py` (~75 行):

```python
def cleanup_pending_ghost_tasks(workflow, operator: str, reason: str = "") -> int:
    """工单被终止/拒绝/撤回时, 清理该工单下所有非终态 DdlGhostTask。

    业务规则:
      - 仅在 CUSTOM_GH_OST_ENABLED=True 时生效
      - 清理 status in (pending, precheck_failed, queued, running, cut_over) 的 task
      - 改成 cancelled + 写 finished_at + 在 error_message 追加 [aborted] 来源
      - 异常不抛 (try/except + logger.exception), 避免影响主流程 (工单终止)
    """
    if not getattr(settings, "CUSTOM_GH_OST_ENABLED", False):
        return 0
    try:
        from sql.extensions.ddl_gh_ost.models import DdlGhostTask
        pending_tasks = DdlGhostTask.objects.filter(
            workflow=workflow,
            status__in=("pending", "precheck_failed", "queued", "running", "cut_over"),
        )
        cleaned = 0
        now = timezone.now()
        for t in pending_tasks:
            t.status = "cancelled"
            t.finished_at = now
            t.error_message = (
                (t.error_message or "")
                + f"\n[aborted] 工单被 {operator} {reason}"
            ).strip()
            t.save()
            cleaned += 1
        if cleaned:
            logger.info(
                "工单 #%s 终止时清理了 %s 个非终态 DdlGhostTask (operator=%s, reason=%s)",
                workflow.id, cleaned, operator, reason,
            )
        return cleaned
    except Exception:
        logger.exception("清理 DdlGhostTask 失败: wf=%s", getattr(workflow, "id", None))
        return 0
```

### 调用方 1: `sql/sql_workflow.py:482-564` cancel 视图 (替换原 inline 代码)

```python
sql_workflow.status = "workflow_abort"
sql_workflow.save()
## CUSTOM-MODIFIED: 抽公共 helper (cancel 视图 + OA callback 都用) @ 2026-08-13 @ mavis
from sql.services.ghost_task_sync import cleanup_pending_ghost_tasks
cleanup_pending_ghost_tasks(
    sql_workflow,
    operator=request.user.username,
    reason="拒绝/撤回",
)
```

### 调用方 2: `oa_callback_handler.py:288-339` `_apply_abort` 函数 (新增)

```python
SqlWorkflow.objects.filter(id=audit_locked.workflow_id).update(
    status="workflow_abort"
)

## CUSTOM-MODIFIED: 钉钉 OA 终止时清理 DdlGhostTask @ 2026-08-13 @ mavis
sql_workflow_aborted = SqlWorkflow.objects.get(id=audit_locked.workflow_id)
from sql.services.ghost_task_sync import cleanup_pending_ghost_tasks
cleanup_pending_ghost_tasks(
    sql_workflow_aborted,
    operator=actor_label["operator"],
    reason=f"OA 终止: {remark or '(无备注)'}",
)
```

## 演练 (134 dev 4 Case + 静态检查)

`scripts/drill_ghost_task_wf_abort_sync.py` + `_check_apply_abort.py`

| Case | 内容 | 结果 |
|------|------|------|
| 1 | 模拟 OA 终止: 调 helper 修工单 #38 (实际数据) | task #46 queued → cancelled, finished_at 填, error_message `[aborted] 工单被 oa_tester_1 OA 终止: 演练验证` ✓ |
| 2 | 已终态 task 再调 helper, 期望幂等 noop | cleaned=0 ✓ |
| 3 | 重置 task 状态回 queued, 验 helper 可重复清理 | cleaned=1 ✓ |
| 4 | 临时关掉 `CUSTOM_GH_OST_ENABLED`, helper 应 noop | cleaned=0, task 状态保持 queued ✓ |
| 静态 | `_apply_abort` 函数体 grep 检查 | 5/5 通过 (含 cleanup_pending_ghost_tasks 调用 + import + operator 写入) ✓ |

**清理**: 演练后 task #46 状态完整还原 (queued / finished_at=None / error_message="")

## 验证清单

- [x] 134 dev 4 Case drill 全过 (真实工单 #38 + task #46)
- [x] _apply_abort 函数体静态检查全过
- [x] gunicorn reload 后代码生效
- [ ] **用户浏览器手动验收**: 用 oa_tester_1 登录 134 dev 9003, 在钉钉 OA 触发一次工单终止, 验证 gh-ost 任务管理列表页 task 状态立刻变 cancelled
- [ ] 工单 #38 task #46 实际修复 (drill 演练后已清理但 task 状态还原回 queued, 用户需要确认是否真要清理; 如果要清, 我手动调一次 helper)

## 风险

- `sql/services/` 目录之前没文件 (8/13 新建), Python 路径确认 `__init__.py` 已存在 ✓
- helper 异常不抛, 不会阻塞主流程 (工单终止)
- helper 只清理 `pending/precheck_failed/queued/running/cut_over` 状态, 不影响 `success/failed/cancelled/rolled_back` 终态

## 同源 entry

- 8/11 commit `664058c` (v0.3.0-beta 审批守卫) 在 cancel 视图加清理逻辑, 但漏改 OA callback
- 8/13 commit `d5f88d1` (OA 3 级审批配置生效) 走的还是 _apply_abort, 没补这个
- 8/13 commit `9eb6c9e` (cancel 端点返 JSON 错误码) 修的是同 task 但 cancel 按钮 perm 守卫, 跟这个状态同步 bug 无关
