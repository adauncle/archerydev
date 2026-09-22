# 2026-09-22 DBA-bug-13 镜像工单 gh-ost 启用按钮无限循环彻底修复

> 阿达叔叔 9/22 14:01 反馈 wf#4873 详情页点"启用 gh-ost"按钮**没有跳出执行页面**, DevTools Console 无报错。
> 后续 14:56 追问"这个工单为什么查不到", 阿达叔叔亲自去 SQL 查询页查 instance 27 (prod core for history 变更) hly_lockwait_monitor.test → **COUNT=1 (表存在!)**
> 阿达叔叔追问"如果不存在怎么会生成镜像工单" → 让我**彻底修复** (不只前端 alert 救火, 要 UI 正确反映状态).

## 背景

### wf#4873 实际状态 (从 110 prod MySQL 拉出来)

```
instance 27 = prod core for history 变更 (172.20.2.108:6446)
hly_lockwait_monitor.test:
  cnt        = 1       ← 表存在 (我之前查错库误判 0, 阿达叔叔反驳后纠正)
  rows_total = 0       ← 表是空表 (业务方 wf#4872 还没真正写数据)
  total_mb   = 0.2     ← 表大小 0.2 MB
```

### 完整因果链

```
业务方 wf#4872 (源库 instance 11 prod core for etc)
  CREATE TABLE test (...)
  ALTER TABLE test ADD COLUMN test8 varchar(128) ...

DDL-Sync 触发 → 创建 wf#4873 镜像工单
  instance=27 (历史库), SQL 只有 ALTER 部分 (DDL-Sync 不同步 CREATE)
  enable_gh_ost=False, gh_ost_mode='smart'

业务方/管理员 (mkq) 详情页点"启用 gh-ost"
  → POST /gh_ost/precheck/4873/ → 200 (5 道预检通过)
  → POST /gh_ost/enable/4873/ → 200 (后端 0 task 创建)
    → _get_table_size_info(instance=27, db='hly_lockwait_monitor', table='test')
      → SELECT TABLE_ROWS, DATA_LENGTH+INDEX_LENGTH FROM information_schema.tables
      → 返 {rows: 0, size_mb: 0.2, table_name: 'test'}
    → is_big = False (rows=0 < 10w AND 0.2 < 100)
    → smart 模式 fallback 小表 → 加入 small_alters → 不创建 DdlGhostTask
    → 返 {ok: True, summary: "smart 模式分流: 0 大表 + 1 小表原生", tasks: [], task_id: None}

前端 detail.html:444 JS:
  if (!j.ok) { alert(...); return; }
  location.reload()    ← 没显示 summary

reload 后:
  has_ghost_task = False (没创建 ghost task)
  can_enable_ghost = (... perm ...) and not has_ghost_task
                   = True (因为没 ghost task)
  → 详情页又显示"启用 gh-ost"按钮

业务方/管理员再点 → 又一轮同样流程 → 无限循环
```

### 关键 access.log 证据

```
14:00:08 POST /gh_ost/precheck/4873/ HTTP/1.1 200 696 ✅
14:00:08 POST /gh_ost/enable/4873/    HTTP/1.1 200 359 ✅
14:00:11 + 14:00:23 重复 3 次都成功 ✅
但 ext_ddl_ghost_task WHERE workflow_id=4873 → 0 条
```

## 根因

**后端逻辑 100% 正确** (smart 模式分流 + 小表走原生 ALTER 是设计行为, 返 ok=True 但 0 task 是预期).

**前端 UI 反馈缺失**:
1. enable 成功后**不显示 summary** (`location.reload()` 直接结束, 业务方看不到发生了什么)
2. reload 后 has_ghost_task=False → 又显示启用按钮 → 业务方循环点

## 修复 (彻底, 3 处)

文件: `sql/views.py` (1 文件) + `sql/templates/detail.html` (1 文件)

### 后端 views.py 改动

1. **加 has_native_alter 变量** (line 564-572): `has_native_alter = False` (初始), `has_native_alter = bool(workflow_detail.native_alter_results)` (DBA-bug-9 task 同步链已存在)

2. **can_enable_ghost 加守卫** (line 691-702):
   ```python
   can_enable_ghost = (
       (... perm 4 选 1 ...)
       and workflow_detail.status in ("workflow_review_pass", "workflow_timingtask")
       and not has_ghost_task
       and not has_native_alter     # ← DBA-bug-13 守卫 (避免重复加入 small_alters + 避免循环)
   )
   ```

3. **context 加 has_native_alter 字段** (line 824): 模板渲染用

### 前端 detail.html 改动

4. **加第 3 处 elif 分支** (line 396-414): has_ghost_task=False + can_enable_ghost=False + has_native_alter=True → 显示"已加入小表原生 ALTER 队列"
   ```html
   {% elif has_native_alter %}
   <div class="alert alert-success" id="gh-ost-native-alter-block">
       <i class="fa fa-check-circle"></i>
       <strong>已加入小表原生 ALTER 队列</strong> · smart 模式小表不锁表原生执行
       <small>工单含 smart 模式分流后的小表 ALTER（行数 < 10w 行 或 大小 < 100MB），
       提交后会自动跑原生 ALTER（不锁表, 不走 GoInception）。
       无 gh-ost 子进程, 无进度面板。</small>
   </div>
   ```

5. **启用按钮 JS alert 显示 summary** (line 469-484, 主按钮 + line 1108-1123 DBA 兜底按钮):
   ```js
   var msg = '启用成功';
   if (j.summary) msg += '\n\n' + j.summary;
   if (j.tasks && j.tasks.length > 0) {
       msg += '\n\n已创建 ' + j.tasks.length + ' 个 gh-ost task, 刷新查看进度面板';
   } else if (j.gh_ost_mode === 'smart') {
       msg += '\n\n(smart 模式小表已加入原生 ALTER 队列, 提交后自动执行)';
   } else if (j.gh_ost_mode === 'all_native') {
       msg += '\n\n(all_native 模式全部走原生 ALTER)';
   }
   alert(msg);
   location.reload();
   ```

## 验证

### 演练 `scripts/_w3_dba_bug13_verify.py`

```
17/17 PASS:
  后端 (5/5):
    Case 1: views.py has_native_alter = False 初始化
    Case 2: views.py has_native_alter = bool(workflow_detail.native_alter_results)
    Case 3: can_enable_ghost 加 'and not has_native_alter' 守卫
    Case 4: context 加 'has_native_alter' 字段
    Case 5: 加 CUSTOM-MODIFIED 注释引用 DBA-bug-13

  前端 (8/8):
    Case 1-2: has_ghost_task 进度面板 + can_enable_ghost 启用按钮分支保留
    Case 3-4: 新增 has_native_alter 已加入小表原生 ALTER 队列分支
    Case 5-6: 主按钮 + DBA 兜底按钮 JS alert summary
    Case 7-8: DBA 兜底按钮条件 + JS handler 保留

  逻辑 (4/4):
    can_enable_ghost body 含 4 个守卫: is_superuser/has_perm/is_dba_group/is_submitter
    + status (review_pass/timingtask) + not has_ghost_task + not has_native_alter
```

### 部署 (DBA 一条龙)

1. **134 dev (9/22 15:11)**: scp views.py + detail.html + `systemctl restart archery-prod-gunicorn.service` + HTTP 200
2. **110 prod (9/22 15:14)**: scp 2 文件 + reload script + HTTP 200
   - 验证: views.py 8 处 has_native_alter, detail.html 3 处 has_native_alter ✅

### 实战测 (阿达叔叔)

- **wf#4873 详情页硬刷新** (Ctrl+Shift+R):
    - 旧: 显示"启用 gh-ost"按钮 (循环点)
    - 新: 显示"已加入小表原生 ALTER 队列"信息块 (✅ 绿色, 不再有按钮)
- **新工单点启用 gh-ost**: 弹出 alert 显示 summary "smart 模式小表已加入原生 ALTER 队列, 提交后自动执行"

## 实战新发现 (1 条入 MEMORY, 跨项目可复用)

**SQL 审核平台 enable 后端 silent OK 致前端循环点 UX 反馈缺失 (跨项目 UX 实战, 9/22 实战新发现)**:
- 跨项目写 SQL 审核平台 / 启用端点时, 后端判"小表走原生"等分流逻辑, 返 ok=True 但 0 task, **前端必须显示 summary 让业务方知道发生了什么**
- 实战踩坑: 9/22 wf#4873 enable 端点返 `{ok: True, tasks: [], task_id: null}` 但前端 detail.html:444 JS 只 `location.reload()` 不显示 summary, reload 后 has_ghost_task=False → can_enable_ghost=True → 又显示启用按钮 → 业务方循环点
- 修法 (彻底): 后端 `can_enable_ghost` 加 `and not has_native_alter` 守卫 + 新增 has_native_alter elif 块 + 启用按钮 JS alert 显示 summary (`j.summary` + `j.gh_ost_mode` 分流提示)
- **关键**: "silent OK" 永远是 UX bug. 后端返 ok=True 必须给前端明确反馈 (alert/toast/inline msg), 不能只 reload
- 跨项目通用: 任何"启用类"端点 (gh-ost 启用 / 任务执行 / 任务重试), 后端 OK 后前端必须 alert 显示后端返的 summary, 不只 reload

## 关联

- 9/22 阿达叔叔 14:01 反馈 wf#4873 点 gh-ost 没跳出执行页面
- 9/22 阿达叔叔 14:56 追问"如果不存在怎么会生成镜像工单" → 我之前误判查错库
- 9/22 阿达叔叔截图证实 test 表存在 (纠正我的"不存在"诊断)
- 9/22 15:05 让我"彻底修复" (不只 alert 救火)
- `sql/views.py:560-572` (has_native_alter 变量定义)
- `sql/views.py:691-702` (can_enable_ghost 守卫)
- `sql/templates/detail.html:396-414` (新增 has_native_alter 分支)
- `sql/templates/detail.html:469-484` (主按钮 JS alert summary)
- `sql/templates/detail.html:1108-1123` (DBA 兜底按钮 JS alert summary)
- `docs/changelogs/2026-09-22_dba-bug-12-start-dead-import.md` (上一个 bug, 同一 wf 链)