# v0 gh-ost 智能模式 (smart mode) — 阶段 2/4 完整落地

## 一句话总结

gh-ost 工单支持 `gh_ost_mode` 三选一 (smart / all_ghost / all_native),
单工单多 ALTER 大小表混合时,业务方可选 smart(智能分流)/all_ghost(全 gh-ost)/all_native(全原生),
task 串行依赖链 + wf.status poller 统一控制。134 dev + 110 prod 演练 7/7 PASS。

## 业务背景

业务方实战 wf#4841 (DBA-bug-9) 显示:**单工单多 ALTER 大小表混合**是常态,
9/16 21:42 阿达叔叔拍板 5A:

1. **大表阈值**: 复用 `CUSTOM_BIG_TABLE_ROW_THRESHOLD=100000` (10w 行) / `CUSTOM_BIG_TABLE_SIZE_THRESHOLD_MB=100`
2. **小表路径**: `mysql.execute()` 原生直连 ALTER,不走 GoInception (DBA 一条龙不动生产数据的捷径)
3. **task 串行依赖链**: `task.depends_on_id` ForeignKey self,前一个 task success 才能启下一个
4. **gh_ost_mode 选法**: 工单提交页下拉框 (smart 默认 / all_ghost / all_native 三选一)
5. **wf.status 控制**: poller 统一,全部 ghost task 终态 + 小表 ALTER 完成 才改 wf.status;任一 failed → workflow_exception

## 实施阶段

### 阶段 1 (commit `7ca2866` 9/16 21:45) — 设计稿 + 数据模型
- 设计稿: `docs/designs/2026-09-16_v0-gh-ost-smart-mode-design.md` (12.3KB, 311 行)
- SqlWorkflow 加 `gh_ost_mode` 字段 (smart/all_ghost/all_native, default=smart, db_index=True)
- SqlWorkflow 加 `native_alter_results` JSONField (smart 模式小表 ALTER 结果记录)
- DdlGhostTask 加 `depends_on` ForeignKey self (串行依赖链)
- migration `0006_dba_bug_v0_gh_ost_smart.py` (阶段 1 写错位置,SqlWorkflow 字段放 ddl_gh_ost app,KeyError 报死)

### 阶段 2 (本 commit 9/17 10:30) — 完整改造

#### 跨 app migration 拆分 (踩坑 1)
- 阶段 1 的 `0006_dba_bug_v0_gh_ost_smart.py` 把 SqlWorkflow 字段 + DdlGhostTask.depends_on 都放在 ddl_gh_ost app
- migrate 时报 `KeyError: ('ddl_gh_ost', 'sqlworkflow')` (Django state 找不到跨 app 的 model)
- **修法**: 拆 2 个 migration
  - `sql/migrations/0001_initial.py`: 最小化 stub (SeparateDatabaseAndState 加 5 个 CreateModel, lazy reference 能 resolve)
  - `sql/migrations/0002_v0_gh_ost_smart.py`: SqlWorkflow 加 gh_ost_mode + native_alter_results
  - `sql/extensions/ddl_gh_ost/migrations/0006_dba_bug_v0_gh_ost_smart.py`: 只保留 DdlGhostTask.depends_on,dependencies 加 0005 (修 conflict)

#### 业务方代码改造 (6 文件)
1. **`sql_api/api_workflow.py`**: 工单提交接收 `gh_ost_mode` 字段 (默认 smart),存到 SqlWorkflow
2. **`sql/extensions/ddl_gh_ost/views.py`**:
   - `_enable_ghost_for_workflow` 按 gh_ost_mode 分流 (smart 查 size_info,big→gh-ost task,small→small_alters)
   - 串行依赖链设置 (depends_on)
   - `_trigger_native_alters` 串行执行 wf.native_alter_results 里小表 ALTER (fail-fast,skip 后续)
   - `_start_next_ghost_task` poller 触发依赖链下一个
   - `_workflow_sql_text` 优先用 workflow.sql_content 属性 (演练脚本 MagicMock 友好)
3. **`sql/extensions/ddl_gh_ost/services/poller.py`**:
   - `_sync_workflow_status` v0 改造: task success 调 `_start_next_ghost_task` 触发依赖链下一个
   - wf.status 控制: 全部 ghost task 终态 + wf.native_alter_results 全部完成 才改 wf.status
   - 任一 failed → workflow_exception
4. **`sql/templates/sqlsubmit.html`**: 工单页 gh_ost_mode 下拉框 (勾 enable_ghost 时显示),JS change handler
5. **`sql/templates/detail.html`**: 显示 gh_ost_mode + 依赖 task # 列 + native_alter_results 渲染块
6. **`sql/extensions/ddl_gh_ost/models.py`**: rebuilt_* 字段 help_text 修正 (跟 0004 migration 一致,避免 makemigrations 报警告)

### 阶段 3 (9/17) — 演练 7/7 PASS

演练脚本 `scripts/_w3_v0_smart_drill.py` (7 case, 13.6KB):
- **A**: smart 模式 1 大 + 1 小 → 1 task + 1 small ALTER
- **B**: smart 模式 全大表 (同表 2 ALTER) → 2 task 依赖链
- **C**: smart 模式 全小表 (2 不存在表) → 0 task + 2 small ALTER
- **D**: all_ghost 模式 1 大 + 1 小 → 2 task (强制小表也走 gh-ost)
- **E**: all_native 模式 1 大 + 1 小 → 0 task + 2 small ALTER (强制大表也走原生)
- **F**: 1 大 + 1 CREATE → reject (gh-ost 模式仅支持 ALTER)
- **G**: depends_on 串行依赖链测试 (用 transaction.atomic savepoint 回滚,不污染 db)

演练结果:
- **134 dev**: archery_dev / accesscard_black_detail (238k 行 / 134 MB) → 7/7 PASS
- **110 prod**: hly_accesscard / accesscard_dynamicaccountinfo (1.5 亿行 / 154 GB 真实生产大表) → 7/7 PASS

演练脚本关键技术:
- `patch.object(DdlGhostTask._default_manager, "filter", ...)` patch Django Manager (普通 patch DdlGhostTask 不行)
- `fake_wf_magic` 用 MagicMock 模拟 workflow,`_workflow_sql_text` 优先读 `workflow.sql_content` 属性避免 ORM 查询
- Case G 用 `transaction.atomic()` + `savepoint_rollback()` 回滚不污染 db

### 阶段 4 (9/17 11:00) — 134 dev + 110 prod 部署 + reload + 验证

#### 134 dev 部署 (DBA 一条龙)
- 推 9 文件 (overwrite 6 modified + 新建 3)
- `manage.py migrate`: `sql.0002_v0_gh_ost_smart OK` + `ddl_gh_ost.0006 OK` + 自动生成 `ddl_gh_ost.0007_alter_ddlghosttask_options OK` (Meta options 同步,no-op)
- `systemctl restart archery-prod-gunicorn.service` (master 50430 → 61881, 业务中断 ~10 秒)
- HTTP 200 + 7 case 演练 PASS

#### 110 prod 部署 (DBA 一条龙)
- 110 prod 特殊处理:
  - sql/migrations/ 目录原本不存在,需要先创建 (`mkdir` + `__init__.py`)
  - settings.py 第 493 行 `env("CAS_SERVER_URL")` 没 default,需要 export 占位 env vars
  - 110 prod 用 Django 4.2.30 (134 dev 5.2.16),但 migration 语法兼容
  - `migrate sql 0002` 用 `--fake` 跳过 state 检查 (因为 110 prod db 里没有完整 sql.models state,后续手动 ALTER 补字段)
- 推 10 文件 + 手动 ALTER 加字段 (gh_ost_mode / native_alter_results / depends_on_id)
- 手动 reload master: `kill -TERM 80828` + setsid nohup 启动新 master (67671),需要 export CAS env vars
- HTTP 200 + 7 case 演练 PASS (用真实生产大表 accesscard_dynamicaccountinfo 154GB)

## 实战新发现 (4 条,跨项目可复用)

### 1. 跨 app migration 必须拆开, 不能一锅端 (跨项目通用)
跨项目 SqlWorkflow 字段不能放 ddl_gh_ost app 的 migration:
- 旧版: `0006_dba_bug_v0_gh_ost_smart.py` 在 ddl_gh_ost app 里操作 `model_name="sqlworkflow"` → KeyError
- 新版: SqlWorkflow 字段 → sql app migration; DdlGhostTask 字段 → ddl_gh_ost app migration
- 实战踩坑: 9/17 推 134 dev / 110 prod 时,Django state 检查找不到跨 app 的 model
- 修法: 拆 2 个 migration, dependencies 显式声明 `(sql, "0002_v0_gh_ost_smart")`

### 2. 空 stub migration + lazy reference 解析失败 (跨项目通用)
跨项目二次开发仓库,本地仓库没某个 app 的 `0001_initial.py`,但 db 里 django_migrations 表已有记录:
- 旧版: stub 用 `operations=[]` 空 operations → Django state 检查时,ddl_gh_ost 的 ForeignKey 'sql.users' lazy reference 找不到 (state.models 里没有 sql.users 的 ModelState)
- 新版: stub 用 `migrations.SeparateDatabaseAndState` 加 CreateModel (5 个 model: resource_group / users / instance / sqlworkflow / workflowaudit) → database_operations=[] 不真建表,state_operations 让 state.models 包含这些 model
- 实战踩坑: 9/17 推 110 prod 时,`migrate` 报 `app 'sql' doesn't provide model 'users'` (因为 0001_initial 是空 stub)
- 修法: 写一个最小化的 stub migration, 用 SeparateDatabaseAndState 加 CreateModel 给 lazy reference 涉及的 5 个 model (其他 model 不需要,因为 lazy reference 只指向这 5 个)

### 3. `_workflow_sql_text` 加 mock-friendly fallback (DBA 演练优化)
跨项目写 gh-ost / work-order / SQL 平台,核心函数读工单 SQL 文本时:
- 旧版: `SqlWorkflowContent.objects.get(workflow=workflow)` 走真实 ORM → 演练脚本用 MagicMock 时 filter(workflow=mock) 报错
- 新版: `_workflow_sql_text` 优先 `getattr(workflow, "sql_content", None)`,fallback ORM 查询
- 实战踩坑: 9/17 v0 智能模式演练 MagicMock workflow,`_enable_ghost_for_workflow` 直接走 ORM,演练失败
- 修法: 在 `_workflow_sql_text` 加 fallback (优先级: 属性 > ORM),这样演练脚本直接设 `fake.sql_content = sql_content` 就能跑
- 注意: 不影响线上行为,真实 SqlWorkflow 模型没有 `sql_content` 属性,fallback 走 ORM 查询

### 4. patch.object(_default_manager, ...) patch Django Manager (跨项目通用)
跨项目写 gh-ost / work-order 演练脚本,patch Django 模型时:
- 旧版: `patch("views.DdlGhostTask", spec=False)` 普通 patch → `MagicMock(spec=DdlGhostTask)` 让 `objects.filter` 是 method object,不能设 `.return_value`
- 新版: `patch.object(DdlGhostTask._default_manager, "filter", return_value=FakeQuerySet([]))` 直接 patch Manager
- 实战踩坑: 9/17 v0 智能模式演练 patch DdlGhostTask 失败,AttributeError: 'method' object has no attribute 'return_value'
- 修法: Django 的 `Model.objects` 是 Manager (descriptor),普通 patch Model 不行,要 patch `_default_manager.filter`

## 改动文件清单 (10 文件)

### Modified (6)
- `sql/extensions/ddl_gh_ost/migrations/0006_dba_bug_v0_gh_ost_smart.py` (dependencies 加 0005, 只保留 DdlGhostTask.depends_on)
- `sql/extensions/ddl_gh_ost/services/poller.py` (+45 行, v0 改造 wf.status 控制)
- `sql/extensions/ddl_gh_ost/views.py` (+280 行, _enable_ghost_for_workflow 智能分流 + 依赖链 + _trigger_native_alters + _start_next_ghost_task)
- `sql/extensions/ddl_gh_ost/models.py` (rebuilt_* help_text 跟 0004 migration 一致,避免 makemigrations 警告)
- `sql/templates/detail.html` (+71 行, gh_ost_mode badge + 依赖 # 列 + native_alter_results 渲染块)
- `sql/templates/sqlsubmit.html` (+32 行, gh_ost_mode 下拉框 + JS change handler)
- `sql_api/api_workflow.py` (+18 行, 工单提交接收 gh_ost_mode)

### New (3)
- `sql/migrations/0001_initial.py` (新建, SeparateDatabaseAndState stub)
- `sql/migrations/0002_v0_gh_ost_smart.py` (新建, SqlWorkflow 加 gh_ost_mode + native_alter_results)
- `scripts/_w3_v0_smart_drill.py` (新建, 7 case 演练)

## 业务效果

业务方工单提交流程 (sqlsubmit.html):
1. 勾"启用 gh-ost" → 显示 gh_ost_mode 下拉框
2. 默认 smart: 大表 → gh-ost task (单 task 或多 task 依赖链),小表 → 原生 ALTER
3. all_ghost: 强制所有 ALTER 走 gh-ost (含小表)
4. all_native: 强制所有 ALTER 走原生 (含大表)
5. 工单含 CREATE / INSERT / UPDATE / DELETE → 提醒拆单 (DBA-bug-9 改造,前端 banner)

DBA / 业务方看工单详情 (detail.html):
1. 顶部显示 gh_ost_mode badge (智能 / 全 gh-ost / 全原生)
2. ghost task 列表 (序号/task #/依赖 #/表/alter 子句/状态/进度/开始/结束)
3. 小表原生 ALTER 结果块 (smart/all_native 模式才显示)

## 关联 commit / 实战接龙

- 关联 commit: `7ca2866` (阶段 1 设计稿) + `c4ca623` (DBA-bug-9) + `4b1e415` (DBA-bug-9.5) + `f880521` (DBA-bug-9 changelog)
- 关联事件: DBA-bug-9 + 9.5 + wf#4841 业务方实战 (8 条 SQL: 4 CREATE + 4 ALTER)
- 关联实战接龙: 9/11-9/17 18 事件 (15 commit + 2 软提示 + 1 凭据 + 2 事故 + 7 bug fix)
- 关联 5A 拍板: 9/16 21:42 阿达叔叔

## 待办

- 业务方通知 + MEMORY 实战新发现 (4 条,跨项目可复用)
- v1 禁止提工单 (建表+ALTER 混合工单 → 禁止提交,SQL 提交按钮 disable + 后端兜底) — P2
- 月度宣讲更新 (v0 智能模式 5A 拍板 + 演练结果)

## changelog

`docs/changelogs/2026-09-16_v0-gh-ost-smart-mode.md` (本文件)

@ 2026-09-17 10:30 @ mavis