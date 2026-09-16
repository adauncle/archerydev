# v0 gh-ost 智能模式设计稿 (5A 拍板, 9/16 21:42 阿达叔叔)

> **状态**: 设计稿 v1.0
> **作者**: mavis @ 2026-09-16 21:45
> **拍板**: 阿达叔叔 21:42 "同意 5A"
> **关联事件**: DBA-bug-9 (gh-ost 多 statement 工单支持) + DBA-bug-9.5 (前端可见 bug)
> **关联设计稿**: docs/designs/2026-09-16_dba-bug-9-ghost-multi-statement-design.md

---

## 一句话总结

**业务方选中 gh-ost → 工单页可下拉选择 gh_ost_mode = smart / all_ghost / all_native。默认 smart 按表大小自动分流(大表 gh-ost task 串行依赖链,小表原生 ALTER); gh-ost task 跟小表 ALTER 都完成 wf.status 才改 workflow_finish。**

---

## 1. 背景

DBA-bug-9 (9/16 18:30 拍板 D 方案) 实现的是 "工单含多条 ALTER 都走 gh-ost" 简化模型,但实际生产场景更细:

- 一张工单可能含 4 条 ALTER,有的表 200k 行 (大表),有的表 1k 行 (小表)
- 小表走 gh-ost 是"杀鸡用牛刀":建影子表 + 复制 + 切流 比直接 ALTER 慢 5-10 秒
- 业务方不应该被强制"全走 gh-ost",应该可以选:
  - smart (智能分流,默认)
  - all_ghost (强制全走 gh-ost)
  - all_native (强制全走原生 ALTER)

---

## 2. 5A 拍板 (9/16 21:42 阿达叔叔)

| # | 决策点 | 拍板 |
|---|---|---|
| 1 | 大表阈值 | **A: 复用现有 `CUSTOM_BIG_TABLE_ROW_THRESHOLD=100000` / `CUSTOM_BIG_TABLE_SIZE_THRESHOLD_MB=100`** |
| 2 | 小表走哪条路径 | **A: 走 `mysql.execute()` 原生连接数据库直连 ALTER** |
| 3 | task 调度 | **A: 串行 — gh-ost task 启动前等前一个 task 进 success 状态 (`task.depends_on` 依赖链)** |
| 4 | gh_ost_mode 选法 | **A: 工单提交页加下拉框 (智能 / 全部 gh-ost / 全部原生)** |
| 5 | wf.status 控制 | **A: poller 统一 — 全部 ghost task 终态 + 全部小表 ALTER 完成 才改 wf.status** |

---

## 3. 数据模型改造

### 3.1 SqlWorkflow 加 `gh_ost_mode` 字段

```python
## CUSTOM-MODIFIED: v0 gh-ost 智能模式加 gh_ost_mode 字段 @ 2026-09-16 @ mavis
GH_OST_MODE_CHOICES = (
    ("smart", "智能 (默认: 大表 gh-ost + 小表原生 ALTER)"),
    ("all_ghost", "全部 gh-ost (强制所有 ALTER 走 gh-ost)"),
    ("all_native", "全部原生 ALTER (强制所有 ALTER 走原生)"),
)
gh_ost_mode = models.CharField(
    "gh-ost 模式", max_length=16, choices=GH_OST_MODE_CHOICES,
    default="smart", db_index=True,
    help_text="smart=默认智能分流;all_ghost=全部 gh-ost;all_native=全部原生",
)
```

### 3.2 SqlWorkflow 加 `native_alter_results` 字段

```python
## CUSTOM-MODIFIED: v0 gh-ost 智能模式存小表原生 ALTER 结果 @ 2026-09-16 @ mavis
native_alter_results = models.JSONField(
    "小表原生 ALTER 结果", default=list, blank=True,
    help_text="smart 模式下小表原生 ALTER 的执行结果 [{statement_index, db, table, alter, status, errormessage, started_at, finished_at}, ...]",
)
```

### 3.3 DdlGhostTask 加 `depends_on` 字段

```python
## CUSTOM-MODIFIED: v0 gh-ost 智能模式加 task 依赖链 @ 2026-09-16 @ mavis
## 业务: 多 ghost task 时按 statement_index 串行, 前一个 task success 才能起下一个
depends_on = models.ForeignKey(
    "self", on_delete=models.SET_NULL,
    null=True, blank=True, related_name="dependent_tasks",
    help_text="串行依赖: 本 task 启动需要 depends_on 任务 success 状态",
)
```

---

## 4. gh-ost 智能模式执行链路

### 4.1 启用阶段 (`_enable_ghost_for_workflow`)

```python
def _enable_ghost_for_workflow(workflow, created_by):
    parsed = _parse_all_statements(workflow.sql_content)
    non_alter = [s for s in parsed if s["stmt_type"] not in ("ALTER", "USE")]
    if non_alter:
        return {"ok": False, "error": "gh-ost 模式仅支持 ALTER..."}

    gh_ost_mode = workflow.gh_ost_mode  # smart/all_ghost/all_native
    tasks_to_create = []
    small_alters = []
    for idx, stmt in enumerate(parsed):
        if stmt["stmt_type"] == "USE":
            continue
        db = stmt["db"] or workflow.db_name
        table = stmt["table"]
        size_info = _get_table_size_info(workflow.instance, db, table)
        is_big = (size_info and size_info["rows"] >= ROW_THRESHOLD
                  or size_info["size_mb"] >= SIZE_THRESHOLD_MB)

        if gh_ost_mode == "all_ghost" or (gh_ost_mode == "smart" and is_big):
            # 大表 → 创建 ghost task
            tasks_to_create.append((idx, db, table, stmt))
        elif gh_ost_mode == "all_native" or (gh_ost_mode == "smart" and not is_big):
            # 小表 → 加入 small_alters 列表 (后续原生 execute)
            small_alters.append((idx, db, table, stmt))

    # 创建 ghost task (依赖链: 链式设置 depends_on)
    prev_task = None
    for idx, db, table, stmt in tasks_to_create:
        report = run_all_prechecks(workflow.instance, db, table, stmt["full"])
        task = _upsert_task(workflow, stmt, db, table,
                            statement_index=idx, statement_type="ALTER",
                            depends_on=prev_task, passed=report["passed"],
                            report=report, created_by=created_by)
        prev_task = task

    # 存小表 ALTER 到 wf.native_alter_results (启动时 execute)
    if small_alters:
        # 等 start 阶段实际跑 ALTER (status="pending"), 跑完更新 native_alter_results
        ...

    return {"ok": True, "tasks": ..., "small_alters": small_alters, ...}
```

### 4.2 启动阶段 (业务方点"启动")

```python
def start(request, workflow_id):
    task = get_object_or_404(DdlGhostTask, workflow_id=workflow_id)  # 第 1 个 task
    # 检查依赖链: 前一个 task 必须是 success 状态
    if task.depends_on and task.depends_on.status != "success":
        return JsonResponse({"ok": False, "error": f"依赖 task #{task.depends_on.id} 未成功, 不能启动"}, status=409)
    # 启动 gh-ost 子进程
    pid = start_ghost_process(task, instance=...)
    task.status = "running"
    task.started_at = timezone.now()
    task.ghost_pid = pid
    task.save()
    start_poller(task.id)
    # 启动 smart 模式下的小表原生 ALTER (如果存在)
    _execute_small_alters(workflow, task)  # 在 gh-ost task 启动后触发, 串行
    return JsonResponse({"ok": True, "task_id": task.id, "pid": pid})
```

### 4.3 小表原生 ALTER 执行 (`_execute_small_alters`)

```python
def _execute_small_alters(workflow, ghost_task):
    """smart 模式下, 在 ghost task 启动后, 串行执行该 task 后续的原生 ALTER"""
    # 拿 workflow.native_alter_results 里 statement_index > ghost_task.statement_index 的小表
    # 串行用 mysql.execute() 直连数据库
    # 更新 wf.native_alter_results 每个 item 的 status/errormessage/started_at/finished_at
    # 完成后 wf.save()
    # poller._sync_workflow_status 会再检查 wf.status
```

### 4.4 poller 改造

```python
def _sync_workflow_status(task, new_status):
    """poller 统一控制 wf.status (5A 拍板)
    规则:
      - 全部 ghost task 都终态 (success/failed/cancelled/rolled_back)
      - 全部小表原生 ALTER 都完成 (native_alter_results 里每个 status 都是 success/failed)
      才改 wf.status
    """
    # 1. 检查所有 ghost task 都终态
    all_ghost_terminal, total, finished = _all_tasks_terminal(workflow_id)
    if not all_ghost_terminal:
        return  # 还有 ghost task 在跑

    # 2. 检查所有小表原生 ALTER 都完成
    wf = SqlWorkflow.objects.get(pk=task.workflow_id)
    native_results = wf.native_alter_results or []
    all_native_done = all(
        item.get("status") in ("success", "failed") for item in native_results
    )
    if native_results and not all_native_done:
        return  # 还有小表原生 ALTER 在跑

    # 3. 计算 wf.status
    failed_ghost = DdlGhostTask.objects.filter(
        workflow_id=workflow_id, task_type="ghost",
        status__in=("failed", "cancelled", "rolled_back"),
    ).exists()
    failed_native = any(item.get("status") == "failed" for item in native_results)
    target = "workflow_exception" if (failed_ghost or failed_native) else "workflow_finish"

    # 4. 同步 wf.status
    if wf.status in ("workflow_review_pass", "workflow_executing", "workflow_timingtask"):
        wf.status = target
        wf.finish_time = timezone.now()
        wf.save(update_fields=["status", "finish_time"])
```

---

## 5. 前端改造

### 5.1 sqlsubmit.html (工单提交页)

新增 `gh_ost_mode` 下拉框 (勾选 gh-ost 时显示):

```html
{% if show_gh_ost_option %}
<div class="form-group" id="gh-ost-mode-group">
    <label>gh-ost 模式</label>
    <select class="form-control" name="gh_ost_mode" id="gh_ost_mode">
        <option value="smart" selected>智能 (默认: 大表 gh-ost + 小表原生 ALTER)</option>
        <option value="all_ghost">全部 gh-ost (强制所有 ALTER 走 gh-ost)</option>
        <option value="all_native">全部原生 ALTER (强制所有 ALTER 走原生)</option>
    </select>
    <small class="text-muted">smart 模式按表大小自动分流; 阈值: 10w 行 / 100MB</small>
</div>
{% endif %}
```

### 5.2 detail.html (工单详情页)

新增 gh_ost_mode 显示 + 小表原生 ALTER 执行状态:

```html
{% if ghost_tasks %}
<div>
    <h4>gh-ost 模式: <span class="badge">{{ gh_ost_mode_display }}</span></h4>
    <!-- ghost task 列表 (含依赖链 depends_on) -->
    <table>
        <thead><tr><th>序号</th><th>task #</th><th>依赖 task #</th><th>表</th>...</tr></thead>
        <tbody>
            {% for t in ghost_tasks %}
            <tr>
                <td>{{ t.statement_index }}</td>
                <td>#{{ t.id }}</td>
                <td>{% if t.depends_on %}#{{ t.depends_on.id }}{% else %}-{% endif %}</td>
                <td>{{ t.db_name }}.{{ t.table_name }}</td>
                ...
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}

{% if native_alter_results %}
<div>
    <h4>小表原生 ALTER 执行结果</h4>
    <table>
        <thead><tr><th>序号</th><th>表</th><th>ALTER</th><th>状态</th>...</tr></thead>
        <tbody>
            {% for nr in native_alter_results %}
            <tr>
                <td>{{ nr.statement_index }}</td>
                <td>{{ nr.db }}.{{ nr.table }}</td>
                <td><code>{{ nr.alter|truncatechars:80 }}</code></td>
                <td>{{ nr.status }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}
```

---

## 6. 演练 (7 case)

| Case | 输入 | 期望 |
|---|---|---|
| A | smart 模式 1 大表 + 1 小表 | 1 ghost task + 1 small ALTER |
| B | smart 模式 全大表 (2 张) | 2 ghost task, depends_on 链 (statement_index 0/1) |
| C | smart 模式 全小表 (2 张) | 0 ghost task, 2 small ALTER |
| D | all_ghost 模式 1 大 + 1 小 | 2 ghost task, depends_on 链 (强制小表也走 gh-ost) |
| E | all_native 模式 1 大 + 1 小 | 0 ghost task, 2 small ALTER (强制大表也走原生) |
| F | 1 大 + 1 CREATE | smart reject (CREATE 拆单) |
| G | wf#4 like 4 CREATE + 4 ALTER | smart reject (4 CREATE) |

---

## 7. 部署计划

1. 134 dev: 推 6 文件 (models + 2 migration + views + gh-ost views + gh-ost poller + 2 template) + reload master + 演练 7/7 PASS
2. 110 prod: 推 6 文件 + migration + reload master + 演练 7/7 PASS (用真实生产大表演练)
3. 业务方通知: smart 默认行为, 业务方可选 all_ghost/all_native
4. **DBA 一条龙原则**: 演练全在 134 dev 做, 不动生产任何数据和表结构

---

## 8. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| depends_on 链调度失败 (前一个 task 永远不 success) | 低 | 全部 task 卡死 | poller 加 timeout, 30 分钟未成功自动失败 |
| native_alter 执行失败 (小表原生 ALTER 报错) | 中 | wf=workflow_exception, 业务方要重提 | fail-fast, 立即同步 wf.status |
| 串行 vs 并行选择 | 低 | 业务方预期不符 | 默认串行 (依赖链), 文档说明 |

---

## 9. 关联 commit / changelog / 设计稿

- 关联 commit: 待推
- 关联 changelog: docs/changelogs/2026-09-16_v0-gh-ost-smart-mode.md
- 关联事件: DBA-bug-9 (c4ca623) + DBA-bug-9.5 (4b1e415) + wf#4841 业务方实战
- 关联实战接龙: DBA-bug-1..9.5 (9/11-9/16, 16 事件)