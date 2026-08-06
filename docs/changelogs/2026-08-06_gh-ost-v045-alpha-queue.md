# v0.4.5-alpha commit 5 —— queue 排队 + 归档联动

**日期**: 2026-08-06
**作者**: mavis
**类型**: feat（新服务 + 视图改造 + poller 钩子）

## 背景

v0.4.5-alpha commit 3（`52b875b`）的 `rebuild_start` 端点用 409 拒绝同表冲突 —— 太粗暴。
DBA 同时点"归档 + 回收"或两次回收就报错，不友好。

这次改：
1. **新服务 `services/queue.py`** —— 同表 FIFO 排队
2. **视图改造** —— `rebuild_start` 入队即返回（不管同表有没有别人）
3. **poller 钩子** —— 任务终态后自动推进同表下一个
4. **归档联动 helper** —— v0.4.2 接入点

## 改动内容

### 1. `services/queue.py`（新建）

公开 5 个函数 + 1 个内部 helper：

| 函数 | 作用 |
|------|------|
| `find_waiting_for(db, table)` | 查同表 status=queued 的最早 task（FIFO） |
| `get_queue_position(task)` | 查 task 排队位置（1=队头，0=不在队列） |
| `try_advance_queue(db, table)` | 推进同表下一个 waiting task（启动 gh-ost + poller） |
| `trigger_rebuild_after_archive(archive_id)` | 归档完成钩子（v0.4.2 接入点） |
| `_resolve_instance(task)` | 内部 helper，从 `related_task_id` 推断 instance |

**设计**：
- 不引入新表 —— 用 `DdlGhostTask.status='queued'` 当队列状态
- FIFO 排序用 `created_at`
- 重启后队列丢失（task 状态保留，stop 期间 queued 不会被自动启动，要 DBA 重触发）

### 2. `services/poller.py` 改造

`_finalize_task` 末尾对 `task.task_type == 'rebuild'` 调 `try_advance_queue`：

```python
if task.task_type == "rebuild":
    from .queue import try_advance_queue
    try:
        try_advance_queue(task.db_name, task.table_name)
    except Exception:
        logger.exception(...)
```

让 rebuild 任务终态后自动推进同表下一个 waiting task。

### 3. `views.py` 改造

`rebuild_start` 不再 409 拒绝，直接入队：

```python
# 旧逻辑（commit 3）
if conflicting:
    return JsonResponse({"error": "..."}, status=409)

# 新逻辑（commit 5）
task = DdlGhostTask.objects.create(status="queued", ...)
advanced = try_advance_queue(db, table)
if task.id != advanced.id:
    return JsonResponse({..., "queue_position": ..., "msg": "已入队"})
return JsonResponse({..., "pid": task.ghost_pid, "status": "running"})
```

启动 gh-ost + poller 全部走 `try_advance_queue` 统一管。

### 4. v0.4.2 归档联动 hook

`queue.py` 提供 `trigger_rebuild_after_archive(archive_id)` helper：
- 触发条件：`CUSTOM_GH_OST_REBUILD_AUTO_LINK_ARCHIVE=True` 全局开关 + ArchiveConfig.auto_rebuild_after_archive=True（v0.4.2 字段）
- 行为：写新 rebuild task（`related_task_id=archive.id`）+ 立即推进队列
- **接入点（v0.4.2 实施时改）**：`sql/archiver.py` 的 `archive()` 函数末尾添加 4 行 import + 1 行调用

## 兼容性

- ghost 端点全部保留
- `try_advance_queue` 只对 `task_type="rebuild"` 生效（poller 钩子有判断）
- 旧 `rebuild_start` 端点行为变更：返回 200 入队消息，**不再返回 409**（破坏性，但符合 commit 3 拍板的"排队不拒绝"）

## 验证

- `python -m py_compile` queue.py / poller.py / views.py：✅ 通过
- 134 dev 端到端验证：待 commit 6 演练时一起做
  - 关键 case：DBA 同时点 2 个 rebuild 同一表 → 第一个跑，第二个排队
  - 第一个完成后，poller 触发 `try_advance_queue` → 第二个自动启动

## 下一步

- [ ] commit 6: 134 dev 演练（accesscard_black_detail 造碎片 → 重建 + 排队验证）

## 关联

- 设计稿: `docs/designs/2026-08-05_gh-ost-product-design.html` v0.4.5 §7
- 规划: `docs/reports/2026-08-06_功能开发计划_v3.xlsx` row 46
- 共享: `services/rebuild.py`（commit 2）/ `services/poller.py`（commit 1）
- v0.4.2 接入文档：`docs/changelogs/2026-08-06_gh-ost-v045-alpha-queue.md` §4
