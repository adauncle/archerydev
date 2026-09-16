# DBA-bug-9 设计稿:gh-ost 多 statement 工单支持

> **状态**: 设计稿 v1.0
> **作者**: mavis
> **拍板**: 阿达叔叔 2026-09-16 17:42 (D 方案)
> **关联事件**: wf#4841 (业务方实战,多表 DDL + CREATE TABLE 工单,gh-ost 只处理了第一张表,其他 SQL 丢失)

---

## 一句话总结

**把 `_parse_first_alter` 改成 `_parse_all_statements`,每个 ALTER TABLE 都建一个独立 DdlGhostTask。poller 改成"全部 task 终态才改工单状态",工单详情页显示多 task 列表。CREATE/INSERT/UPDATE/DELETE 拒绝启用 gh-ost,要求业务方拆单。**

---

## 1. 背景 (wf#4841 实战事故)

业务方 9/16 17:00+ 提工单 **wf#4841**,内容 3 条 SQL:

```sql
USE `hly_accesscard`;
ALTER TABLE `vehicle_risk_hit` ADD COLUMN `xxx` varchar(150) DEFAULT NULL COMMENT '...';
CREATE TABLE `vehicle_risk_hit_detail` (
  `hit_id` bigint NOT NULL AUTO_INCREMENT,
  ...
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT '车辆业务风险命中记录明细 (明细表)';
```

业务方勾选"启用 gh-ost" → 审批通过 → 详情页 lazy auto-enable 创建 `DdlGhostTask #26` (只解析第一条 ALTER) → 业务方点"启动 gh-ost" → gh-ost 切流 vehicle_risk_hit 481463/481463 行成功 → poller 同步工单状态为 `workflow_finish`。

**结果**:
- ✅ `vehicle_risk_hit` ADD COLUMN 执行成功
- ❌ `vehicle_risk_hit_detail` CREATE TABLE 没执行
- ❌ 工单状态显示"已正常结束"
- ❌ 业务方以为全部成功 → **生产表缺失风险**

---

## 2. 现状分析 (根因)

### 2.1 代码缺陷 3 处

| 文件 | 行 | 缺陷 |
|---|---|---|
| `views.py:_parse_first_alter` | 79-108 | `sql_content.split(";")` 后只取第一条 ALTER;后置的语句完全忽略 |
| `precheck.py:check_alter_sql` | 222-242 | `sqlparse.split(sql_content)` 后只检第一条;不警告工单含多表/CREATE |
| `runner.py:build_ghost_command` | 84-117 | 单 gh-ost 进程只 `--table=单表` `--alter=单条`;CREATE TABLE / 多表无机制执行 |

### 2.2 工单状态联动缺陷 1 处

| 文件 | 行 | 缺陷 |
|---|---|---|
| `poller.py:_sync_workflow_status` | 168-211 | gh-ost task success → 立即把 wf.status 改为 `workflow_finish`;**完全绕过 `execute_sql.execute` 路径**,非 gh-ost 处理的 SQL (CREATE/INSERT/UPDATE/DELETE) 全部丢失 |

### 2.3 wf#4841 完整链路图

```
提工单 wf#4841 (3 条 SQL + 勾选 gh-ost)
  ↓
审批通过 (workflow_review_pass)
  ↓
详情页渲染 lazy auto-enable
  → _enable_ghost_for_workflow
  → _parse_first_alter 只解 ALTER vehicle_risk_hit
  → 创建 DdlGhostTask #26 (status=queued)
  ↓
业务方点 "启动 gh-ost" → /gh_ost/start/<wf#4841>/
  → start_ghost_process → Popen gh-ost --table=vehicle_risk_hit --alter="ADD COLUMN ..."
  → cut-over 成功 481463/481463
  ↓
poller 解析 log "Cut-over complete"
  → _sync_workflow_status
  → _WORKFLOW_STATUS_MAP["success"] = "workflow_finish"
  → wf.status = workflow_finish ✓ (但其他 SQL 没跑!)
  ↓
❌ GoInception.execute_workflow 0 次调用
❌ CREATE TABLE vehicle_risk_hit_detail 丢失
❌ 业务方看到工单 "已正常结束" 误以为全部成功
```

---

## 3. D 方案设计

### 3.1 核心原则

1. **业务方拆 CREATE 是合理约束**:CREATE TABLE 本来就是单独事务,跟 ALTER 一起提交会出问题 (gh-ost ALTER 中途失败回滚,CREATE 已执行 → 一半成功一半失败)。**CREATE 拆成单独工单,反而更安全**
2. **多 ALTER 走多 gh-ost task**:用户核心诉求"全部 SQL 都要执行"满足
3. **不动 execute_sql 主链路**:只用 poller 触发,风险小
4. **不影响上游 Archery**:改动都在 `sql/extensions/ddl_gh_ost/` extension 内

### 3.2 数据模型改造

#### 3.2.1 `DdlGhostTask` 新增字段

```python
## CUSTOM-MODIFIED: DBA-bug-9 加 statement_index 字段 @ 2026-09-16 @ mavis
## 关联: docs/changelogs/2026-09-16_dba-bug-9-ghost-multi-statement.md
## 业务: 一个工单含多条 ALTER TABLE, 每个 ALTER 一个 task,
##       statement_index 标识"工单 SQL 列表的第几条" (从 0 开始)
statement_index = models.IntegerField(
    "SQL 序号 (工单内的第几条)", default=0,
    help_text="工单 SQL 列表的第几条 (从 0 开始);0 = 第一条",
)
statement_type = models.CharField(
    "DDL 类型", max_length=16, blank=True, default="ALTER",
    help_text="DDL 类型: ALTER / CREATE / INSERT / UPDATE / DELETE / USE",
)
```

#### 3.2.2 去掉 unique_together

```python
## 旧:
constraints = [
    models.UniqueConstraint(fields=["task_type", "workflow"], name="uniq_task_type_workflow"),
]

## 新 (DBA-bug-9):
constraints = [
    ## 同 task_type + 同 workflow + 同 statement_index 唯一
    ## 一个工单同序号只能有一个 task (避免重复创建)
    models.UniqueConstraint(
        fields=["task_type", "workflow", "statement_index"],
        name="uniq_task_type_workflow_stmt",
    ),
]
```

### 3.3 解析层改造

#### 3.3.1 `_parse_first_alter` → `_parse_all_statements`

```python
def _parse_all_statements(sql_content: str) -> List[dict]:
    """提取 SQL 文本里的所有 statement,按 ; 切 + 去注释 + 去空行。

    Returns:
        list of {"stmt_type": "ALTER"|"CREATE"|"INSERT"|"UPDATE"|"DELETE"|"USE"|"OTHER",
                 "db": str|None, "table": str|None, "full": str}
    """
    statements = [s.strip() for s in sql_content.split(";") if s.strip()]
    result = []
    for stmt in statements:
        # 去掉前导注释
        lines = []
        for line in stmt.splitlines():
            stripped = line.strip()
            if stripped.startswith("--") or not stripped:
                continue
            lines.append(line)
        cleaned = "\n".join(lines).strip()
        if not cleaned:
            continue

        # 识别 DDL 类型 + 提取 db/table
        m = _FIRST_ALTER_RE.match(cleaned)  # 复用 8/30 现有 regex
        if m:
            schema = m.group("schema") or ""
            table = m.group("table") or ""
            result.append({
                "stmt_type": "ALTER",
                "db": schema.rstrip(".").strip("`") or None,
                "table": table.strip("`"),
                "full": cleaned,
            })
            continue

        # CREATE / INSERT / UPDATE / DELETE / USE 简化识别 (取首 token)
        first_token = cleaned.split()[0].upper().rstrip(";") if cleaned.split() else ""
        stmt_type = first_token if first_token in (
            "CREATE", "INSERT", "UPDATE", "DELETE", "USE",
        ) else "OTHER"
        result.append({
            "stmt_type": stmt_type,
            "db": None,
            "table": None,
            "full": cleaned,
        })
    return result
```

#### 3.3.2 `_enable_ghost_for_workflow` 循环创建 task

```python
def _enable_ghost_for_workflow(workflow: SqlWorkflow, created_by: str) -> dict:
    """DBA-bug-9: 改为扫所有 statement, 每个 ALTER 一个 task, 非 ALTER 直接 reject。
    """
    parsed_all = _parse_all_statements(_workflow_sql_text(workflow))
    if not parsed_all:
        return {"ok": False, "error": "工单 SQL 为空"}

    # 非 ALTER 检查
    non_alter = [s for s in parsed_all if s["stmt_type"] != "ALTER"]
    if non_alter:
        names = ", ".join(s["stmt_type"] for s in non_alter[:3])
        return {
            "ok": False,
            "error": (
                f"gh-ost 模式仅支持 ALTER TABLE, 工单含非 ALTER 语句 ({names});"
                " 请拆分: CREATE / INSERT / UPDATE / DELETE 单独提交工单"
            ),
        }

    # 至少要有一条 ALTER
    if not parsed_all:
        return {"ok": False, "error": "未找到 ALTER TABLE 语句"}

    # 已经存在 task?
    existing = DdlGhostTask.objects.filter(workflow=workflow).first()
    if existing and existing.status in ("running", "cut_over", "queued"):
        return {
            "ok": False,
            "error": f"task 已在执行中 (status={existing.status}), 不能重复启用",
        }

    # 循环创建 task
    created_tasks = []
    for idx, stmt in enumerate(parsed_all):
        db_name = stmt["db"] or workflow.db_name
        table_name = stmt["table"]
        if not db_name or not table_name:
            return {
                "ok": False,
                "error": f"第 {idx + 1} 条 ALTER 无法解析 db/table: {stmt['full'][:100]}",
            }

        report = run_all_prechecks(
            workflow=workflow,
            instance=workflow.instance,
            db_name=db_name,
            table_name=table_name,
            alter_sql=stmt["full"],
        )
        task = _upsert_task(
            workflow, stmt, db_name, table_name,
            statement_index=idx,
            passed=report["passed"], report=report,
            created_by=created_by,
        )
        created_tasks.append(task)

    # 汇总
    all_passed = all(t.precheck_passed for t in created_tasks)
    return {
        "ok": all_passed,
        "passed": all_passed,
        "summary": f"{len(created_tasks)} 条 ALTER {'全部通过' if all_passed else '部分未通过'}",
        "tasks": [{"id": t.id, "index": t.statement_index, "table": t.table_name,
                   "passed": t.precheck_passed} for t in created_tasks],
        "task_id": created_tasks[0].id if created_tasks else None,  # 兼容旧字段
    }
```

### 3.4 poller 改造 (核心:全部 task 终态才改 wf.status)

```python
## CUSTOM-MODIFIED: DBA-bug-9 _sync_workflow_status 改成"全部 task 终态"才改 wf.status
## 关联: docs/changelogs/2026-09-16_dba-bug-9-ghost-multi-statement.md
## 根因 (9/16 wf#4841): 旧版 task success → 立即改 wf.status=workflow_finish,
##       绕过 execute_sql 路径,非 gh-ost 处理的 SQL (CREATE/INSERT/UPDATE/DELETE) 全部丢失
## 改法: 加 _all_tasks_terminal 检查, 全部终态才同步 wf.status
def _sync_workflow_status(task, new_status: str):
    if task.task_type != "ghost":
        return  # rebuild 跳过
    if not task.workflow_id:
        return

    # DBA-bug-9: 检查该工单所有 task 是否都已终态
    all_tasks_terminal, total, finished = _all_tasks_terminal(task.workflow_id)
    if not all_tasks_terminal:
        logger.info(
            "_sync_workflow_status: defer task=%s wf=%s status=%s "
            "(%s/%s tasks terminal)",
            task.id, task.workflow_id, new_status, finished, total,
        )
        return

    # 全部终态 → 计算 wf.status
    from sql.models import SqlWorkflow
    try:
        wf = SqlWorkflow.objects.get(pk=task.workflow_id)
    except SqlWorkflow.DoesNotExist:
        return

    # 任一 task failed/cancelled → wf=workflow_exception
    failed_tasks = DdlGhostTask.objects.filter(
        workflow_id=task.workflow_id,
        task_type="ghost",
        status__in=("failed", "cancelled", "rolled_back"),
    )
    target = "workflow_exception" if failed_tasks.exists() else "workflow_finish"

    # 仅在工单处于预期状态时同步
    if wf.status not in ("workflow_review_pass", "workflow_executing", "workflow_timingtask"):
        return
    wf.status = target
    wf.finish_time = timezone.now()
    wf.save(update_fields=["status", "finish_time"])
    logger.info(
        "_sync_workflow_status: ALL TERMINAL task=%s wf=%s → %s",
        task.id, wf.id, target,
    )


def _all_tasks_terminal(workflow_id: int) -> Tuple[bool, int, int]:
    """检查该工单所有 ghost task 是否都已终态。

    Returns:
        (all_terminal, total, finished_count)
    """
    tasks = DdlGhostTask.objects.filter(
        workflow_id=workflow_id,
        task_type="ghost",
    )
    total = tasks.count()
    if total == 0:
        return (False, 0, 0)  # 没 task 不算终态
    finished = tasks.filter(
        status__in=("success", "failed", "cancelled", "rolled_back"),
    ).count()
    return (finished == total, total, finished)
```

### 3.5 前端改造

#### 3.5.1 `views.py` 详情视图

```python
## CUSTOM-MODIFIED: DBA-bug-9: get all ghost tasks instead of one
## @ 2026-09-16 @ mavis
ghost_tasks = DdlGhostTask.objects.filter(
    workflow=workflow_detail, task_type="ghost",
).order_by("statement_index")
has_ghost_task = ghost_tasks.exists()
active_ghost_tasks = [t for t in ghost_tasks if t.status in (
    "queued", "running", "cut_over", "precheck_failed"
)]
has_active_ghost_task = bool(active_ghost_tasks)
all_ghost_tasks_terminal = all(t.is_terminal for t in ghost_tasks) if ghost_tasks else False
```

#### 3.5.2 `detail.html` 多 task 列表

```html
{% if ghost_tasks %}
<div class="panel panel-default">
    <div class="panel-heading">
        <i class="fa fa-rocket"></i> gh-ost 无锁变更
        <span class="badge">{{ ghost_tasks|length }} 个 task</span>
        {% if not all_ghost_tasks_terminal %}
        <span class="badge" style="background:#67C23A;">
            {{ active_ghost_tasks|length }} 个执行中
        </span>
        {% else %}
        <span class="badge" style="background:#909399;">全部已结束</span>
        {% endif %}
    </div>
    <div class="panel-body">
        <table class="table table-condensed">
            <thead>
                <tr>
                    <th>序号</th>
                    <th>task #</th>
                    <th>表</th>
                    <th>ALTER 子句</th>
                    <th>状态</th>
                    <th>进度</th>
                </tr>
            </thead>
            <tbody>
                {% for t in ghost_tasks %}
                <tr>
                    <td>{{ t.statement_index }}</td>
                    <td>#{{ t.id }}</td>
                    <td>{{ t.db_name }}.{{ t.table_name }}</td>
                    <td><code>{{ t.alter_statement|truncatechars:80 }}</code></td>
                    <td>{{ t.get_status_display }}</td>
                    <td>{{ t.progress_pct }}%</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% if workflow_detail.status == "workflow_finish" and not all_ghost_tasks_terminal %}
        <div class="alert alert-warning">
            <i class="fa fa-warning"></i>
            工单状态已置为"已正常结束", 但还有 {{ active_ghost_tasks|length }} 个 gh-ost task 在跑;
            请等待所有 task 结束。
        </div>
        {% endif %}
    </div>
</div>
{% endif %}
```

---

## 4. 边界 case 处理

| Case | 行为 | 备注 |
|---|---|---|
| 1 条 ALTER | 创建 1 个 task (statement_index=0) | 兼容旧逻辑 |
| 2 条 ALTER | 创建 2 个 task (statement_index=0/1) | 新逻辑 |
| 1 条 ALTER + 1 条 CREATE | precheck reject "gh-ost 仅支持 ALTER" | 业务方拆单 |
| 1 条 ALTER + 1 条 INSERT | precheck reject "gh-ost 仅支持 ALTER" | 业务方拆单 |
| 0 条 (空 / 全注释) | precheck reject "未找到 ALTER" | 显式提示 |
| USE hly_accesscard (无 ALTER) | precheck reject "未找到 ALTER" | 兼容旧逻辑 |
| ALTER vehicle_risk_hit (use 前面) | parse 切 ; 后第一条是 use (USE),跳过;第一条 ALTER 是 vehicle_risk_hit | 按 list 顺序处理 |

---

## 5. 演练方案 (5 case,134 dev + 110 prod)

### 5.1 单元测试 (precheck / parser)

| Case | 输入 | 期望 |
|---|---|---|
| A1 | 1 条 ALTER | parse 返回 1 条 ALTER,statement_index=0 |
| A2 | 2 条 ALTER (不同表) | parse 返回 2 条 ALTER,statement_index=0/1 |
| A3 | 1 条 ALTER + 1 条 CREATE | parse 返回 [ALTER, CREATE];CREATE 触发 reject |
| A4 | 1 条 ALTER + 1 条 INSERT | parse 返回 [ALTER, INSERT];INSERT 触发 reject |
| A5 | 全是 USE / COMMENT | parse 返回 [],reject "未找到 ALTER" |

### 5.2 端到端测试 (134 dev 演练脚本)

| Case | 工单 SQL | 期望 |
|---|---|---|
| B1 | `ALTER TABLE accesscard_black_detail ADD COLUMN test_col int;` | 1 个 task (statement_index=0), 全部 success |
| B2 | `ALTER TABLE t1 ADD COLUMN c1 int; ALTER TABLE t2 ADD COLUMN c2 int;` | 2 个 task (statement_index=0/1), 都 success |
| B3 | `ALTER TABLE t1 ... ; CREATE TABLE t2 ...;` | precheck reject |
| B4 | `USE hly_accesscard; ALTER TABLE accesscard_black_detail ...;` | parse 后 USE 被跳,1 个 task |
| B5 | `ALTER TABLE accesscard_black_detail ... ENGINE=InnoDB;` (5.7 触发重写) | 1 个 task, 5.7 走 COPY 触发,8.0 走 INSTANT no-op (架构限制) |

### 5.3 110 prod 复现 drill (跟 134 dev 同样 5 case)

---

## 6. 部署计划 (DBA 一条龙,不主动补建)

1. **134 dev 推 4 个文件** (models.py + 0005 migration + views.py + precheck.py + poller.py + detail.html):
   ```bash
   scp -i archery_deploy .../models.py root@134:/opt/archery/prod/sql/extensions/ddl_gh_ost/models.py
   scp -i archery_deploy .../migrations/0005_*.py root@134:/opt/archery/prod/sql/extensions/ddl_gh_ost/migrations/
   scp -i archery_deploy .../views.py root@134:/opt/archery/prod/sql/extensions/ddl_gh_ost/views.py
   scp -i archery_deploy .../precheck.py root@134:/opt/archery/prod/sql/extensions/ddl_gh_ost/services/precheck.py
   scp -i archery_deploy .../poller.py root@134:/opt/archery/prod/sql/extensions/ddl_gh_ost/services/poller.py
   scp -i archery_deploy .../detail.html root@134:/opt/archery/prod/sql/templates/detail.html
   ```
2. **134 dev 跑 migration**: `docker-compose exec archery python manage.py migrate`
3. **134 dev reload master**: `systemctl restart archery-prod-gunicorn.service`
4. **134 dev 演练 5/5 PASS**
5. **110 prod 推同样 5 文件**
6. **110 prod 跑 migration**: `python manage.py migrate`
7. **110 prod reload master**: `kill -TERM <master> && nohup setsid 重启`
8. **110 prod 复现 drill 5/5 PASS**
9. **wf#4841 业务方通知**:
   - **不主动补建 vehicle_risk_hit_detail** (按"不动生产数据"原则)
   - 提供 wf#4841 实际 CREATE 语句,业务方自己 review 后决定补建

---

## 7. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 旧 task (statement_index=NULL/0) 跟新 unique_together 冲突 | 低 | migration 失败 | migration 用 default=0 + ignore_old_uniques |
| 多 ALTER 跑,任一失败,工单仍显示"已完成" | 中 | 业务方误判 | poller 改成"任一 failed → workflow_exception" |
| reload master 业务中断 | 低 | 10-30 秒 | DBA 一条龙规范,运维通知 |
| 业务方已用 wf#4841 投产 → 数据缺失 | 已发生 | 中 | 通知业务方补建 + 加 CREATE 拒绝逻辑 |

---

## 8. 实战新发现 (DBA-bug-9,跨项目可复用, 待入 MEMORY)

1. **gh-ost 启用 → 工单 execute 路径被绕过**: 启用 gh-ost 后, GoInception.execute_workflow 0 次调用, 工单直接由 poller 同步状态; **非 gh-ost 处理的 SQL (CREATE/INSERT/UPDATE/DELETE) 全部丢失**
2. **Archery 上游 poller 设计缺陷**: poller._sync_workflow_status 看到 task success 就改 wf.status=workflow_finish, 没检查工单 SQL 是否全执行
3. **业务方实战: 工单含多 DDL 是常态**: CREATE TABLE + ALTER 是常见组合 (新表 + 字段调整一起做), 平台不该拒绝业务方, 平台该支持
4. **CREATE TABLE 单独事务拆单原则**: CREATE TABLE 跟 ALTER 在 gh-ost 模式下必须拆单 (CREATE 不可走 gh-ost); 业务方实战教训
5. **gh-ost task unique_together 限制**: DdlGhostTask UniqueConstraint(task_type, workflow) 限制了一个工单只能一个 task, 多 ALTER 必须扩到 (task_type, workflow, statement_index)

---

## 9. 关联 commit / changelog / 设计稿

- 关联 commit: 待推
- 关联 changelog: docs/changelogs/2026-09-16_dba-bug-9-ghost-multi-statement.md
- 关联事件: wf#4841 (9/16 17:00+)
- 关联实战接龙: DBA-bug-1..8 (9/11-9/16)