# 9/17 全天实战成果收尾 (Daily Recap)

> **收尾日期**：2026-09-17 18:35
> **作者**：mavis
> **覆盖时段**：2026-09-17 09:30 ~ 18:35
> **commit 范围**：`62b3cf2~2884b69` (含 9/16 v0 拍板延续)
> **关联文档**：本文档为收尾索引，各子项详见 `2026-09-17_*.md` changelog

---

## 1. 一句话总结

9/17 全天完成 **7 个 commit**，落地 **6 大新功能**（v0 智能模式 + 9.5b 守卫 + v1 禁止 + DDL-Sync 多 ALTER + DBA-bug-10 CREATE INDEX + column_diff 端点），业务方 wf#4841 + wf#4849 两起重大事故闭环，**0 业务中断**，**0 数据/表结构改动**。

---

## 2. 实战成果一览 (7 个 commit)

| # | Commit | 时间 | 类型 | 业务背景 | 实战工单 |
|---|--------|------|------|----------|----------|
| 1 | `62b3cf2` | 09:30 | docs | v1 优化备忘（建表+ALTER 混合 → 禁止提工单拍板） | — |
| 2 | `d3264eb` | 10:30 | feature | **v0 gh-ost 智能模式** 阶段 2 完整落地（大小表混合自动分流） | — |
| 3 | `9d068d9` | 13:10 | fix | **DBA-bug-9.5b** detail 页非 ALTER 警告加 `enable_gh_ost` 守卫（双层防护） | wf#4848 |
| 4 | `18e2ae3` | 13:50 | feature | **v1 混合 DDL 禁止提交**（CREATE+ALTER 拆单，前后端双层防护） | wf#4841 |
| 5 | `fe77c14` | 16:45 | fix | **DDL-Sync-Bug-A** 多 ALTER 工单 + 混合黑/白名单（每个 ALTER 独立判定） | wf#4841 |
| 6 | `4119838` | 17:00 | fix | **DBA-bug-10** CREATE INDEX 绕过 ALTER 检测（5 文件统一修） | wf#4849 |
| 7 | `2884b69` | 17:55 | fix | **DBA-bug-10 column_diff 端点** 补漏（大表 alert banner 显示） | wf#4849 |

---

## 3. 6 大新功能详解

### 3.1 v0 gh-ost 智能模式 (`d3264eb`)

**业务**：单工单含多 ALTER 时，业务方可选智能分流（`smart` 模式默认），大表走 gh-ost 无锁变更，小表走原生 ALTER 降低风险。

**核心改动**：
- 新字段：`SqlWorkflow.gh_ost_mode` (smart/all_ghost/all_native) + `native_alter_results` (JSONField)
- 新字段：`DdlGhostTask.depends_on` (依赖链支持)
- 视图层 `_enable_ghost_for_workflow` 智能分流 + `_trigger_native_alters` 串行执行小表 ALTER
- poller `_sync_workflow_status` 改造（全部 task 终态 + native_alter_results 全完成才改 wf.status）
- detail.html 加 gh_ost_mode badge + 依赖 # 列 + native_alter_results 渲染块

**实战验证**：7/7 case PASS（含 wf#4841 实战 4 ALTER）

### 3.2 DBA-bug-9.5b detail 警告守卫 (`9d068d9`)

**业务**：工单没勾 gh-ost 时，不该显示"gh-ost 模式不支持"警告（无关场景 UX 误导）

**核心改动**：双层防护
- `sql/views.py` detail 视图：`if status_for_alert and getattr(workflow_detail, "enable_gh_ost", False):`
- `sql/templates/detail.html` 警告块：`{% if workflow_detail.enable_gh_ost and non_alter_stmts %}`

**实战验证**：wf#4848（纯 CREATE 没勾 gh-ost）警告不渲染 ✅

### 3.3 v1 混合 DDL 禁止提交 (`18e2ae3`)

**业务**：业务方工单含 CREATE + ALTER 混合时，旧提醒模式无效（业务方无视 banner 继续提交，导致 7/8 失败）。升级为强制禁止。

**核心改动**：双层防护
- 前端：`sql/templates/sqlsubmit.html` 检测回调加 mixed_ddl alert + 阻止提交按钮
- 后端：`sql_api/serializers.py` `WorkflowContentSerializer.create()` 第一步 raise ValidationError
- 错误优先级：mixed_ddl > cross_db > pk_conflict

**实战验证**：8/8 case PASS（含 wf#4841 实战 4 CREATE + 4 ALTER）

### 3.4 DDL-Sync-Bug-A 多 ALTER 黑/白名单 (`fe77c14`)

**业务**：业务方工单含多条 ALTER 时，每条 ALTER 独立判定白/黑名单（不是只看第一条）

**核心改动**：
- `_extract_all_alters(sql_content) -> list[{db, table, full}]`（按 `;` 分割 + 跳 use/注释/空行 + regex 匹配）
- `workflow_passed_handler` 循环每个 ALTER：
  - skipped → `DdlSyncHistory(sync_status='skipped')`（DBA 排查）
  - kept → 拼新 sql_content 创建镜像工单（只含 kept 的 ALTER）
- `_extract_table_name` deprecate 兼容老代码

**实战验证**：e2e PASS（134 dev 镜像工单 #10003 / 110 prod 镜像工单 #4859）

### 3.5 DBA-bug-10 CREATE INDEX 绕过 ALTER 检测 (`4119838` + `2884b69`)

**业务**：业务方用 `CREATE INDEX` 操作 170 万行表（accesscard_channel_task），绕过所有 ALTER 检测，DBA 审核时看不到大表 alert / gh-ost 选项 / 字段 diff / 镜像工单 / 混合 DDL 检测。

**根因**：`CREATE INDEX` 在 MySQL 等价 `ALTER TABLE ADD INDEX`，但代码只识别 `ALTER TABLE` 关键字。

**核心改动**（5 文件）：
- `sql/views.py`：`_parse_first_alter` / `_parse_all_alters` / `_detect_non_alter` / `_check_mixed_ddl`
- `sql/extensions/ddl_gh_ost/views.py`：`_FIRST_CREATE_INDEX_RE` + `_parse_all_statements` CREATE INDEX 路径
- `sql/extensions/ddl_sync/services/sync_trigger.py`：`_CREATE_INDEX_PATTERN` + `_extract_all_alters`
- `sql/templates/sqlsubmit.html`：fetchColumnDiff 触发条件兼容 CREATE INDEX
- `sql/extensions/ddl_gh_ost/services/column_diff.py`（补漏）：`column_diff_full` + `_diff_single_table` 兼容 CREATE INDEX

**实战验证**：10/10 case PASS + 110 prod 真实大表演练 PASS（rows=1707167, size_mb=865.4）

---

## 4. 实战新发现汇总 (按各 commit changelog)

按主题分类（共 24 条实战新发现，按 commit 分布）：

### 4.1 v0 stage 2 (`d3264eb`) — 4 条
1. 跨 app migration 必须拆开，不能一锅端
2. 空 stub migration + SeparateDatabaseAndState + lazy reference 解析失败
3. _workflow_sql_text mock-friendly fallback
4. patch.object(_default_manager, ...) patch Django Manager

### 4.2 DBA-bug-9.5b (`9d068d9`) — 2 条
5. detail 页警告块必加 `enable_xxx` 守卫（双层防护）
6. 跨 commit 部署必查 `git diff --stat`

### 4.3 v1 禁止提工单 (`18e2ae3`) — 2 条
7. "提醒"升级"禁止"必须前后端双层防护
8. SQL 解析复用 split + skip comments + first word token

### 4.4 DDL-Sync-Bug-A (`fe77c14`) — 8 条
9. ddl_sync 多 ALTER 处理规则
10. db_raw 反引号边界处理
11. 110 prod 真实跑路径是 `archery_v114_c9236a0/`（修正旧 memory）
12. 110 prod systemd 服务已 failed（手动 kill + setsid nohup 启动）
13. e2e 演练 mock audit.get_audit 绕过
14. 演练脚本 sys.path 用 `os.getcwd()` 不要写死
15. gunicorn `--daemon --pid /tmp/gunicorn_xxx.pid` 应急启动
16. e2e drill savepoint_rollback 干净退出

### 4.5 DBA-bug-10 (`4119838`) — 8 条
17. CREATE INDEX 等价 ALTER TABLE ADD INDEX（跨项目 SQL 语法）
18. ALTER TABLE / CREATE INDEX 分 2 个 regex（实战新发现：合并 regex 会抓错 table）
19. schema 段 regex 必加 rstrip("."）（实战新发现：抓的 db 含尾点）
20. 详情页 big_table_alert 用 _parse_all_alters（DBA-bug-9.5 复用）
21. SQL 检测弹窗触发条件必含 CREATE INDEX
22. 跨文件 regex 同步（5 文件一次改完）
23. 9.5b 实战固化：CREATE INDEX 归 ALTER 不归 CREATE
24. v1 实战固化：CREATE INDEX 不算混合 DDL

### 4.6 DBA-bug-10 column_diff 端点 (`2884b69`) — 2 条
25. column_diff 端点也要识别 CREATE INDEX（端点必须支持语法等价）
26. 跨文件 regex 同步实战教训（5 个文件改 4 个漏改端点）

**累计**：自 9/11-9/17 共 **56 条实战新发现入档 MEMORY**（含之前 9/11-9/16 实战）

---

## 5. 部署战绩 (DBA 一条龙)

| 环境 | 部署次数 | 业务中断 | 数据/表结构改动 | 实战新发现 |
|------|---------|---------|----------------|----------|
| 134 dev | 6 次 reload | 每次 ~10 秒 | 0 | 演练 26 case PASS |
| 110 prod | 5 次 reload | 每次 ~10 秒 | 0 | 真实生产大表演练 PASS |

**注**：110 prod systemd 9/8 已 failed，全部手动 kill + setsid nohup 启动。9/17 全部成功 reload。

---

## 6. 实战工单链路 (2 起重大事故闭环)

### 6.1 wf#4841 (9/16 17:00+, 9/17 闭环)
- **业务方工单**：4 CREATE + 4 ALTER (8 条 SQL)
- **事故影响**：gh-ost task #26 只处理 1 ALTER（accesscard_licensefront_info），7 条 SQL 全部丢失
- **9/17 闭环**：
  - v0 智能模式（`d3264eb`）：智能分流大表 gh-ost + 小表原生
  - 9.5b 守卫（`9d068d9`）：详情页警告加 enable_gh_ost 守卫
  - v1 禁止（`18e2ae3`）：混合 DDL 禁止提交
  - DDL-Sync 多 ALTER（`fe77c14`）：每条 ALTER 独立判定白/黑名单

### 6.2 wf#4849 (9/17 16:59+, 9/17 闭环)
- **业务方工单**：use + CREATE TABLE + CREATE INDEX（170 万行表 accesscard_channel_task）
- **事故影响**：CREATE INDEX 绕过 ALTER 检测，170 万行表加索引锁表 5-10 分钟风险
- **9/17 闭环**：
  - DBA-bug-10（`4119838`）：CREATE INDEX 等价 ALTER，5 文件统一识别
  - column_diff 端点补漏（`2884b69`）：大表 alert banner 显示

---

## 7. 文件清单 (29 文件)

### 7.1 新建 (10)
- `docs/changelogs/2026-09-16_v0-gh-ost-smart-mode.md` (11.6KB)
- `docs/changelogs/2026-09-17_v1-optimize-mixed-ddl-block-submit.md` (5.4KB)
- `docs/changelogs/2026-09-17_dba-bug-9.5b-detail-alert-gate.md` (5.2KB)
- `docs/changelogs/2026-09-17_v1-mixed-ddl-block-submit.md` (8.3KB)
- `docs/changelogs/2026-09-17_ddl-sync-multi-alter-mixed-blacklist.md` (9.6KB)
- `docs/changelogs/2026-09-17_dba-bug-10-create-index-bypass-alter-check.md` (10.7KB)
- `docs/changelogs/2026-09-17_daily-recap.md` (本文档)
- `sql/migrations/0001_initial.py` (SeparateDatabaseAndState stub)
- `sql/migrations/0002_v0_gh_ost_smart.py` (SqlWorkflow 新字段)
- `scripts/_w3_*.py` (7 个演练脚本)

### 7.2 修改 (19)
- `sql/extensions/ddl_gh_ost/migrations/0006_dba_bug_v0_gh_ost_smart.py`
- `sql/extensions/ddl_gh_ost/models.py`
- `sql/extensions/ddl_gh_ost/services/poller.py`
- `sql/extensions/ddl_gh_ost/services/column_diff.py` (DBA-bug-10 补漏)
- `sql/extensions/ddl_gh_ost/views.py`
- `sql/extensions/ddl_sync/services/sync_trigger.py`
- `sql/templates/detail.html`
- `sql/templates/sqlsubmit.html`
- `sql/views.py`
- `sql_api/api_workflow.py`
- `sql_api/serializers.py`
- `scripts/_commit_msg_*.txt` (3 个 commit message 模板)

---

## 8. 月度宣讲准备 (5 → 6 大新功能)

下次月度宣讲更新点：
- **v0 智能模式**（gh-ost + 大小表自动分流）
- **v1 禁止混合 DDL**（前后端双层防护）
- **DDL-Sync 多 ALTER 黑/白名单**（每个 ALTER 独立判定）
- **DBA-bug-9.5b detail 警告守卫**（双层防护）
- **DBA-bug-10 CREATE INDEX 等价 ALTER**（5 文件统一识别）
- **DBA-bug-10 column_diff 端点**（端点必须支持语法等价）

配套实战案例：
- wf#4841 重大事故（4 CREATE + 4 ALTER 7/8 失败）→ 推动 6 大新功能
- wf#4849 170 万行表 CREATE INDEX → 推动 DBA-bug-10 修复

---

## 9. 下次再说挂账

- **月度宣讲更新**（5 → 6 大新功能，参考第 8 节）
- **W2 剩余挂账** (5 条 P1/P2/P3):
  - settings/urls/base.html commit + .env 补 CAS_SERVER_URL
  - Archery 8.0 兼容
  - gh-ost 二进制部署（v0.3.0-alpha，134 dev 演练大表已迁移完成）
- **gh-ost v0.3.0-alpha** (排在 v0.2.3 OA 对账之后): 灰度 1 个实例跑 1 周
- **110 prod systemd 服务修复** (9/8 failed, 至今 manual reload)

---

## commit 统计

```
7 个 commit, 29 files, +3656 / -640 lines
9/17 当天实战新发现: 26 条 (按各 commit changelog)
累计 9/11-9/17 入档 MEMORY: 56 条
总 changelog: 50KB+ (6 个新功能 changelog + 本收尾文档)
总演练脚本: 7 个 (v0 7 case + v1 8 case + 9.5b N case + DDL-Sync 7 case + DDL-Sync e2e + DBA-bug-10 10 case + DBA-bug-10 column_diff 演练)
134 dev: 6 次 reload, 0 事故
110 prod: 5 次 reload, 0 事故
0 业务数据改动 / 0 表结构改动 (DBA 一条龙原则)
```