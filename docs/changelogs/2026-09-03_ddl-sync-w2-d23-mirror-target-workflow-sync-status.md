# DDL 跨库同步 W2 D23: 镜像工单 status 联动 DdlSyncHistory

> 日期: 2026-09-03 14:48
> 阶段: W2 实施阶段 (D23, 9/3 14:42 业务方反馈 + 排查根因 + 实战修通)
> 模块: `sql/extensions/ddl_sync/services/sync_trigger.py`
> 关联: D11 hotfix 互补 — D11 管"源工单终止→镜像工单", D23 管"镜像工单终态→DdlSyncHistory"

## 背景

D11 hotfix (9/2 实战) 加了 `workflow_terminal_handler` 监听**源工单** status 变终止
→ 联动**镜像工单** status + 联动 `DdlSyncHistory.sync_status` 切终态.

**但缺**: 镜像工单自己执行完 (`workflow_finish`) → DdlSyncHistory 没联动.

## 症状 (9/3 14:42 业务方反馈)

业务方演练 wf#128 (镜像工单) detail 页:
- 业务库 wf#127 "已正常结束"
- alert 块显示 **"状态 同步中 (镜像工单已生成, 还没执行)"**
- DdlSyncHistory id=12 sync_status='syncing'

**业务方期望**: 业务库执行结束 + 镜像工单执行结束 → DdlSyncHistory 显示"已同步"而不是"同步中"

## 根因

D11 `workflow_terminal_handler` 只覆盖**源工单终止**场景:
- `instance.status` 变终止 (workflow_reject/abort/exception)
- 找 `DdlSyncHistory.objects.filter(source_workflow=instance, sync_status='syncing')`
- 联动 target_workflow + DdlSyncHistory 切终态

**没覆盖**镜像工单自己 status 变终态/完成态:
- DBA 手动审 + 手动执行完镜像工单 → `target_workflow.status = workflow_finish`
- 没人监听 target_workflow post_save
- DdlSyncHistory 永远停留在 'syncing'

**实战证据 (9/3 14:42 排查)**:
- wf#125 镜像工单 status='workflow_finish' (DBA 9/3 13:50 已手动执行完)
- DdlSyncHistory id=11 sync_status='syncing'
- 没人联动 — 9 月 3 日 14:42 用户看到"工单执行结束, 状态显示还是同步中"

## 修法

加新 signal handler `target_workflow_status_handler`, 跟 D11 互补.

```python
@receiver(post_save, sender=SqlWorkflow)
def target_workflow_status_handler(sender, instance, created, **kwargs):
    """镜像工单 status 变化 → 联动 DdlSyncHistory 切终态.

    监听 status:
      - workflow_finish → DdlSyncHistory.sync_status = 'synced' (DBA 手动审+执行成功)
      - workflow_reject / workflow_abort → 'skipped' (DBA 拒绝/中止)
      - workflow_exception → 'failed' (执行异常)

    跟 D11 workflow_terminal_handler 互补 (不冲突):
      - D11: instance 是 source_workflow, 找 DdlSyncHistory(source_workflow=instance)
      - D23: instance 是 target_workflow, 找 DdlSyncHistory(target_workflow=instance)
      - D11 触发的 target_workflow.save() 会触发 D23, 但 D11 已经切过 DdlSyncHistory.sync_status
        (不再是 'syncing'), D23 filter sync_status='syncing' 查不到, 不会重复切
    """
    try:
        if created:
            return

        final_statuses = (
            'workflow_finish', 'workflow_reject', 'workflow_abort', 'workflow_exception',
        )
        if instance.status not in final_statuses:
            return

        histories = DdlSyncHistory.objects.filter(
            target_workflow=instance,
            sync_status='syncing',
        )
        if not histories.exists():
            return

        for h in histories:
            try:
                if instance.status == 'workflow_finish':
                    new_sync_status = 'synced'
                elif instance.status == 'workflow_exception':
                    new_sync_status = 'failed'
                else:  # workflow_reject / workflow_abort
                    new_sync_status = 'skipped'

                h.sync_status = new_sync_status
                h.finished_at = timezone.now()
                h.error_message = (
                    (h.error_message + '\n') if h.error_message else ''
                ) + f'镜像工单 #{instance.id} status={instance.status} → DdlSyncHistory 联动切 {new_sync_status}'
                h.save()

                logger.info(...)
            except Exception as e:
                logger.exception(...)  # 单条 history 失败不影响其他

    except Exception as e:
        # 9/1 W1-D3 §9.3 实战 1 兜底: 异常不能阻塞镜像工单状态变更主流程
        logger.exception(...)
```

## 验证 (9/3 14:48 134 dev 演练)

### 演练 1: 重放 wf#125 save → D23 signal 触发 → DdlSyncHistory id=11 切 synced

`scripts/_archive/_d23_push_test.py`:
- 推 sync_trigger.py 134 dev (md5 一致)
- kill 旧 gunicorn + 拉新 (master + 4 worker)
- 重放 wf#125 save() 触发 D23 signal
- 查 DdlSyncHistory id=11 sync_status

演练 1 实战结果:
```
演练前:
  wf#125 status: workflow_finish
  h#11 sync_status: syncing
  h#11 finished_at: None
  h#11 error_message: ''

  re-saving wf#125 to trigger D23 signal...

演练后:
  wf#125 status: workflow_finish
  h#11 sync_status: synced                       ← 切了!
  h#11 finished_at: 2026-09-03 14:48:04.661396  ← 设了!
  h#11 error_message: '镜像工单 #125 status=workflow_finish → DdlSyncHistory 联动切 synced'  ← 写明!
```

**D23 联动 PASS** ✅

### 演练 2 (业务方视角): 134 dev /detail/127/ 验证

- 业务库 wf#127 已正常结束 (用户截图)
- 镜像工单 wf#128 status='workflow_manreviewing' (DBA 还没审, 正常)
- DdlSyncHistory id=12 sync_status='syncing' (DBA 还没审+执行, 正常)

**用户报告的"业务库执行结束, 状态显示同步中"根因澄清**:
- 业务库 wf#127 执行结束 ≠ 镜像工单 wf#128 执行结束
- D9 W1-D3 §5.2 拍板: **镜像工单不自动跑** (DBA 手动审 + 手动执行)
- 业务库执行结束 → 镜像工单还是 syncing (等 DBA 审) — 这是正确行为
- 但**镜像工单执行结束后** (DBA 手动审+执行完) → D23 signal 应该联动 DdlSyncHistory 切 synced

D23 修后:
- 业务库 wf#127 "已正常结束"  ✓
- 镜像工单 wf#128 status='workflow_manreviewing' (等 DBA 审, 正确)  ✓
- DdlSyncHistory id=12 sync_status='syncing' (等镜像工单执行完, 正确)  ✓
- **等 DBA 审+执行完镜像工单 wf#128** → D23 signal 自动切 DdlSyncHistory id=12 sync_status='synced'  ✓

### 演练 3 (DBA 视角): 老的镜像工单 (wf#125) 联动验证

D23 signal 触发场景:
- 9/3 13:50 DBA 手动执行完 wf#125 → 当时没 D23 signal, h#11 留 'syncing'
- 9/3 14:48 D23 signal 上线后, 重放 wf#125 save() → h#11 切 'synced' ✓

**老镜像工单 (D23 上线前已 finish 的) 走"重放 save()" 套路**:
- 用户在浏览器里点 "刷新" 触发 wf.save() 也行
- 或者 DBA 走 Django shell 一次性 UPDATE 全部 syncing 但实际已 finish 的

## 改动文件 (1 文件)

| 文件 | 改动 |
|------|------|
| `sql/extensions/ddl_sync/services/sync_trigger.py` | 新增 `target_workflow_status_handler` signal handler, 监听镜像工单 status 变终态/完成态 → 联动 DdlSyncHistory 切 synced/failed/skipped |

## 同源 entry

- 9/1 W1-D3 §9.3 实战 1 兜底 (signal handler 整个 try/except) — D23 复用
- 9/1 W2 D9 sync_trigger 初版 (workflow_passed_handler)
- 9/2 D11 hotfix (workflow_terminal_handler 源工单终止→镜像工单联动) — D23 互补
- 9/3 D22 镜像工单 group_id 走历史库组 (target_group 字段) — D23 独立但同一文件
- 9/3 D21 sync_trigger.py review_content placeholder — D23 同一文件

## D23 实战新发现 (跨项目可复用, 4 条)

1. **D11 hotfix 只覆盖"源工单终止→镜像工单"**, 缺"镜像工单终态→DdlSyncHistory" — D23 实战发现这个缺口, 跟 D11 互补
2. **D11 跟 D23 不冲突**: D11 切过 DdlSyncHistory.sync_status 后, D23 filter sync_status='syncing' 查不到, 不会重复切
3. **Django post_save 不管 instance 有没有变, 每次 save() 都触发**: D23 演练用 `swf.save()` 重放 (无 update_fields) 就能触发 post_save, 跟预期一致
4. **业务方报告"业务库执行结束, 镜像工单显示同步中"根因澄清**: 业务库执行结束 ≠ 镜像工单执行结束, D9 拍板"镜像工单不自动跑", 业务方误以为"业务库执行完镜像工单也完"是预期错配, D23 实际修的是"DBA 手动审+执行完镜像工单后联动 DdlSyncHistory"

## D23 实战踩坑 (2 条)

1. **D23 演练用 `swf.save()` 重放触发 post_save**: Django 5.2 默认 save() 不管 instance 字段有没有变都触发 post_save, 演练方便; 但生产用 `swf.save(update_fields=['status'])` 不会触发 post_save, 实战时要注意 (DBA 手动审+执行完镜像工单 Archery 走 .save() 不带 update_fields, 触发 post_save, D23 联动 OK)
2. **D23 老镜像工单 (D23 上线前已 finish 的) 走"重放 save()" 套路**: 用户在浏览器里点 "刷新" 触发 wf.save() 也行; 或者 DBA 走 Django shell 一次性 UPDATE 全部 syncing 但实际已 finish 的

## 待办

1. 老的 syncing 但实际已 finish 的镜像工单 兜底 (D23 实战挂账):
   - 134 dev 排查发现 wf#110/112/114/115/117/119/121 全部 status='workflow_abort' 但 DdlSyncHistory 'syncing' (D11 hotfix 时只切了 target_workflow.status, 没切 DdlSyncHistory — 这是 D11 设计漏洞)
   - 但 wf#110/115 D11 hotfix 时已经切了 sync_status='skipped' (D11 修复好了)
   - wf#112/114/117/119/121 留 'syncing' (D11 实战后没 save 这些 target_workflow)
   - 等用户拍板: 是否一次性 SQL UPDATE 全部 syncing 但实际已终态的 DdlSyncHistory, 还是等 D23 上线后用户浏览器刷新自动联动
2. 推 110 prod (D23 1 文件 + D22 6 文件 一次推):
   - sync_trigger.py (D22 + D23 共用, 一个 commit push)
   - D11 hotfix 同步推 (D11 在 9/2 已经实战过 134 dev, 110 prod 还没推 D11, 必带)

## D23 实战后 W2 状态

D6 数据模型 → D7 库对管理 → D8 AJAX 端点 + 前端 → D9 R3 + signal → D10-D12 134 dev 演练 → D13 多表 diff → D14 推 110 prod → D15 字符集 → D16 推 D15 修复 → D17 验证 → D18 alert 块 → D19 alert SQL → D20 挪位置 → D21 placeholder → D22 target_group → **D23 镜像工单 status 联动 DdlSyncHistory**

## D23 实战备份

`/backup/d23_20260903_1442/sync_trigger.py.bak`

## D23 实战后 134 dev gunicorn pids

master 42694 + 4 worker 42746/42830/42843 (D23 演练拉新)
