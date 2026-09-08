# D35 修复: _should_use_ddl_rollback 在 DdlGhostTask.workflow 改 ForeignKey 后失效 (wf#4786 业务方看不到回滚根因)

> **日期**: 2026-09-07 13:50
> **触发**: 业务方截图 110 prod wf#4786 (汪银和 UPDATE fund_penetrate) "查看回滚 SQL" 页面显示"没有找到匹配的记录"
> **根因**: DdlGhostTask.workflow 在 2026-08-06 拆 OneToOne 为 ForeignKey, 但 `_should_use_ddl_rollback` 注释还写 "reverse OneToOne", 代码用 `workflow.ghost_task` 期望抛 `DoesNotExist` 才走 DML 路径. ForeignKey 关系下 `workflow.ghost_task` 是 `RelatedManager` (永远 truthy, 永远不抛错), 导致**所有 DML 工单都被错走 A 方案 (DDL 智能回滚) → rows=[]**.
> **影响范围**: 8/6 改 ForeignKey 之后所有 DML 工单的"查看回滚 SQL"功能 (从 wf#4786 看至少有 9/7 业务方实战暴露)

---

## 一、根因详细链路

### 1. wf#4786 实际数据
- 工单: 汪银和 (wyh) 9/7 17:55 提交, 9/8 09:19 执行结束
- 类型: **DML (syntax_type=2)**
- 4 条 SQL: 1 use + 2 INSERT (waybill_load) + 1 UPDATE (fund_penetrate)
- 备份: 是
- 状态: workflow_finish

### 2. wf#4786 关联的 DdlGhostTask
- **无关联** (查 DdlGhostTask 表里 workflow_id=4786 的所有记录返回空)

### 3. `_should_use_ddl_rollback` 判定逻辑
`sql/services/ddl_rollback.py:119-135`:
```python
def _should_use_ddl_rollback(workflow: SqlWorkflow) -> bool:
    """判定 workflow 是否走 A 方案 (DDL 智能回滚).
    True:  workflow 关联 DdlGhostTask (走 gh-ost 改造的工单)
    False: 普通 DML 工单, 走原 goinception 路径
    """
    try:
        workflow.ghost_task  # reverse OneToOne, 不存在就 DoesNotExist
        return True
    except Exception:
        return False
```

### 4. ForeignKey vs OneToOne 的关键差异

`sql/extensions/ddl_gh_ost/models.py:64-67` (D24 实战注释):
```python
## CUSTOM-MODIFIED: v0.4.5-alpha 拆 OneToOne 为 ForeignKey(null=True) @ 2026-08-06 @ mavis
workflow = models.ForeignKey(
    "sql.SqlWorkflow", on_delete=models.CASCADE,
    related_name="ghost_task",
    null=True, blank=True,
)
```

| Django 关系 | `workflow.ghost_task` 返回 | 无关联时 |
|---|---|---|
| **OneToOneField** (改前) | DdlGhostTask 实例 | 抛 `DoesNotExist` |
| **ForeignKey** (改后) | **RelatedManager** (查询集) | 永远 truthy, 永远不抛错 |

### 5. Bug 触发

改 ForeignKey 之后:
- `workflow.ghost_task` 永远返回 RelatedManager, **永远不抛 DoesNotExist**
- `try-except` 永远不触发 except
- `return True` 永远执行
- **所有工单** (包括没 DdlGhostTask 关联的 DML 工单) 都走 A 方案
- A 方案 `_is_alter_table(stmt)` 只识别 ALTER TABLE, wf#4786 的 INSERT/UPDATE 全被 skip
- `rows=[]`, 页面显示"没有找到匹配的记录"

### 6. 实际验证

```
=== wf#4786 走 backup_sql 端点 ===
  syntax_type: 2 (DML)
  _should_use_ddl_rollback: True  ❌ (DML 工单被误判)
  A result: status=0 rows=0 warnings=0  ❌ (rows 空)

=== 直接 GoInceptionEngine.get_rollback(workflow) ===
  rows: 3  ✅ (DML 路径能查到 3 行回滚)
```

实际 inception 备份库 (`172.20.2.110:3306` / `172_20_2_20_6446_hly_platform`) 里:
- `fund_penetrate` 备份表: 5 行 rollback_statement (UPDATE 反向 SQL)
- `waybill_load` 备份表: 71435 + 20618 行 rollback_statement (INSERT 回滚)

数据完整存在, 走 DML 路径 (GoInceptionEngine) 能查到 3 行. 但前端走的是 A 方案, 看到空.

## 二、修法

### 方案 A (推荐): 改 `_should_use_ddl_rollback` 用 `.filter().exists()`

```python
# 修前 (ddl_rollback.py:119-135)
def _should_use_ddl_rollback(workflow: SqlWorkflow) -> bool:
    try:
        workflow.ghost_task
        return True
    except Exception:
        return False

# 修后
def _should_use_ddl_rollback(workflow: SqlWorkflow) -> bool:
    """判定 workflow 是否走 A 方案 (DDL 智能回滚).
    True:  workflow 关联 DdlGhostTask (走 gh-ost 改造的工单)
    False: 普通 DML 工单, 走原 goinception 路径
    """
    return DdlGhostTask.objects.filter(workflow=workflow).exists()
```

**优点**: 1 行代码修复, 跟 D24 改 ForeignKey 后的关系模型一致
**风险**: 极低, 不影响其他逻辑

### 方案 B: 用 `if workflow.ghost_task.exists():`

```python
def _should_use_ddl_rollback(workflow: SqlWorkflow) -> bool:
    return workflow.ghost_task.exists() if hasattr(workflow, 'ghost_task') else False
```

跟 A 方案等价, 但代码稍繁琐.

### 方案 C: 不改, 让 A 方案有更好的兜底

让 A 方案在 `rows=[]` 时降级到 DML 路径:
```python
# backup_sql 端点
if _should_use_ddl_rollback(workflow):
    result = generate_ddl_rollback(workflow)
    if result["rows"] or result["warnings"]:
        return HttpResponse(json.dumps(result), content_type="application/json")
    # rows=[] 且无 warnings → 降级 DML (说明工单不是 DDL, 是 DML)
    # fall through
```

**优点**: 不改 A 方案判定, 兜底更稳健
**缺点**: 每次 DML 工单都先跑 A 方案空跑, 性能略差

## 三、推荐修法

**走 A 方案 + 1 行代码修复**. 跟用户"一条龙"风格一致, 最干净.

**额外建议**: 既然 `_should_use_ddl_rollback` 注释写错了, 顺便把相关注释和 changelog 一起更新.

## 四、相关 context

- D24 实战: `sql/extensions/ddl_gh_ost/models.py:64` 拆 OneToOne 为 ForeignKey (注释 `CUSTOM-MODIFIED: v0.4.5-alpha 拆 OneToOne 为 ForeignKey @ 2026-08-06 @ mavis`)
- 引入时间: 2026-08-06
- 暴露时间: 2026-09-07 (业务方 wf#4786 实战, 距引入 1 个月)
- 影响范围: 8/6 - 9/7 期间所有 DML 工单"查看回滚 SQL"都受影响 (功能不可用, 但 wf 数据本身备份完整, 走 DML 路径能拿)
- 134 dev 同步修 + 演练 PASS 后 D35 push 推 110 prod (合并到 D35 push 范围)

## 五、关联 D35 实战 push

D35 push 9 步 runbook Step 6 跨 app 文件清单**新增 1 个**:
- `sql/services/ddl_rollback.py` (D35 backticks 修复) — D35 顺手修这个 bug

总跨 app 文件从 11 个增加到 12 个.
