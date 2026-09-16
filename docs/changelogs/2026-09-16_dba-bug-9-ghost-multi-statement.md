# DBA-bug-9 gh-ost 多 statement 工单支持 (9/16 17:50+ 拍板 D 方案)

> **作者**: mavis @ 2026-09-16 18:00
> **拍板**: 阿达叔叔 17:42 走 D 方案
> **关联事件**: wf#4841 (业务方实战,多表 DDL + CREATE TABLE 工单)
> **关联设计稿**: `docs/designs/2026-09-16_dba-bug-9-ghost-multi-statement-design.md`

---

## 一句话总结

`_parse_first_alter` 改成 `_parse_all_statements`,每个 ALTER TABLE 都建一个独立 DdlGhostTask;**poller 改成"全部 task 终态才改工单状态"**;CREATE/INSERT/UPDATE/DELETE 拒绝启用 gh-ost,要求业务方拆单。

---

## 背景 (wf#4841 实战)

业务方 9/16 17:00+ 提工单 **wf#4841**,3 条 SQL:

```sql
USE `hly_accesscard`;
ALTER TABLE `vehicle_risk_hit` ADD COLUMN `xxx` varchar(150) DEFAULT NULL COMMENT '...';
CREATE TABLE `vehicle_risk_hit_detail` (
  `hit_id` bigint NOT NULL AUTO_INCREMENT,
  ...
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT '车辆业务风险命中记录明细 (明细表)';
```

业务方勾选"启用 gh-ost" → 审批通过 → gh-ost 切流 vehicle_risk_hit 成功 → poller 同步工单状态为 `workflow_finish`。

**结果**:CREATE TABLE 没执行;工单"已正常结束";**生产数据缺失风险**。

---

## 根因 (4 处代码缺陷)

### 1. `views.py:_parse_first_alter` (line 79-108)

```python
statements = [s.strip() for s in sql_content.split(";") if s.strip()]
for stmt in statements:  # ❌ 只解第一条 ALTER,后续语句全部忽略
    ...
```

### 2. `precheck.py:check_alter_sql` (line 222-242)

```python
statements = [s for s in sqlparse.split(sql_content) if s.strip()]
first = statements[0].strip()  # ❌ 只检第一条 ALTER
```

### 3. `runner.py:build_ghost_command` (line 84-117)

单 gh-ost 进程只 `--table=单表` `--alter=单条`,CREATE TABLE / 多表无机制执行。

### 4. `poller.py:_sync_workflow_status` (line 168-211) **— 最关键**

```python
_WORKFLOW_STATUS_MAP = {
    "success": "workflow_finish",  # ❌ task success → 立即改 wf.status=workflow_finish
}
```

gh-ost task 切流成功 → 立即把 wf.status 改为 `workflow_finish` → **GoInception.execute_workflow 路径 0 次调用** → CREATE TABLE / INSERT 等全部丢失。

---

## 修法 (D 方案,5 文件 + 1 migration + 1 前端)

| 文件 | 改动 |
|---|---|
| `sql/extensions/ddl_gh_ost/models.py` | 加 `statement_index` (Int) + `statement_type` (Char);`unique_together` 改成 (task_type, workflow, statement_index) |
| `sql/extensions/ddl_gh_ost/migrations/0005_dba_bug_9_ghost_multi_statement.py` | AddField × 2 + RemoveConstraint + AddConstraint |
| `sql/extensions/ddl_gh_ost/views.py` | 加 `_parse_all_statements()` (扫所有 statement);改 `_enable_ghost_for_workflow` 循环创建 task;非 ALTER → reject |
| `sql/extensions/ddl_gh_ost/services/precheck.py` | 改 `check_alter_sql` 扫所有 statement,含非 ALTER → reject;USE 跳过 |
| `sql/extensions/ddl_gh_ost/services/poller.py` | 加 `_all_tasks_terminal()`;`_sync_workflow_status` 改成"全部 task 终态才同步 wf.status";任一 failed → wf=workflow_exception |
| `sql/views.py` | 详情视图 query 改成 `filter(workflow, task_type='ghost').order_by('statement_index', 'id')`;加 `ghost_tasks` + `active_ghost_tasks` 到 context |
| `sql/templates/detail.html` | 单 task iframe 改成多 task 列表 (序号/task#/表/alter子句/状态/进度/开始/结束);多 task active 时显示进度详情链接;异常情况 banner |

---

## 演练 5/5 PASS

### 134 dev (`/opt/archery/prod/`)

演练脚本: `scripts/_w3_dba9_drill.py` (134 dev + 110 prod 复用)

| Case | 输入 | 期望 | 结果 |
|---|---|---|---|
| A | 单 ALTER (兼容旧逻辑) | 1 个 task, statement_index=0 | ✅ PASS |
| B | 多 ALTER (不同表) | 2 个 task, statement_index=0/1 | ✅ PASS |
| C | 1 ALTER + 1 CREATE TABLE | reject "gh-ost 仅支持 ALTER" | ✅ PASS |
| D | 1 ALTER + 1 INSERT | reject "gh-ost 仅支持 ALTER" | ✅ PASS |
| E | USE + ALTER (USE 跳过) | pass | ✅ PASS |
| 综合 | _enable_ghost_for_workflow 拒绝非 ALTER | ok=False, error 含"非 ALTER" | ✅ PASS |

### 110 prod (`/dbdata/archery_v114_c9236a0/`)

5/5 PASS (跟 134 dev 同样脚本,sys.path 改 /dbdata/archery_v114_c9236a0)

---

## 部署 (DBA 一条龙,不主动补建)

### 134 dev
1. ✅ 推 7 文件 (models.py + migration + views.py + precheck.py + poller.py + views.py + detail.html + drill.py)
2. ✅ `manage.py migrate ddl_gh_ost` → Applying 0005 OK
3. ✅ `systemctl restart archery-prod-gunicorn.service` (master 14794 → 17936)
4. ✅ HTTP 200 /演练 5/5 PASS

### 110 prod
1. ✅ pscp 推 7 文件
2. ✅ `manage.py migrate ddl_gh_gh_ost` (带 CAS_SERVER_URL 占位) → Applying 0005 OK
3. ✅ kill -TERM 54413 + setsid nohup 启新 gunicorn (master 61590)
4. ✅ HTTP 200 /演练 5/5 PASS

---

## wf#4841 业务方通知 (待发)

业务方 wf#4841 实际工单包含 3 条 SQL:
- use hly_accesscard ✅ (自动跟踪,无需执行)
- ALTER TABLE vehicle_risk_hit ADD COLUMN... ✅ (gh-ost 切流 481463/481463 行成功)
- CREATE TABLE vehicle_risk_hit_detail... ❌ (未执行)

**按 DBA 一条龙原则**:
- **不主动帮业务方补建表**
- 提供 wf#4841 实际 CREATE 语句,业务方自己 review 后决定补建
- 通知业务方: **DBA-bug-9 修复后,类似多表 DDL + CREATE 工单会被 gh-ost 预检拒绝,需要拆成单独工单**

---

## 实战新发现 (DBA-bug-9,跨项目可复用,5 条入 MEMORY)

1. **gh-ost 启用 → 工单 execute 路径被绕过**: 启用 gh-ost 后, GoInception.execute_workflow 0 次调用, 工单直接由状态完成
2. **Archery 上游 poller 设计缺陷**: poller._sync_workflow_status 看到 task success 就改 wf.status, 没检查工单 SQL 是否全执行
3. **业务方实战: 工单含多 DDL 是常态**: CREATE TABLE + ALTER 是常见组合 (新表 + 字段调整一起做)
4. **CREATE TABLE 单独事务拆单原则**: CREATE TABLE 跟 ALTER 在 gh-ost 模式下必须拆单 (CREATE 不可走 gh-ost)
5. **gh-ost task unique_together 限制**: DdlGhostTask UniqueConstraint(task_type, workflow) 限制一个工单只能一个 task

---

## 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 旧 task (statement_index=0) 跟新 unique 不冲突 | 低 | migration 失败 | AddField default=0 + RemoveConstraint/AddConstraint |
| 多 ALTER 跑,任一失败,工单仍显示"已完成" | 中 | 业务方误判 | poller 改成"任一 failed → workflow_exception" |
| reload master 业务中断 | 低 | 10-30 秒 | DBA 一条龙规范 |
| 业务方已用 wf#4841 投产 → 数据缺失 | 已发生 | 中 | 通知业务方补建 + 加 CREATE 拒绝逻辑 |

---

## 关联 commit / changelog / 设计稿

- 关联 commit: 待推
- 关联 changelog: docs/changelogs/2026-09-16_dba-bug-9-ghost-multi-statement.md (本文件)
- 关联设计稿: docs/designs/2026-09-16_dba-bug-9-ghost-multi-statement-design.md
- 关联事件: wf#4841 (9/16 17:00+)
- 关联实战接龙: DBA-bug-1..8 (9/11-9/16)

---

## 后续

1. ✅ 推 134 dev + 110 prod + 演练 5/5 PASS
2. ✅ **DBA-bug-9.5** (9/16 19:55+, 业务方实测发现 2 个前端可见 bug):
   - 问题 1: CREATE TABLE 没提示要拆单
   - 问题 2: 多 ALTER 大表只提示一张表
   - 修法: 加 `big_tables` 列表 + `non_alter_stmts` + `/gh_ost/check_non_alter/` 端点 + 前端 SQL 检测弹窗警告 banner
   - commit `4b1e415`, 演练 6+1 PASS (134 dev + 110 prod)
3. ⏳ 业务方实测 wf#4841 类似多表 DDL 工单
4. ⏳ 通知业务方 wf#4841 vehicle_risk_hit_detail 表没建 (提供 CREATE 语句让他 review)
5. ⏳ gh-ost v0.3.0-alpha 排期 (排在 v0.2.3 OA 对账之后)
6. ⏳ 月度 DBA 宣讲更新 (DBA-bug-9 + 9.5 加进实战案例)