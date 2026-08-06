# v0.4.5-alpha commit 2 —— rebuild service（碎片回收 CLI 构建）

**日期**: 2026-08-06
**作者**: mavis
**类型**: refactor + feat（重构 runner.build_ghost_command + 新建 rebuild service）

## 背景

v0.4.5-alpha commit 1（`6412da4`）改造了 `DdlGhostTask` 模型支持 rebuild 任务。
但 gh-ost CLI 构建逻辑在 `services/runner.py` 的 `build_ghost_command` 里只支持
ghost 场景（从 `task.alter_statement` 取 SQL）。rebuild 场景没有 SQL 工单，
需要单独处理。

## 改动内容

### 1. 重构 `services/runner.py`

`build_ghost_command` 加 `rebuild_mode` 参数：

```python
def build_ghost_command(task, instance=None, rebuild_mode: bool = False) -> List[str]:
    if rebuild_mode:
        # rebuild 任务 workflow=NULL，instance 必传
        if instance is None:
            raise ValueError(...)
        inst = instance
        alter_arg = _make_rebuild_alter(task)  # 空 COMMENT
    else:
        inst = instance or (task.workflow.instance if task.workflow_id else None)
        if inst is None:
            raise ValueError(...)
        alter_arg = task.alter_statement or ...
```

新增 helper `_make_rebuild_alter(task)`：

```python
def _make_rebuild_alter(task) -> str:
    today = timezone.now().strftime("%Y%m%d")
    return (
        f"ALTER TABLE `{task.db_name}`.`{task.table_name}` "
        f"COMMENT 'archery-auto-rebuild-{today}'"
    )
```

**为什么用空 COMMENT 触发重建**：
- 不改列结构 → 业务无感（应用不读 COMMENT 字符串）
- 触发表重建 → InnoDB 重组 page → 回收碎片
- gh-ost 几秒切表（cut-over=atomic）→ 比 OPTIMIZE TABLE 锁表时间短
- 134 dev (8.0) 和 110 prod (5.7) 都支持

### 2. 新建 `services/rebuild.py`

公开 2 个函数 + 1 个内部校验：

| 函数 | 作用 |
|------|------|
| `build_rebuild_command(task, instance)` | 包装 `build_ghost_command(rebuild_mode=True)` |
| `start_rebuild_process(task, instance)` | 包装 `start_ghost_process`，加 task_type / workflow_id 校验 |
| `_validate_rebuild_task(task)` | 校验 task.task_type='rebuild' + workflow_id is None + db/table 必填 |

**共享设施**（沿用 v0.3.0-beta）：
- `services/parser.py` —— stdout 解析（rebuild 输出格式跟 ghost 一样）
- `services/poller.py` —— 3s 轮询 + 状态机（不区分 task_type）
- `services/notify.py` —— 钉钉群通知（best-effort）
- `services/db.py::_get_creds` —— 凭据获取

## 兼容性

- 旧代码调 `build_ghost_command(task)` 不传 `rebuild_mode` → 行为不变（default False）
- 旧代码调 `build_ghost_command(task, instance=inst)` 不变
- 重构 pure additive，**零破坏**

## 验证

- `python -m py_compile` runner.py + rebuild.py：✅ 通过
- 134 dev `makemigrations ddl_gh_ost --check` 仍 0 missing（model 没动）
- 134 dev `migrate ddl_gh_ost --check` 仍 0 阻塞

## 下一步

- [ ] commit 3: views + urls —— `/gh_ost/rebuild/<table_id>/` 端点
- [ ] commit 4: admin + UI —— list_filter 加 task_type + 批量 action
- [ ] commit 5: services/queue.py —— 同表冲突排队 + 关联归档
- [ ] commit 6: 134 dev 演练

## 关联

- 设计稿: `docs/designs/2026-08-05_gh-ost-product-design.html` v0.4.5 §4
- 规划: `docs/reports/2026-08-06_功能开发计划_v3.xlsx` row 43
- 上游: `sql/extensions/ddl_gh_ost/services/runner.py` / 新建 `rebuild.py`
