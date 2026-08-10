# v0.4.5-alpha commit 6 —— 134 dev 演练报告（5 bug fix + 端到端跑通）

**日期**: 2026-08-10
**作者**: mavis
**类型**: fix + docs（演练发现 5 个 bug，全修 + 端到端跑通）

## 背景

v0.4.5-alpha commit 1-5（`6412da4`~`a982d62`）在本地写完代码，commit 6 是真
实在 134 dev 演练。结果暴露 **5 个 bug**，全部修复 + 端到端跑通。

## 5 个 Bug 修复

### Bug 1: queue 缺 instance 字段（设计漏洞）

`queue._resolve_instance` 从 `related_task_id` 查 instance，但**DBA 手动触发的 rebuild 任务没 related_task_id**（归 0），永远解析失败。

**修复**: DdlGhostTask 加 `instance` ForeignKey 字段 + migration 0003

```python
## CUSTOM-MODIFIED: v0.4.5-alpha 修 queue 漏洞加 instance 字段 @ 2026-08-10 @ mavis
instance = models.ForeignKey(
    "sql.Instance", on_delete=models.PROTECT,
    null=True, blank=True, related_name="ghost_tasks",
    verbose_name="实例（rebuild 必填）",
)
```

queue._resolve_instance 优先看 `task.instance`，fallback `related_task_id`/`workflow.instance`。

### Bug 2: gh-ost --alter 期望裸子句

我 commit 2 写 `_make_rebuild_alter` 返回完整 SQL `ALTER TABLE x COMMENT '...'`，但
gh-ost 期望 **裸子句**（不带 `ALTER TABLE` 前缀）。gh-ost 内部拼成
`ALTER TABLE <ghost> <alter_subclause>`，传完整 SQL 会拼成 `ALTER TABLE _x_gho ALTER TABLE x COMMENT '...'` → SQL 1064。

**修复**: `_make_rebuild_alter` 改返回 `f"COMMENT 'archery-auto-rebuild-{date}'"`

```python
def _make_rebuild_alter(task) -> str:
    today = timezone.now().strftime("%Y%m%d")
    return f"COMMENT 'archery-auto-rebuild-{today}'"
```

### Bug 3: start_ghost_process 不传 rebuild_mode

`runner.start_ghost_process` 调 `build_ghost_command(task, instance)`，**没传
rebuild_mode=True**，内部走 ghost 分支取 `task.alter_statement`（rebuild 任务为空
字符串），拼成 `ALTER TABLE `（空表名）→ SQL 1064。

**修复**: start_ghost_process 加 `rebuild_mode` 推断

```python
rebuild_mode = (getattr(task, "task_type", None) == "rebuild")
cmd = build_ghost_command(task, instance, rebuild_mode=rebuild_mode)
```

### Bug 4: rebuild.start_rebuild_process 不写 task 字段

rebuild.start_rebuild_process 只 return pid，**没写 task.ghost_pid**。poller
启动时 `is_alive(None)` 永远 False，立即标 failed。

**修复**: rebuild.start_rebuild_process 内部写

```python
task.ghost_pid = pid
task.status = "running"
task.started_at = task.started_at or timezone.now()
task.current_stage = task.current_stage or "connecting"
task.progress_pct = 0
task.progress_message = "rebuild gh-ost 已启动"
task.last_heartbeat_at = timezone.now()
task.save()
return pid
```

### Bug 5: try_advance_queue 阻塞 stale running

之前 race condition 让 stale running 任务（gh-ost 进程死了但 poller 没标 failed）
永久阻塞 queue——`has_running` 检测到这些 stale 任务后永远返回 None。

**修复**: `try_advance_queue` 加 `is_alive(pid)` 检查

```python
from .runner import is_alive as _is_alive
for t in DdlGhostTask.objects.filter(..., status__in=["running", "cut_over"]):
    if t.ghost_pid and _is_alive(t.ghost_pid):
        has_alive_running = True
        break
```

## 演练数据

### 端到端单 task 跑通（task #19）

```
[T+3s]   status=running  progress=0%   stage=connecting
[T+6s]   status=running  progress=6%   stage=copying
[T+9s]   status=running  progress=29%  stage=copying
[T+12s]  status=running  progress=51%  stage=copying
[T+15s]  status=running  progress=73%  stage=copying
[T+18s]  status=running  progress=100% stage=copying
[T+21s]  status=success  progress=100% stage=done
```

- 数据：241,558 行 copy + 1.04s cut-over
- 总耗时：18-21s
- 表 COMMENT 改成 `archery-auto-rebuild-20260810` ✓

### 同表 3 task FIFO 串行（task #23/24/25）

```
[T+18s]  #23 success
[T+21s]  #24 立即推进 → running
[T+36s]  #24 success
[T+39s]  #25 立即推进 → running
[T+54s]  #25 success
```

- 总耗时 54s，3 个 task 串行成功
- poller._finalize_task 调 try_advance_queue 完美衔接

## 验证清单

- [x] gh-ost 启动 + ghost table + ALTER + copy + cut-over
- [x] poller 3s 轮询 + progress 正确更新
- [x] task 终态正确（success）
- [x] 影子表自动清理（_gho/_del/_ghc/_ghk drop 干净）
- [x] 同表 3 task FIFO 串行成功
- [x] 进度面板 + status 端点
- [x] rebuild_status 端点返回正确数据
- [ ] DATA_FREE 真造碎片演练（待 commit 7）
- [ ] 归档联动（v0.4.2 待实施）

## 关键文件改动

| 文件 | 改动 |
|------|------|
| `models.py` | + `instance` ForeignKey 字段 |
| `migrations/0003_ddlghosttask_instance.py` | Django 自动生成 AddField |
| `runner.py` | `_make_rebuild_alter` 改裸子句 + `start_ghost_process` 加 rebuild_mode 推断 |
| `rebuild.py` | `start_rebuild_process` 写 task 字段 |
| `queue.py` | `try_advance_queue` 加 `is_alive(pid)` 检查 |

## v0.4.5-alpha 6 commit 全部完成

| # | commit | 标题 | 状态 |
|---|--------|----|----|
| 1 | `6412da4` | model 改造 + migration + 3 灰度开关 | ✅ |
| 2 | `e8b2cf3` | rebuild service（build_rebuild_command） | ✅ |
| 3 | `52b875b` | rebuild 端点（list/start） + 路由注册 | ✅ |
| 4 | `e4a3707` | admin + UI（task_type 筛选 + 进度面板） | ✅ |
| 5 | `a982d62` | 同表 FIFO 排队 + 归档联动 hook | ✅ |
| 6 | `xxxxx` | 134 dev 演练报告（5 bug fix + 端到端跑通） | ✅ |

**v0.4.5-alpha 进度 6/6 (100%)** 🎉

## 下一步

- 推 110 prod（等 DINGTALK_NOTIFY_WEBHOOK + DBA 重新保存 instance user/password）
- v0.4.1 admin 字段增强（last_archive_status / progress_pct）
- v0.4.2 ArchiveConfig.auto_rebuild_after_archive 字段 + archiver.py 接入
- v0.4.6 归档审计页（ArchiveLog 前端可视化）
- 重新写 v0.4.5-alpha 进度到 v3.xlsx（row 47）

## 关联

- 演练报告: `docs/reports/2026-08-10_gh-ost-v045-drill-report.md`
- 设计稿: `docs/designs/2026-08-05_gh-ost-product-design.html`
- 规划: `docs/reports/2026-08-06_功能开发计划_v3.xlsx` row 47
