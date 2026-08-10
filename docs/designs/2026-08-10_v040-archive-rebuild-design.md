# v0.4.0 归档专题 — 详细设计稿

**版本**: v0.4.0 系列（v0.4.0~v0.4.6）
**作者**: mavis
**日期**: 2026-08-10
**目的**: 把概要设计拆解到可以直接动手写代码的粒度
**粒度约定**: 函数签名 / 类结构 / 字段定义 / 逻辑分支 / 变量 / 异常 / 算法 全列

---

## §0 设计原则

1. **补强优先，新建其次**：v0.4.1~v0.4.3 全部基于现有 `ArchiveConfig` + `ArchiveLog` + `archiver.py`
2. **复用 gh-ost 设施**：v0.4.5 碎片回收走 v0.3.0/v0.4.5-alpha 已建好的 gh-ost runner/parser/poller/notify
3. **安全优先**：触发默认关，DBA 显式开
4. **同表排队**：归档和回收撞车 → 排队等前序完成（FIFO）
5. **审计可读**：ArchiveLog 字段已有，前端可视化 + dashboard

---

## §1 v0.4.0 列压缩（gh-ost 触发 DROP+ADD 合并）

### 1.1 模块位置

```
sql/extensions/ddl_gh_ost/
├── views.py  — precheck/enable/start 端点
└── services/
    ├── parser.py
    └── runner.py
```

### 1.2 算法

**当前问题**：用户在工单页面写 `DROP COLUMN col_a; ADD COLUMN col_b;`（两条 ALTER），gh-ost 跑两次。

**v0.4.0 算法**：
1. 用户在工单页面提交 SQL（含 `DROP` + `ADD` 多个语句）
2. `views.enable()` 解析 SQL，检测 `DROP` + `ADD` 同表同提交
3. 合并为单条 `ALTER TABLE x DROP col_a, ADD col_b`
4. 存到 `DdlGhostTask.alter_statement`（覆盖原始 sql_content）
5. 后续 gh-ost 跑这一条 ALTER → 1 次重建

### 1.3 函数

```python
# views.py 新增
def _merge_drop_add_statements(sql_content: str) -> Tuple[str, bool]:
    """检测 sql_content 里的 DROP+ADD 同表同提交，合并为单条 ALTER。
    
    Returns:
        (merged_sql, was_merged)
    
    算法:
        1. 按 ";" split statements
        2. 按 table 分组
        3. 同表同时含 DROP + ADD → 合并
        4. 保留其他表语句
    
    Examples:
        >>> _merge_drop_add_statements("ALTER TABLE x DROP col_a; ALTER TABLE x ADD col_b INT;")
        ("ALTER TABLE x DROP col_a, ADD col_b INT", True)
    """
    pass
```

### 1.4 异常

- 合并后 SQL 长度 > `MAX_ALTER_LENGTH`（5000）→ 拒绝合并，原样 2 次 gh-ost
- 含非 ALTER 语句（DELETE/UPDATE 等）→ 不合并

---

## §2 v0.4.5 碎片回收（gh-ost 触发空 alter）

### 2.1 数据模型

**`DdlGhostTask` 新增字段**（migration `0002` + `0003`）：

```python
# sql/extensions/ddl_gh_ost/models.py
TASK_TYPE_CHOICES = (
    ("ghost", "gh-ost DDL"),       # 默认（v0.3.0 老数据）
    ("rebuild", "碎片回收"),       # v0.4.5 新增
)

class DdlGhostTask(models.Model):
    # 已有字段省略 ...
    
    ## CUSTOM-MODIFIED: v0.4.5-alpha @ 2026-08-06
    task_type = models.CharField(
        "任务类型", max_length=16, choices=TASK_TYPE_CHOICES,
        default="ghost", db_index=True,
    )
    target_table = models.CharField(
        "目标表", max_length=128, blank=True, db_index=True,
        help_text="rebuild 场景存 db.table",
    )
    related_task_id = models.BigIntegerField(
        "关联 task id", null=True, blank=True,
        help_text="归档联动存 ArchiveConfig.id",
    )
    ## CUSTOM-MODIFIED: 修 queue 漏洞 @ 2026-08-10
    instance = models.ForeignKey(
        "sql.Instance", on_delete=models.PROTECT,
        null=True, blank=True, related_name="ghost_tasks",
    )
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task_type", "workflow"],
                name="uniq_task_type_workflow",
            ),
        ]
```

### 2.2 灰度开关

```python
# archery/settings.py
CUSTOM_GH_OST_REBUILD_ENABLED = env(
    "CUSTOM_GH_OST_REBUILD_ENABLED", default=True,
)
CUSTOM_GH_OST_REBUILD_AUTO_LINK_ARCHIVE = env(
    "CUSTOM_GH_OST_REBUILD_AUTO_LINK_ARCHIVE", default=False,
)
CUSTOM_GH_OST_REBUILD_CRON_ENABLED = env(
    "CUSTOM_GH_OST_REBUILD_CRON_ENABLED", default=False,
)
```

### 2.3 runner.py — gh-ost CLI 构建

```python
# services/runner.py

def build_ghost_command(
    task, instance=None, rebuild_mode: bool = False
) -> List[str]:
    """构建 gh-ost 命令行参数列表。
    
    Args:
        task: DdlGhostTask
        instance: Instance（rebuild 必传）
        rebuild_mode: True=rebuild 场景，alter 改空 COMMENT
    
    Returns:
        list[str] gh-ost argv
    
    Raises:
        ValueError: instance 缺失（rebuild）/ ghost 任务 alter_statement 空
    """
    if rebuild_mode:
        if instance is None:
            raise ValueError("rebuild 模式必须传 instance")
        inst = instance
        alter_arg = _make_rebuild_alter(task)  # "COMMENT 'archery-auto-rebuild-YYYYMMDD'"
    else:
        inst = instance or (task.workflow.instance if task.workflow_id else None)
        if inst is None:
            raise ValueError("no instance available for gh-ost")
        alter = task.alter_statement or ""
        alter_arg = (
            alter if alter.strip().upper().startswith("ALTER")
            else f"ALTER TABLE {alter}"
        )
    
    user, password, (host, port) = _get_creds(inst)
    bin_path = settings.CUSTOM_GH_OST_BIN  # /usr/local/bin/gh-ost
    
    return [
        bin_path,
        f"--host={host}", f"--port={port}",
        f"--user={user}", f"--password={password}",
        f"--database={task.db_name}", f"--table={task.table_name}",
        f"--alter={alter_arg}",                     # 关键参数
        "--assume-rbr", "--allow-on-master", "--execute",
        "--exact-rowcount", "--concurrent-rowcount",
        f"--max-load=Threads_running={task.max_load_threads_running}",
        "--nice-ratio=0", "--cut-over=atomic",
        "--initially-drop-ghost-table", "--initially-drop-old-table",
        "--ok-to-drop-table",
        "--verbose", "--default-retries=120",
    ]


def _make_rebuild_alter(task) -> str:
    """rebuild 场景的 gh-ost --alter 裸子句。
    
    Returns:
        str 形如 "COMMENT 'archery-auto-rebuild-20260810'"
    
    关键规则: gh-ost 期望 --alter 是**裸子句**（不带 ALTER TABLE 前缀）。
    gh-ost 内部拼成 `ALTER TABLE <ghost_table> <alter_subclause>`。
    传完整 SQL 'ALTER TABLE x COMMENT ...' 会拼成双 ALTER → SQL 1064。
    """
    today = timezone.now().strftime("%Y%m%d")
    return f"COMMENT 'archery-auto-rebuild-{today}'"


def start_ghost_process(task, instance=None) -> int:
    """启动 gh-ost 子进程。
    
    Returns:
        gh-ost PID
    
    Raises:
        RuntimeError: 进程秒退（log 写在 /var/log/archery/gh_ost/ghost-{id}.log）
    """
    rebuild_mode = (getattr(task, "task_type", None) == "rebuild")
    log_dir = settings.CUSTOM_GH_OST_LOG_DIR
    log_path = os.path.join(log_dir, f"ghost-{task.id}.log")
    
    cmd = build_ghost_command(task, instance, rebuild_mode=rebuild_mode)
    logger.info("gh-ost start: task_id=%s cmd=%s", task.id, " ".join(shlex.quote(c) for c in cmd))
    
    # 写 log 文件（chown 到 archery 用户）
    # ...
    
    with open(log_path, "ab", buffering=0) as logf:
        proc = subprocess.Popen(
            cmd,
            stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True,  # 等价 nohup
            cwd="/tmp",
        )
    
    if proc.poll() is not None:
        # 进程秒退，抛 RuntimeError
        with open(log_path, "r", errors="replace") as f:
            err_tail = f.read()[-2000:]
        raise RuntimeError(f"gh-ost 进程秒退 (rc={proc.returncode})。log tail: {err_tail}")
    
    return proc.pid
```

### 2.4 rebuild.py — rebuild 场景封装

```python
# services/rebuild.py

def start_rebuild_process(task, instance) -> int:
    """启动 rebuild 场景的 gh-ost 进程（与 ghost 共享 runner.start_ghost_process）。
    
    Args:
        task: DdlGhostTask（task_type=rebuild, workflow=NULL）
        instance: Instance（rebuild 必填，gh-ost 连接凭据源）
    
    Returns:
        gh-ost PID
    
    Raises:
        ValueError: 任务不合法（task_type != rebuild / workflow_id 不为 None / db/table 为空）
        RuntimeError: gh-ost 进程秒退
    """
    _validate_rebuild_task(task)
    if instance is None:
        raise ValueError("rebuild 模式必须传 instance")
    
    logger.info("gh-ost rebuild start: task_id=%s db=%s table=%s", task.id, task.db_name, task.table_name)
    pid = start_ghost_process(task, instance)  # 内部 rebuild_mode=True
    
    # 写 task 字段（poller 启动时 is_alive(pid) 需要 ghost_pid）
    task.ghost_pid = pid
    task.status = "running"
    task.started_at = task.started_at or timezone.now()
    task.current_stage = task.current_stage or "connecting"
    task.progress_pct = 0
    task.progress_message = "rebuild gh-ost 已启动"
    task.last_heartbeat_at = timezone.now()
    task.save()
    return pid


def _validate_rebuild_task(task) -> None:
    """校验 task 是合法 rebuild 任务。
    
    Raises:
        ValueError: 校验失败
    """
    if task.task_type != "rebuild":
        raise ValueError(f"task.task_type={task.task_type!r} 不是 'rebuild'")
    if task.workflow_id is not None:
        raise ValueError(f"rebuild 任务不应挂 workflow（workflow_id={task.workflow_id}）")
    if not task.db_name or not task.table_name:
        raise ValueError(f"rebuild db_name/table_name 必填")
    expected = f"{task.db_name}.{task.table_name}"
    if task.target_table and task.target_table != expected:
        logger.warning("rebuild target_table=%r != %r，按 db_name.table_name 走", task.target_table, expected)
```

### 2.5 queue.py — 同表 FIFO 排队

```python
# services/queue.py

def try_advance_queue(db: str, table: str) -> Optional[DdlGhostTask]:
    """推进同表下一个 waiting 的 rebuild。
    
    Returns:
        启动的 task（None = 队列空 / 有 running 阻塞）
    
    算法:
        1. 查同表 status=queued 的最早 task（FIFO，created_at asc）
        2. 查同表 status=running AND is_alive(pid) 的 task，有则 return None（继续等）
        3. _resolve_instance(task) 拿 instance
        4. start_rebuild_process 启动 gh-ost
        5. 写 ghost_pid / status=running
        6. start_poller(task.id) 后台轮询
    """
    waiting = find_waiting_for(db, table).first()
    if not waiting:
        logger.debug("queue empty for %s.%s", db, table)
        return None
    
    # 检查同表 alive running（避免 stale running 阻塞）
    from .runner import is_alive as _is_alive
    has_alive_running = any(
        t.ghost_pid and _is_alive(t.ghost_pid)
        for t in DdlGhostTask.objects.filter(
            task_type="rebuild", db_name=db, table_name=table,
            status__in=["running", "cut_over"],
        )
    )
    if has_alive_running:
        logger.debug("queue advance skip: %s.%s 有 alive running，task #%s 等", db, table, waiting.id)
        return None
    
    instance = _resolve_instance(waiting)
    if instance is None:
        # queue 推进失败：标 failed
        waiting.status = "failed"
        waiting.error_message = "queue 推进失败：无法解析 instance"
        waiting.finished_at = timezone.now()
        waiting.save()
        return waiting
    
    try:
        pid = start_rebuild_process(waiting, instance)
    except Exception as exc:
        logger.exception("queue advance start_rebuild_process failed: task=%s", waiting.id)
        waiting.status = "failed"
        waiting.error_message = f"queue 推进启动 gh-ost 失败：{exc}"
        waiting.finished_at = timezone.now()
        waiting.save()
        return waiting
    
    # 启动 poller
    from .poller import start_poller
    try:
        start_poller(waiting.id)
    except Exception:
        logger.exception("start_poller failed in queue advance: task=%s", waiting.id)
        waiting.error_message = "poller 启失败 — gh-ost 在跑但没人在轮询"
        waiting.save()
    
    logger.info("queue advance: task_id=%s db=%s table=%s pid=%s", waiting.id, db, table, pid)
    return waiting


def _resolve_instance(task: DdlGhostTask):
    """从 task 推断 instance（按优先级）。"""
    if task.instance_id:
        return task.instance
    if task.related_task_id is not None:
        from sql.models import ArchiveConfig
        try:
            archive = ArchiveConfig.objects.get(id=task.related_task_id)
            return archive.src_instance
        except ArchiveConfig.DoesNotExist:
            return None
    if task.workflow_id:
        return task.workflow.instance
    return None


def get_queue_position(task: DdlGhostTask) -> int:
    """查 task 在同表队列里排第几（1=队头，0=不在队列）。"""
    if task.status != "queued":
        return 0
    earlier = find_waiting_for(task.db_name, task.table_name).filter(
        created_at__lt=task.created_at,
    ).count()
    return earlier + 1
```

### 2.6 poller.py — 终态后自动推进

```python
# services/poller.py
def _finalize_task(task, new_status: str, error_message: str = ""):
    """终态收尾：写状态、停止进程、钉钉通知、推进同表 rebuild 队列。"""
    task.status = new_status
    task.finished_at = timezone.now()
    if error_message:
        task.error_message = (task.error_message or "") + "\n" + error_message
    if task.ghost_pid:
        try:
            os.kill(task.ghost_pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    task.save()
    try:
        notify_terminal(task)
    except Exception:
        logger.exception("notify_terminal failed: task=%s", task.id)
    
    ## CUSTOM-MODIFIED: v0.4.5-alpha 终态后推进同表 rebuild 队列
    if task.task_type == "rebuild":
        from .queue import try_advance_queue
        try:
            try_advance_queue(task.db_name, task.table_name)
        except Exception:
            logger.exception("try_advance_queue failed after task #%s finalize", task.id)
```

### 2.7 views.py — 端点

```python
# views.py

@login_required
@require_GET
def rebuild_list(request: HttpRequest) -> JsonResponse:
    """GET /gh_ost/rebuild/list/?instance_id=N
    列 instance 下可重建的表（InnoDB + DATA_FREE 倒序）。
    
    Returns:
        {ok, instance_id, instance_name, tables: [{db, table, data_free_mb, size_mb, data_free_pct}]}
    """
    instance_id = request.GET.get("instance_id")
    if not instance_id:
        return JsonResponse({"ok": False, "error": "instance_id 必填"}, status=400)
    try:
        instance = Instance.objects.get(pk=int(instance_id))
    except (Instance.DoesNotExist, ValueError):
        return JsonResponse({"ok": False, "error": f"instance #{instance_id} 不存在"}, status=404)
    
    # 走 _get_creds（dev 走 .env 兜底 dbops 凭据）
    try:
        user, password, (host, port) = _get_creds(instance)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"取凭据失败：{exc}", "hint": "dev 134 instance 是历史密文，配置 CUSTOM_GH_OST_PRECHECK_* 兜底"}, status=500)
    
    import pymysql
    try:
        conn = pymysql.connect(host=host, port=port, user=user, password=password, connect_timeout=5, autocommit=True)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"连 MySQL 失败：{exc}", "host": host, "port": port}, status=500)
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT TABLE_SCHEMA, TABLE_NAME, DATA_FREE, DATA_LENGTH, INDEX_LENGTH
                FROM INFORMATION_SCHEMA.TABLES
                WHERE ENGINE = 'InnoDB'
                  AND TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
                  AND TABLE_TYPE = 'BASE TABLE'
                ORDER BY DATA_FREE DESC
                LIMIT 200
            """)
            tables = []
            for schema, name, df, dl, il in cur.fetchall():
                df, dl, il = df or 0, dl or 0, il or 0
                total_mb = (dl + il) / 1024 / 1024
                tables.append({
                    "db": schema, "table": name,
                    "data_free_mb": round(df / 1024 / 1024, 1),
                    "size_mb": round(total_mb, 1),
                    "data_free_pct": round(df / (dl + 1) * 100, 1),
                })
    finally:
        conn.close()
    
    return JsonResponse({
        "ok": True,
        "instance_id": instance.id,
        "instance_name": instance.instance_name,
        "tables": tables,
    })


@login_required
@require_POST
def rebuild_start(request: HttpRequest) -> JsonResponse:
    """POST /gh_ost/rebuild/start/
    DBA 选表触发 rebuild task。
    
    Body: {instance_id, db, table}（JSON 或 form）
    
    Returns:
        {ok, task_id, status, pid, target_table} 或 {queue_position, msg}
    """
    # 1. 灰度开关
    if not getattr(settings, "CUSTOM_GH_OST_REBUILD_ENABLED", True):
        return JsonResponse({"ok": False, "error": "rebuild 功能未启用"}, status=403)
    
    # 2. 入参（JSON 或 form）
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "JSON body 解析失败"}, status=400)
        instance_id = payload.get("instance_id")
        db = payload.get("db")
        table = payload.get("table")
    else:
        instance_id = request.POST.get("instance_id")
        db = request.POST.get("db")
        table = request.POST.get("table")
    
    if not all([instance_id, db, table]):
        return JsonResponse({"ok": False, "error": "instance_id / db / table 必填"}, status=400)
    try:
        instance = Instance.objects.get(pk=int(instance_id))
    except (Instance.DoesNotExist, ValueError):
        return JsonResponse({"ok": False, "error": f"instance #{instance_id} 不存在"}, status=404)
    
    # 3. 写 task
    task = DdlGhostTask.objects.create(
        workflow=None, task_type="rebuild",
        db_name=db, table_name=table,
        target_table=f"{db}.{table}",
        instance=instance,
        enabled=True, status="queued",
        created_by=request.user.username,
        max_load_threads_running=30, timeout_seconds=7200,
    )
    
    # 4. 推进队列
    from .services.queue import get_queue_position, try_advance_queue
    pos_before = get_queue_position(task)
    advanced = try_advance_queue(db, table)
    task.refresh_from_db()
    
    if advanced is None:
        return JsonResponse({"ok": False, "error": "queue 推进异常，请联系 DBA"}, status=500)
    if task.id != advanced.id:
        return JsonResponse({
            "ok": True, "task_id": task.id, "status": task.status,
            "queue_position": pos_before, "target_table": task.target_table,
            "advanced_task_id": advanced.id,
            "msg": f"已入队，前面 task #{advanced.id} 在执行",
        })
    return JsonResponse({
        "ok": True, "task_id": task.id, "status": task.status,
        "pid": task.ghost_pid, "target_table": task.target_table,
    })


@login_required
@require_GET
def rebuild_progress_page(request: HttpRequest, task_id: int) -> HttpResponse:
    """GET /gh_ost/rebuild/progress/<task_id>/"""
    task = get_object_or_404(DdlGhostTask, pk=task_id, task_type="rebuild")
    return render(request, "ddl_gh_ost/progress_rebuild.html", {"task": task})


@login_required
@require_GET
def rebuild_status(request: HttpRequest, task_id: int) -> JsonResponse:
    """GET /gh_ost/rebuild/status/<task_id>/"""
    task = DdlGhostTask.objects.filter(pk=task_id, task_type="rebuild").first()
    if not task:
        return JsonResponse({"ok": False, "error": "rebuild task 不存在"}, status=404)
    return JsonResponse({
        "ok": True, "task_id": task.id, "task_type": task.task_type,
        "target_table": task.target_table, "status": task.status,
        "current_stage": task.current_stage,
        "progress": {
            "pct": task.progress_pct, "rows_copied": task.progress_rows_copied,
            "rows_total": task.progress_rows_total, "speed": task.progress_speed_rows_per_sec,
            "eta_seconds": task.progress_eta_seconds,
            "threads_running": task.progress_threads_running,
            "message": task.progress_message,
        },
        "last_heartbeat_at": task.last_heartbeat_at.isoformat() if task.last_heartbeat_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "duration_seconds": task.duration_seconds,
        "stderr_tail": task.stderr_tail[-2000:],
        "error_message": task.error_message,
    })
```

### 2.8 admin.py — 列表/筛选/action

```python
# admin.py
@admin.register(DdlGhostTask)
class DdlGhostTaskAdmin(admin.ModelAdmin):
    list_display = (
        "id", "task_type_badge", "source_link",
        "status_badge", "current_stage", "progress_bar",
        "enabled", "cut_over_strategy", "precheck_passed",
        "started_at", "finished_at", "created_at",
    )
    list_filter = (
        "task_type", "status", "enabled", "cut_over_strategy", "precheck_passed",
    )
    search_fields = (
        "workflow__workflow_name", "workflow__id",
        "audit__audit_id", "table_name", "db_name", "target_table",
    )
    readonly_fields = (
        "task_type", "target_table", "related_task_id",
        # ... 已有 readonly
    )
    actions = ["admin_cancel", "admin_retry", "admin_rollback", "admin_batch_rebuild"]
    
    def task_type_badge(self, obj):
        color = {"ghost": "#409EFF", "rebuild": "#67C23A"}.get(obj.task_type, "#909399")
        label = {"ghost": "gh-ost DDL", "rebuild": "碎片回收"}.get(obj.task_type, obj.task_type)
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">{}</span>',
            color, label,
        )
    
    def source_link(self, obj):
        if obj.task_type == "rebuild":
            target = obj.target_table or f"{obj.db_name}.{obj.table_name}"
            return format_html('<span style="color:#67C23A;">📊 {}</span>', target)
        if obj.workflow_id:
            url = f"/admin/sql/sqlworkflow/{obj.workflow_id}/change/"
            return format_html('<a href="{}">工单 #{} {}</a>', url, obj.workflow_id, obj.workflow.workflow_name or "")
        return format_html('<span style="color:#909399;">—</span>')
```

### 2.9 templates — progress_rebuild.html

从 `progress.html` fork：

- title: `碎片回收进度 · {db.table} [v0.4.5]`
- sub 段: `目标表 {db.table} · 发起人 {created_by} · 任务 #{id}`
- 去掉"启动 gh-ost"按钮（rebuild 走端点触发，不走 admin 手动）
- JS 端点: `/gh_ost/rebuild/status/<task_id>/`（不是 workflow_id）
- 3s polling 同 ghost
- 终态时禁用"取消回收"按钮

### 2.10 urls.py

```python
urlpatterns = [
    # 已有 8 个 ...
    path("rebuild/list/", views.rebuild_list, name="rebuild_list"),
    path("rebuild/start/", views.rebuild_start, name="rebuild_start"),
    path("rebuild/status/<int:task_id>/", views.rebuild_status, name="rebuild_status"),
    path("rebuild/progress/<int:task_id>/", views.rebuild_progress_page, name="rebuild_progress"),
]
```

### 2.11 异常处理表

| 异常 | 触发条件 | 处理 |
|------|----------|------|
| `ValueError("rebuild 模式必须传 instance")` | rebuild 任务没传 instance | 写 task.status="failed" + error_message |
| `ValueError("task.task_type != 'rebuild'")` | _validate_rebuild_task | 抛 ValueError（不静默） |
| `ValueError("rebuild 任务不应挂 workflow")` | rebuild 任务 workflow_id 非空 | 抛 ValueError |
| `RuntimeError("gh-ost 进程秒退")` | gh-ost 启动后秒退（exit code 非 0） | 抛 RuntimeError，task.failed |
| `OperationalError`（MySQL 连不上） | pymysql connect 失败 | 500 + 提示 .env 兜底 |
| poller 异常 | 任何未捕获异常 | 外层 try/except 写 error_message + status=failed |

---

## §3 v0.4.1 现有归档补强

### 3.1 数据模型

**`ArchiveConfig` 新增字段**（migration `0004`）：

```python
# sql/models.py
class ArchiveConfig(models.Model, WorkflowAuditMixin):
    # 已有字段省略 ...
    
    ## CUSTOM-MODIFIED: v0.4.1 @ 2026-08-10
    last_archive_status = models.CharField(
        "上次归档状态", max_length=16, blank=True, default="",
        choices=(("success", "成功"), ("failed", "失败"), ("running", "执行中"), ("", "未执行")),
    )
    last_archive_rows_archived = models.BigIntegerField(
        "上次归档行数", null=True, blank=True,
    )
    last_archive_duration_seconds = models.IntegerField(
        "上次归档耗时（秒）", null=True, blank=True,
    )
    last_archive_task_id = models.BigIntegerField(
        "上次归档关联 task id（rebuild 联动用）", null=True, blank=True,
    )
```

### 3.2 archiver.py — 写新字段 + 钉钉通知

```python
# sql/archiver.py
def archive(archive_id: int) -> None:
    """执行数据库归档（增强版：写 last_archive_* 字段 + 钉钉通知 + 触发 rebuild 联动）。"""
    archive_info = ArchiveConfig.objects.get(id=archive_id)
    
    # ... 已有 pt-archiver 执行逻辑 ...
    
    # 末尾：写 last_archive_* 字段
    with transaction.atomic():
        ArchiveConfig.objects.filter(id=archive_id).update(
            last_archive_status="success" if success else "failed",
            last_archive_rows_archived=delete_cnt,
            last_archive_duration_seconds=int((t.end - t.start).total_seconds()),
        )
    
    # 钉钉通知（best-effort）
    try:
        notify_archive_terminal(archive_info, success, error_info, select_cnt, insert_cnt, delete_cnt)
    except Exception:
        logger.exception("notify_archive_terminal failed: archive=%s", archive_id)
    
    # v0.4.2 联动（auto_rebuild_after_archive=True 时触发 rebuild）
    from sql.extensions.ddl_gh_ost.services.queue import trigger_rebuild_after_archive
    try:
        rebuild_task = trigger_rebuild_after_archive(archive_id)
        if rebuild_task:
            ArchiveConfig.objects.filter(id=archive_id).update(
                last_archive_task_id=rebuild_task.id,
            )
    except Exception:
        logger.exception("trigger_rebuild_after_archive failed: archive=%s", archive_id)
    
    if not success:
        raise Exception(f"{error_info}\n{statistics}")


def notify_archive_terminal(archive_info, success: bool, error_info: str, select_cnt: int, insert_cnt: int, delete_cnt: int) -> None:
    """归档完成钉钉通知（best-effort，参考 gh-ost notify.py 模式）。"""
    webhook = getattr(settings, "DINGTALK_NOTIFY_WEBHOOK", "")
    if not webhook:
        logger.debug("DINGTALK_NOTIFY_WEBHOOK 未配置，skip 钉钉通知")
        return
    
    status = "✅ 成功" if success else "❌ 失败"
    msg = f"""## 归档完成 {status}
- 配置: {archive_info.title}
- 实例: {archive_info.src_instance.instance_name}
- 表: `{archive_info.src_db_name}.{archive_info.src_table_name}`
- 模式: {archive_info.get_mode_display()}
- 查询: {select_cnt:,}  ·  写入: {insert_cnt:,}  ·  删除: {delete_cnt:,}
- 发起人: {archive_info.user_display}
"""
    if error_info:
        msg += f"- 错误: {error_info[:500]}\n"
    
    payload = {"msgtype": "markdown", "markdown": {"title": "归档完成", "text": msg}}
    try:
        requests.post(webhook, json=payload, timeout=5)
    except Exception as exc:
        logger.warning("dingtalk notify failed: %s", exc)
```

### 3.3 admin.py — ArchiveConfig 详情页

```python
# sql/admin.py
@admin.register(ArchiveConfig)
class ArchiveConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id", "title", "src_instance", "src_db_name", "src_table_name",
        "mode", "state", "last_archive_status", "last_archive_rows_archived",
        "last_archive_duration_seconds", "user_display", "create_time",
    )
    list_filter = ("state", "mode", "last_archive_status", "resource_group")
    readonly_fields = (
        "last_archive_status", "last_archive_rows_archived",
        "last_archive_duration_seconds", "last_archive_task_id",
        "last_archive_time", "create_time", "sys_time",
    )
```

### 3.4 异常处理表

| 异常 | 触发条件 | 处理 |
|------|----------|------|
| `requests.RequestException` | 钉钉 webhook 调用失败 | logger.warning（best-effort） |
| `ArchiveConfig.DoesNotExist` | archive_id 不存在 | raise（保留原行为） |
| `Exception`（归档失败） | pt-archiver returncode != 0 | raise，error_message 落 ArchiveLog |

---

## §4 v0.4.2 归档→重建联动

### 4.1 数据模型

**`ArchiveConfig` 新增字段**（migration `0004`，同 v0.4.1 一起）：

```python
## CUSTOM-MODIFIED: v0.4.2 @ 2026-08-10
auto_rebuild_after_archive = models.BooleanField(
    "归档完成后自动重建（碎片回收）", default=False,
    help_text="勾选后归档完成时自动触发 gh-ost 触发空 alter 重建同表",
)
```

### 4.2 触发器

`archiver.py` 的 `archive()` 函数末尾调 `trigger_rebuild_after_archive(archive_id)`（见 §3.2）。

### 4.3 queue.py — 触发函数

```python
# services/queue.py
def trigger_rebuild_after_archive(archive_id: int) -> Optional[DdlGhostTask]:
    """归档完成钩子 —— 自动触发 src 表的 rebuild（v0.4.2 联动）。
    
    触发条件（按顺序校验）：
        1. CUSTOM_GH_OST_REBUILD_AUTO_LINK_ARCHIVE=True（灰度开关）
        2. ArchiveConfig.auto_rebuild_after_archive=True（每条配置独立勾选）
        3. 同表无 running/queued/cut_over 任务
    
    行为:
        1. 写新 DdlGhostTask
           task_type=rebuild
           workflow=NULL
           related_task_id=archive.id
           instance=archive.src_instance
           created_by="archive-{archive.user_name}"
        2. try_advance_queue(src_db, src_table) 立即推进
    
    Returns:
        新建 / 推进的 rebuild task（None = 不需要触发）
    """
    if not settings.CUSTOM_GH_OST_REBUILD_AUTO_LINK_ARCHIVE:
        return None
    
    archive = ArchiveConfig.objects.get(id=archive_id)
    if not archive.auto_rebuild_after_archive:
        return None
    
    existing = DdlGhostTask.objects.filter(
        task_type="rebuild",
        db_name=archive.src_db_name, table_name=archive.src_table_name,
        status__in=["queued", "running", "cut_over"],
    ).first()
    if existing:
        return existing
    
    task = DdlGhostTask.objects.create(
        workflow=None, task_type="rebuild",
        db_name=archive.src_db_name, table_name=archive.src_table_name,
        target_table=f"{archive.src_db_name}.{archive.src_table_name}",
        instance=archive.src_instance, related_task_id=archive.id,
        enabled=True, status="queued",
        created_by=f"archive-{archive.user_name}",
        max_load_threads_running=30, timeout_seconds=7200,
    )
    return try_advance_queue(archive.src_db_name, archive.src_table_name)
```

### 4.4 异常处理表

| 异常 | 触发条件 | 处理 |
|------|----------|------|
| `ArchiveConfig.DoesNotExist` | archive_id 不存在 | logger.warning，return None |
| `Exception` | trigger 内部任何异常 | logger.exception，不影响归档本身 |

---

## §5 v0.4.3 归档审计页

### 5.1 数据模型

**不新增字段**。`ArchiveLog` 已有：
- `select_cnt / insert_cnt / delete_cnt / start_time / end_time / success / error_info / statistics`

直接 SELECT 渲染，前端算 ratio。

### 5.2 URL + View

```python
# sql/urls.py
path("archive/audit/<int:archive_id>/", views.archive_audit, name="archive_audit"),

# sql/views.py
@login_required
def archive_audit(request, archive_id: int):
    """归档审计详情页：进度 + 历史日志 + 比率可视化。"""
    archive = get_object_or_404(ArchiveConfig, pk=archive_id)
    logs = ArchiveLog.objects.filter(archive=archive).order_by("-id")[:50]
    return render(request, "sqlarchive_audit.html", {
        "archive": archive,
        "logs": logs,
    })
```

### 5.3 模板 — sqlarchive_audit.html

```html
{% extends "base.html" %}
{% block content %}
<h1>归档审计 · {{ archive.title }}</h1>
<div class="card">
  <h3>基本信息</h3>
  <p>实例 {{ archive.src_instance }} · 库 {{ archive.src_db_name }} · 表 {{ archive.src_table_name }}</p>
  <p>模式 {{ archive.get_mode_display }} · 条件 {{ archive.condition }}</p>
  <p>上次归档:
    {% if archive.last_archive_status == "success" %}
      <span class="badge good">✓ 成功</span>
    {% elif archive.last_archive_status == "failed" %}
      <span class="badge danger">✗ 失败</span>
    {% endif %}
    {{ archive.last_archive_rows_archived }} 行 · {{ archive.last_archive_duration_seconds }}s
  </p>
  {% if archive.last_archive_task_id %}
    <p>关联 rebuild task: <a href="/gh_ost/rebuild/progress/{{ archive.last_archive_task_id }}/">#{{ archive.last_archive_task_id }}</a></p>
  {% endif %}
</div>

<div class="card">
  <h3>历史日志（近 50 次）</h3>
  <table>
    <thead>
      <tr><th>时间</th><th>查询</th><th>写入</th><th>删除</th><th>耗时</th><th>状态</th></tr>
    </thead>
    <tbody>
      {% for log in logs %}
      <tr>
        <td>{{ log.start_time|date:"Y-m-d H:i" }} → {{ log.end_time|date:"H:i" }}</td>
        <td>{{ log.select_cnt }}</td>
        <td>{{ log.insert_cnt }}</td>
        <td>{{ log.delete_cnt }}</td>
        <td>{{ log.end_time|timeuntil:log.start_time }}</td>
        <td>
          {% if log.success %}<span class="badge good">✓</span>
          {% else %}<span class="badge danger">✗</span>{% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<div class="card">
  <h3>详情日志</h3>
  {% for log in logs %}
  <details>
    <summary>#{{ log.id }} · {{ log.start_time }}</summary>
    <pre>{{ log.statistics }}</pre>
    {% if log.error_info %}<pre class="error">{{ log.error_info }}</pre>{% endif %}
  </details>
  {% endfor %}
</div>
{% endblock %}
```

### 5.4 dashboard

```python
# sql/views.py
@login_required
def archive_dashboard(request):
    """归档 dashboard：周统计 + 失败 Top 5。"""
    from datetime import timedelta
    now = timezone.now()
    week_ago = now - timedelta(days=7)
    
    archives_this_week = ArchiveLog.objects.filter(start_time__gte=week_ago)
    total = archives_this_week.count()
    success = archives_this_week.filter(success=True).count()
    total_rows = archives_this_week.aggregate(s=Sum("delete_cnt"))["s"] or 0
    
    # 按天统计
    by_day = archives_this_week.extra(select={"day": "DATE(start_time)"}).values("day").annotate(c=Count("id"), r=Sum("delete_cnt"))
    
    # 失败 Top 5
    failed_top = ArchiveLog.objects.filter(success=False, start_time__gte=week_ago).values("archive__src_db_name", "archive__src_table_name").annotate(c=Count("id")).order_by("-c")[:5]
    
    return render(request, "archive_dashboard.html", {
        "total": total, "success_rate": success / total if total else 0,
        "total_rows": total_rows, "by_day": list(by_day), "failed_top": list(failed_top),
    })
```

### 5.5 异常处理表

| 异常 | 触发条件 | 处理 |
|------|----------|------|
| `ArchiveConfig.DoesNotExist` | archive_id 不存在 | 404 |
| `ArchiveLog.DoesNotExist` | 日志不存在 | 渲染空列表（不报错） |

---

## §6 v0.4.6 cron 自动调度

### 6.1 灰度开关

`CUSTOM_GH_OST_REBUILD_CRON_ENABLED = env(..., default=False)`

### 6.2 django-q 调度

```python
# sql/management/commands/cron_rebuild_scan.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from django.db.models import F, ExpressionWrapper, BigIntegerField
from django.db.models.functions import Coalesce

class Command(BaseCommand):
    help = "每周日凌晨 3 点扫描大表碎片率 > 30% 触发 rebuild"
    
    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--threshold-pct", type=int, default=30, help="DATA_FREE 占比阈值")
        parser.add_argument("--size-mb-min", type=int, default=1024, help="最小表 MB")
    
    def handle(self, *args, **options):
        if not settings.CUSTOM_GH_OST_REBUILD_CRON_ENABLED:
            self.stdout.write("CUSTOM_GH_OST_REBUILD_CRON_ENABLED=False, skip")
            return
        
        threshold = options["threshold_pct"]
        size_min = options["size_mb_min"]
        
        # 查所有 instance 的 INFORMATION_SCHEMA
        from sql.models import Instance
        for instance in Instance.objects.filter(type="master"):
            try:
                tables = self._scan_instance(instance, threshold, size_min)
            except Exception as exc:
                self.stderr.write(f"instance {instance.id} 扫描失败: {exc}")
                continue
            
            for t in tables:
                self.stdout.write(f"  触发 rebuild: {t['db']}.{t['table']} (data_free_pct={t['pct']}%)")
                if options["dry_run"]:
                    continue
                from sql.extensions.ddl_gh_ost.services.queue import trigger_rebuild_after_archive
                # ... 触发 rebuild task（类似 trigger_rebuild_after_archive 但无 archive_id）
    
    def _scan_instance(self, instance, threshold, size_min):
        from sql.extensions.ddl_gh_ost.services.db import _get_creds
        import pymysql
        user, password, (host, port) = _get_creds(instance)
        conn = pymysql.connect(host=host, port=port, user=user, password=password, connect_timeout=10, autocommit=True)
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT TABLE_SCHEMA, TABLE_NAME, DATA_FREE, DATA_LENGTH, INDEX_LENGTH
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE ENGINE = 'InnoDB'
                      AND TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
                      AND TABLE_TYPE = 'BASE TABLE'
                      AND (DATA_LENGTH + INDEX_LENGTH) > %s * 1024 * 1024
                      AND DATA_FREE > (DATA_LENGTH + INDEX_LENGTH) * %s / 100.0
                """, (size_min, threshold))
                results = []
                for schema, name, df, dl, il in cur.fetchall():
                    df, dl, il = df or 0, dl or 0, il or 0
                    pct = df / (dl + il + 1) * 100
                    results.append({"db": schema, "table": name, "pct": round(pct, 1)})
                return results
        finally:
            conn.close()
```

### 6.3 django-q Schedule

```python
# sql/management/commands/setup_cron_tasks.py
from django_q.models import Schedule

def setup():
    Schedule.objects.update_or_create(
        name="cron_rebuild_scan",
        defaults={
            "func": "sql.management.commands.cron_rebuild_scan.Command.handle",
            "schedule_type": Schedule.WEEKLY,
            "repeats": -1,  # forever
            "next_run": next_sunday_3am(),
        },
    )
```

### 6.4 异常处理表

| 异常 | 触发条件 | 处理 |
|------|----------|------|
| `Instance.DoesNotExist` | 跳过该 instance | continue |
| `pymysql.OperationalError` | 连不上 instance | logger.warning，continue |
| `Exception`（建 task 失败） | trigger_rebuild 内部 | logger.exception，继续扫描下一个 |

---

## §7 实施顺序（开发前规划）

| 步骤 | 内容 | 涉及文件 |
|------|------|----------|
| 1 | v0.4.0 列压缩（已存在） | `views.py` `_merge_drop_add_statements` |
| 2 | v0.4.5 model + migration 0002 | `models.py` |
| 3 | v0.4.5 rebuild.py | `services/rebuild.py` |
| 4 | v0.4.5 queue.py | `services/queue.py` |
| 5 | v0.4.5 runner 加 rebuild_mode | `services/runner.py` |
| 6 | v0.4.5 views rebuild_list/start | `views.py` |
| 7 | v0.4.5 admin task_type 筛选 | `admin.py` |
| 8 | v0.4.5 progress_rebuild.html | `templates/` |
| 9 | v0.4.5 migration 0003 instance 字段 | `models.py` + `migrations/0003` |
| 10 | v0.4.5 134 dev 演练 | tarball sync + 端到端 |
| 11 | v0.4.1 migration 0004 + archiver notify + admin readonly | `models.py` + `archiver.py` + `admin.py` |
| 12 | v0.4.2 trigger_rebuild_after_archive + archiver 接入 | `queue.py` + `archiver.py` |
| 13 | v0.4.3 archive_audit view + template + dashboard | `views.py` + `urls.py` + `templates/` |
| 14 | v0.4.6 cron_rebuild_scan + django-q Schedule | `management/commands/` + `setup_cron_tasks.py` |

---

## §8 验证清单（开发后用）

### v0.4.5 单元测试

- [ ] `build_ghost_command(task, instance, rebuild_mode=True)` 返回的 `--alter` 不含 `ALTER TABLE` 前缀
- [ ] `start_rebuild_process(task, instance=None)` 抛 `ValueError`
- [ ] `_validate_rebuild_task(task)` 校验 `task_type` / `workflow_id` / `db_name` / `table_name`
- [ ] `try_advance_queue(db, table)` 同表有 alive running 时返回 None
- [ ] `try_advance_queue(db, table)` 同表有 stale running 时跳过 stale
- [ ] `get_queue_position(task)` 返回 0/1/2/3...

### v0.4.5 集成测试

- [ ] `rebuild_start` 走 JSON body
- [ ] `rebuild_start` 走 form-encoded
- [ ] `rebuild_start` 同表冲突时排队（不 409）
- [ ] `rebuild_list` 倒序返回 DATA_FREE
- [ ] `rebuild_status` 字段一致

### v0.4.5 演练

- [ ] 134 dev 单 task 跑通
- [ ] 134 dev 3 task FIFO 串行成功
- [ ] 影子表清理（_gho/_del/_ghc/_ghk）

### v0.4.1 / v0.4.2 演练

- [ ] ArchiveConfig 勾 auto_rebuild_after_archive → 归档完成 → rebuild 自动起
- [ ] ArchiveConfig 不勾 → 归档完成 → 无 rebuild
- [ ] 归档完成 → 钉钉群收到通知

### v0.4.3 演练

- [ ] archive_audit 页显示进度 + 历史 + 详情
- [ ] archive_dashboard 显示周统计

### v0.4.6 演练

- [ ] cron_rebuild_scan --dry-run 不触发
- [ ] cron_rebuild_scan 真跑触发 rebuild task
- [ ] django-q Schedule 下周日 3 点自动跑

---

## §9 异常处理总表

| 模块 | 异常 | 处理 |
|------|------|------|
| `build_ghost_command` | `ValueError("no instance available for gh-ost")` | 抛 ValueError |
| `build_ghost_command` (rebuild) | `ValueError("rebuild 模式必须传 instance")` | 抛 ValueError |
| `start_ghost_process` | `RuntimeError("gh-ost 进程秒退")` | 抛 RuntimeError，task.failed |
| `start_rebuild_process` | `ValueError`（_validate） | 抛 ValueError |
| `try_advance_queue` | MySQL OperationalError | logger.exception，task.failed |
| `rebuild_start` | `CUSTOM_GH_OST_REBUILD_ENABLED=False` | 403 + 提示 |
| `rebuild_list` | `_get_creds` 失败 | 500 + .env 兜底提示 |
| `trigger_rebuild_after_archive` | `ArchiveConfig.DoesNotExist` | logger.warning，return None |
| `archive()` | pt-archiver 失败 | 写 ArchiveLog + raise，error_message 落库 |
| `notify_archive_terminal` | `requests.RequestException` | logger.warning（best-effort） |
| `cron_rebuild_scan` | `Instance` 扫描失败 | logger.warning，continue 下一个 instance |

---

## §10 灰度开关汇总

| 变量 | 默认 | 控制功能 | 设计稿 |
|------|------|----------|--------|
| `CUSTOM_GH_OST_ENABLED` | False | gh-ost 整个模块 | v0.3.0 §2 |
| `CUSTOM_GH_OST_REBUILD_ENABLED` | True | DBA 手动 + 一键批量 rebuild | §2.2 |
| `CUSTOM_GH_OST_REBUILD_AUTO_LINK_ARCHIVE` | False | 归档完成后自动 rebuild | §2.2 |
| `CUSTOM_GH_OST_REBUILD_CRON_ENABLED` | False | cron 自动扫描触发 | §6.1 |
| `CUSTOM_DINGTALK_NOTIFY_ENABLED` | False | 钉钉通知 | §3.2 |
| `CUSTOM_GH_OST_LOG_DIR` | `/var/log/archery/gh_ost` | gh-ost 日志路径 | §2.3 |
| `CUSTOM_GH_OST_BIN` | `/usr/local/bin/gh-ost` | gh-ost 二进制路径 | §2.3 |
| `CUSTOM_GH_OST_PRECHECK_*` | 空 | dev 134 凭据兜底 | §2.7 |
