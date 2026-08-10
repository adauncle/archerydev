# 2026-08-10 · v0.3.0-beta gh-ost 状态机修复

> **作者**: mavis  · **面向 DBA 验收 + 后续 110 PROD 推 v0.3.0 参考**

## 一句话

gh-ost 跟原路径"立即执行"按钮冲突、gh-ost 完成后 SqlWorkflow.status 没同步 → 这俩 bug 之前会让 DBA 详情页看到
"切已完成"但工单仍能再点"立即执行"，触发双 ALTER 锁等待。本次三件全收口：

| 编号 | 修复 | 位置 | 影响 |
|------|------|------|------|
| 修复 1 | `is_can_execute` 联动 `has_active_ghost_task` | `sql/views.py` | 启用 gh-ost 后禁用原路径"立即执行" |
| 修复 2 | `poller._finalize_task` 同步 `SqlWorkflow.status` | `sql/extensions/ddl_gh_ost/services/poller.py` | cut-over 成功 → workflow_finish / 失败 → workflow_exception |
| 修复 3 | 终态 task UI 不再显示启用按钮 | `sql/views.py` + `sql/templates/detail.html` | cancel / success / failed 后"启用 gh-ost"按钮自动消失，详情页展示终态摘要 |

## 背景问题

- **修复 1 触发场景**: 用户在详情页点"启用 gh-ost"按钮 → 启用成功后详情页 reload → 立即执行按钮仍可见。
  DBA 不注意就会再点立即执行，原路径 + gh-ost 双 ALTER 同时跑，业务侧会有 metadata lock 等待。
- **修复 2 触发场景**: gh-ost cut-over success 之后 `DdlGhostTask.status="success"`，但 `SqlWorkflow.status` 还停在
  `workflow_review_pass`。工单列表显示"审核通过"，DBA 又得手动把工单标"已正常结束"。
- **修复 3 触发场景**: 取消 gh-ost 之后 task.status=cancelled（终态）→ 老逻辑里 `has_ghost_task=False` →
  `can_enable_ghost=True` → 详情页又显示"启用 gh-ost"按钮。但用户预期是"我已经取消过，不要再显示"，
  走"重试"端点才是正确路径。

## 修复 1：`is_can_execute` 联动 `has_active_ghost_task`

`sql/views.py` `detail` 视图：

```python
# 关键修复: 修复 #1 - 避免 gh-ost 与原路径"立即执行"冲突
# active 状态 (queued/running/cut_over/precheck_failed) 都视为在跑
has_active_ghost_task = ghost_task.status in (
    "queued", "running", "cut_over", "precheck_failed"
)
is_can_execute = can_execute(request.user, workflow_id) and not has_active_ghost_task
```

**效果**：启用 gh-ost 后立即执行按钮变灰。task 终态（cancelled/failed/rolled_back/success）后
`has_active_ghost_task` 自动 False → 立即执行按钮重新可见。

## 修复 2：`poller._finalize_task` 同步 `SqlWorkflow.status`

`sql/extensions/ddl_gh_ost/services/poller.py` 新增 `_sync_workflow_status`：

```python
_WORKFLOW_STATUS_MAP = {
    "success": "workflow_finish",        # cut-over 成功 → 工单正常结束
    "failed": "workflow_exception",      # gh-ost 失败  → 工单执行异常
    "rolled_back": "workflow_exception", # DBA 手动回滚 → 工单执行异常
    # "cancelled" 不在这里 —— cancel 端点单独处理（保持"用户主动放弃"语义）
}


def _sync_workflow_status(task, new_status: str):
    """CUSTOM: gh-ost 终态时同步 SqlWorkflow.status。

    规则:
      - 仅同步 task_type="ghost"（挂载到 SqlWorkflow）；rebuild task 跳过
      - 仅在工单处于"待执行/执行中"语义时覆盖，避免打乱 manreviewing 等上游状态
      - success → workflow_finish + finish_time
      - failed/rolled_back → workflow_exception + finish_time
    """
    if task.task_type != "ghost":
        return  # rebuild 任务无关联工单
    if not task.workflow_id:
        return  # 没挂工单
    from sql.models import SqlWorkflow
    try:
        wf = SqlWorkflow.objects.get(pk=task.workflow_id)
    except SqlWorkflow.DoesNotExist:
        logger.warning(...)
        return
    target = _WORKFLOW_STATUS_MAP.get(new_status)
    if not target:
        return  # cancelled / queued/running 不动
    if wf.status not in ("workflow_review_pass", "workflow_executing", "workflow_timingtask"):
        # 工单还在审核中, 跑完 gh-ost 也不动它（DBA 还要审）
        return
    wf.status = target
    wf.finish_time = timezone.now()
    wf.save(update_fields=["status", "finish_time"])
```

**关键决策**：

1. **cancelled 不动 wf.status** — 详情页 cancel 按钮是"DBA 否决 gh-ost 走原路径"，工单应保持
   `workflow_review_pass`，让 DBA 立即执行按钮能继续工作。如果切到 `workflow_exception` 会让用户以为是 SQL 失败。
2. **rebuild 任务直接 return** — rebuild 是表级任务不挂 SqlWorkflow，没有 status 可同步。
3. **manreviewing 状态不覆盖** — gh-ost 在审核期间跑完不应该自动通过工单，仍然要 DBA 审核。

## 修复 3：终态 task UI 区分

`sql/views.py` 之前逻辑是 `has_ghost_task = not is_terminal` —— 终态后 has_ghost_task=False，
导致 can_enable_ghost=True 重新显示启用按钮。本次改成：

```python
has_ghost_task = ghost_task is not None     # 已有 task 就一直显示
ghost_task_is_terminal = ghost_task.is_terminal
can_enable_ghost = (perms) and wf.status ok and not has_ghost_task  # 已有 task 不再"启用"
```

`sql/templates/detail.html` 加分支：

```html
{% if ghost_task_is_terminal %}
<!-- 终态：显示结果摘要，不再轮询 -->
<table>最终状态 / 进度 / 耗时 / 错误 / 开始→结束</table>
{% else %}
<!-- active：iframe 轮询 -->
<iframe src="/gh_ost/progress/{{ workflow_detail.id }}/" />
{% endif %}
```

**3 种 UI 状态**：

| 状态 | 详情页表现 |
|------|-----------|
| 无 task + 可启用 | 蓝色 alert "启用 gh-ost" 按钮 |
| task active (queued/running/cut_over/precheck_failed) | iframe 进度面板 + 立即执行按钮**变灰** |
| task terminal (success/failed/cancelled/rolled_back) | 终态摘要表 + 立即执行按钮恢复 + 启用按钮**消失**（要走 retry / rollback 端点） |

## 端到端验证（134 dev 演练）

演练表：`archery_dev.accesscard_black_detail`（433k 行 / 243MB）。

**Case 1：启用 gh-ost → cut-over success → 状态同步**

1. 提交工单 wf=20 走 gh-ost（提交页勾选 + 详情页点启用按钮任一路径）
2. precheck 5/5 通过，task=33 状态 `queued → running → cut_over → success`
3. 切成功后 `SqlWorkflow.status` 应自动从 `workflow_review_pass` 变为 `workflow_finish`
4. 详情页 reload：进度面板消失，显示终态摘要；立即执行按钮**重新可见**但 wf.status 已 finish，can_execute 返回 False
5. 钉钉通知"工单已正常结束"

**Case 2：启用 gh-ost → DBA 取消 → 走原路径**

1. 提交工单 wf=21 走 gh-ost
2. precheck 通过，task=34 状态 `running`
3. DBA 详情页点"取消 gh-ost 迁移"按钮
4. 切成功后 task.status=cancelled；wf.status **保持** `workflow_review_pass`（不要变）
5. 详情页 reload：进度面板变终态摘要；启用按钮**消失**；立即执行按钮**重新可见**
6. DBA 走原路径点立即执行

**Case 3：启用 gh-ost → gh-ost 失败 → 走回滚**

1. 演练：手动 kill gh-ost 子进程模拟失败
2. task.status=failed，wf.status → `workflow_exception`
3. 详情页 reload：终态摘要显示"失败"红色 + error_message
4. DBA 走 rollback 端点 drop 影子表

## 变更文件清单

| 文件 | 变更 |
|------|------|
| `sql/extensions/ddl_gh_ost/services/poller.py` | `_finalize_task` 加 `_sync_workflow_status` 调用 + 映射表 + 函数实现 |
| `sql/views.py` | `has_ghost_task` 改为"有 task 就 True" + 新增 `ghost_task_is_terminal` context |
| `sql/templates/detail.html` | 终态 vs active 两种 UI 分支 + 终态摘要表 |
| `scripts/pack_v030b_state_sync.py` | 打包脚本（dist/ 输出） |

## 110 PROD 推 v0.3.0 前必做

1. ✅ `chown -R archery:archery /var/log/archery/gh_ost`（避开 Permission denied）
2. ✅ `rm -f /tmp/gh-ost.*.sock`（避开 zombie socket 端口冲突）
3. ✅ drop 残留 `_gho/_del/_ghc` 影子表
4. ✅ DBA 手动从 admin 后台**重新保存**所有 instance user/password + sql_config SysConfig
   触发 K2 重新加密（解决 mirage K1 密文 K2 解不开问题）
5. ⚠️ 升级前再确认 ddl_gh_ost 任务没有遗留 active task

## 关联设计

- `docs/designs/2026-08-10_gh-ost-detail-design.html` §7.3 状态机
- `docs/designs/2026-08-05_gh-ost-product-design.html` §启用 gh-ost
