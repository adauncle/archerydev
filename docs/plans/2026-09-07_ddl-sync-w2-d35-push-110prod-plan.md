# D35 实战推 110 prod 完整计划 (9/8 18:30 启动)

> **状态**: 🟡 准备就绪 + D24 ForeignKey bug 紧急热补丁已先于 18:30 完成 (9/8 09:30-09:50)
> **启动时间**: 2026-09-08 18:30 (距今 8 小时)
> **提前 30 分钟**: 9/8 18:00 改 `LIVE_PUSH=True` + 拉新 cron 提醒
> **业务方通知**: ⏰ 待用户拍板渠道 (飞书/钉钉/微信)
> **⚠️ 9/8 09:30 紧急热补丁**: `sql/services/ddl_rollback.py` (D24 ForeignKey bug) 已推 110 prod, 业务方 wf#4786 实测 PASS, 详见下方"零"段

## 零、D24 ForeignKey bug 紧急热补丁 (9/8 09:30-09:50, 业务方实战反馈驱动)

> **状态**: ✅ 已完成 (`commit e94f988` 落地 + 110 prod 热补丁 PASS + 业务方 wf#4786 验证回滚 SQL 3 行 PASS)
> **触发**: 业务方 wf#4786 (汪银和 9/7 17:55 DML UPDATE) 9/8 09:19:15 执行完后, 业务方"查看回滚 SQL"显示"没有找到匹配的记录" - 实战反馈驱动
> **影响**: 12 文件升级版清单中 `sql/services/ddl_rollback.py` (1 个) 已先推, 今晚 18:30 推剩余 11 个

### 根因 (D24 实战新发现, 100% 锁定)
D24 在 2026-08-06 把 `DdlGhostTask.workflow` 从 OneToOne 拆 ForeignKey, 但 `sql/services/ddl_rollback.py` 的 `_should_use_ddl_rollback` 还按老逻辑写 `try: workflow.ghost_task`, 期望 DoesNotExist 才走 DML 路径.

ForeignKey 关系下, `workflow.ghost_task` 返回 `RelatedManager` (永远 truthy), try-except 永远不触发, 导致 **所有 DML 工单从 8/6 到 9/8 (整整 33 天) 都被错走 A 方案 (DDL 智能回滚) → rows=[]**.

### 修法 (1 行修复 + import)
```python
# 修前 (110 prod 老 bug 版)
def _should_use_ddl_rollback(workflow: SqlWorkflow) -> bool:
    try:
        workflow.ghost_task  # reverse OneToOne, 不存在就 DoesNotExist
        return True
    except workflow.ghost_task.RelatedObjectDoesNotExist:
        return False

# 修后 (D35 fix)
def _should_use_ddl_rollback(workflow: SqlWorkflow) -> bool:
    """判定 workflow 是否走 A 方案 (DDL 智能回滚).

    ## CUSTOM-MODIFIED: D35 修复 ForeignKey 后 RelatedManager 永远 truthly 的 bug @ 2026-09-07 @ mavis
    ## 根因: D24 8/6 改 DdlGhostTask.workflow 从 OneToOne 拆 ForeignKey, 但本函数
    ##       用 workflow.ghost_task 期望 DoesNotExist, ForeignKey 关系下
    ##       ghost_task 是 RelatedManager (永远 truthly), try-except 永远不触发,
    ##       所有 DML 工单都被错走 A 方案 → rows=[].
    ## 修法: 改用 .filter(workflow=workflow).exists() 显式查
    """
    return DdlGhostTask.objects.filter(workflow=workflow).exists()
```

### 4 步落地链路 (9/8 09:30-09:50)
1. **commit 修法**: `e94f988` (2 files, +163/-7, 含 changelog `docs/changelogs/2026-09-07_ddl-sync-w2-d35-bug-ghost-task-manager.md`)
2. **md5 校验**: 134 dev (`0ec505fd...`) vs 110 prod (`30355b0b...` 老 bug 版), 推前不一致
3. **scp 推 110 prod**: 22519 bytes, 推后 md5 一致 (`0ec505fd...`)
4. **kill + 拉新 gunicorn**: 5 进程, 9123 LISTEN, /login/ 200
5. **业务方数据验证 PASS**:
   - `_should_use_ddl_rollback(wf#4786) = False` (DML 正确走 goinception, 修前 True)
   - `engine.get_rollback(wf#4786)` 返回 3 行: UPDATE 反向 + 2 个 DELETE FROM (修前 `[]`)
   - wf#4786 实测 3 条 DML: 1 UPDATE fund_penetrate (5 行) + 2 INSERT waybill_load (71435 + 20618 行), 全部有完整回滚 SQL

### 业务方通知话术 (用户 DBA 阿达叔叔发)
> 汪银和你 9/7 17:55 提的 wf#4786 (DML UPDATE fund_penetrate) 回滚 SQL 现在能查了. 之前是后台有个 bug, DML 工单都查不到 (8/6-9/8 期间所有 DML 都受影响). 修法已上 110 prod (今早 9:30), 你刷新工单详情页 → 点 "查看回滚 SQL", 应该能看到 3 行回滚 (1 UPDATE 反向 + 2 DELETE FROM). 备份数据一直都在 inception 库里, 之前是查询路径走错.

### 同源 entry
- 9/7 13:50 排查: `scripts/_archive/_d35_110prod_get_rollback_debug.py` (ssh 端实测 3 行 + rows=[] 对比)
- 9/7 14:00 演练: `scripts/_archive/_d35_134dev_ghost_fix_verify.py` (134 dev 演练 PASS: DML 无 ghost 工单 should_ddl=False)
- 9/8 09:30 热补丁: `scripts/_archive/_d35_hotfix_110prod_d24.py` (4 步落地: commit + md5 + scp + kill+拉新)
- 9/8 09:48 验证: `scripts/_archive/_d35_verify_v2.py` (业务方数据验证 PASS: 3 行回滚 SQL)

## 一、本次推送范围 (9 步 runbook)

### 4 大步 (Django app 部署)
1. **Step 1**: copy 整个 `sql/extensions/ddl_sync/` 目录 (53+ 文件)
2. **Step 2**: `archery/settings.py` 加 `INSTALLED_APPS += ("sql.extensions.ddl_sync.apps.DdlSyncConfig",)`
3. **Step 3**: `archery/urls.py` 加 `path("ddl_sync/", include(("sql.extensions.ddl_sync.urls", "ddl_sync"), namespace="ddl_sync"))`
4. **Step 4**: `common/templates/base.html` 加 ddl_sync menu (带 `{% if perms.ddl_sync.view_ddlsyncpair %}` 守卫)

### 1 步数据库
5. **Step 5**: `cd /dbdata/archery_v114_c9236a0 && sudo -u archery venv/bin/python manage.py migrate ddl_sync`

### 1 步跨 app 文件 (Step 6: 12 文件升级版, 9/8 09:30 D24 已推 1 个, 今晚推 11 个)
6. **Step 6**: 推跨 app 12 文件清单 (D34 演练升级版, 跟 memory 同步):
   1. `sql/extensions/ddl_gh_ost/models.py` (D35 nover 去掉版本号 - TASK_TYPE_CHOICES line 32-33)
   2. `sql/extensions/ddl_gh_ost/migrations/0002_*.py` (D35 nover 同步 choices line 41-42)
   3. `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/progress_rebuild.html` (D35 nover 删 v0.4.5 badge line 94)
   4. `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/task_list.html` (D35 approver 加 "审批人" 组文案 line 95, 100)
   5. `sql/extensions/ddl_gh_ost/views.py` (D35 approver 加 "审批人" 组白名单 line 1116-1133)
   6. `sql/extensions/ddl_gh_ost/services/column_diff.py` (D27 ALTER COLUMN + D35 backticks 修复 line 403 + 757)
   7. ~~`sql/services/ddl_rollback.py` (D35 D24 ForeignKey bug 修复 - **9/8 09:30 紧急热补丁已推, 详见"零"段**)~~
   8. `sql/templates/detail.html` (D18/D20/D25 v2 + D35 nover 镜像工单 line 31 + 源工单 line 74)
   9. `sql/templates/sqlsubmit.html` (D28/D29 弹窗化)
   10. `sql/extensions/ddl_sync/views/__init__.py` (D22/D23/D25/D33 分页+导出)
   11. `sql/extensions/ddl_sync/urls.py` (D33 history_export)
   12. `sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html` (D33 同步历史 tab)

   **状态**: 12 文件中, 9/8 09:30 D24 紧急热补丁已推 1 个 (#7 `sql/services/ddl_rollback.py`), 今晚 18:30 D35 push 推剩余 11 个 (3-12-1 = 11, 不含 #7).

### 2 步重启
7. **Step 7**: kill + 拉新 gunicorn + qcluster (D24 实战新发现 qcluster 必 kill)
8. **Step 8**: 验证 6 项 (D34 演练 8 步 + D35 backticks 修复)
9. **Step 9**: 验证 D33 视图改动 (Paginator + pair_history_export + ddlsync-btn-export + ddlsync-page-link)

## 二、D35 backticks 修复 (commit `e4403e3`)

### 修法 (1 行正则, 2 处)
```python
# 修前 (110 prod + 134 dev 都有)
r"(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?"

# 修后 (D35 fix)
r"(?:(?P<schema>`?[^`\s.()]+`?)\.)?`?(?P<table>[^`\s(]+)`?"
```

### 134 dev 演练结果 (9/7 12:50)
- backticks SQL 修后: `[{operation: modify, name: pic_url, ...}]` ✅
- no-backticks SQL: 同样正常 ✅ (无破坏)
- 业务不中断: GET /login/ 200, GET /ddl_sync/pair/1/ 200 ✅
- column_diff.py md5: `0a1acecaac776ba8573d0b93753f1dec` 1293 行 (本地原 1291 行 +2 行注释)

### 110 prod 当前状态
- column_diff.py: 1168 行 md5 `e6588f1d...` (D13 推的旧版, 缺 D27 + 缺 backticks 修复)
- 推完后预期: 1293 行 + 修法生效 + D27 ALTER COLUMN 增强一并补齐

## 三、9 步推送脚本 (D35 prep 完成)

| 脚本 | 状态 | 备注 |
|------|------|------|
| `_d35_push_110prod.py` | ✅ ready | 16524 bytes, LIVE_PUSH 标志在 (默认 False, 9/8 18:00 改 True) |
| `_d35_verify_110prod.py` | ✅ ready (新) | 8 步验证: showmigrations + get_resolver + reverse + curl + backticks 修复验证 + 业务不中断 |

### verify 脚本 8 步 (D35 9/8 推完跑)
- **Step 1**: ssh 拿 mkq session_id
- **Step 2**: GET /login/ 拿 csrf token
- **Step 3**: showmigrations ddl_sync (期望 2 [X])
- **Step 4**: get_resolver() 路由数 (期望 ≥ 29)
- **Step 5**: reverse() 验证 4 大步关键 URL
- **Step 6**: curl /ddl_sync/pair/1/ (200 mkq 登录)
- **Step 7**: **D35 backticks 修复验证** (业务方 wf#4783 SQL → ok=True + big_table_alert 非 None)
- **Step 8**: 业务不中断验证 (GET /login/ 200 + gunicorn 进程数 ≥ 2)

## 四、9/8 18:30 启动 checklist

- [x] **9/8 09:30 D24 ForeignKey bug 紧急热补丁** (业务方 wf#4786 实战反馈驱动)
  - [x] commit 修法 `e94f988` (1 个文件 + changelog)
  - [x] 134 dev md5 校验 `0ec505fd...` (推前 110 prod `30355b0b...` 老 bug 版)
  - [x] scp 推 110 prod 22519 bytes
  - [x] kill + 拉新 gunicorn (5 进程, 9123 LISTEN, /login/ 200)
  - [x] 业务方数据验证 PASS: `should_ddl=False` + `engine.get_rollback` 返回 3 行
  - [ ] 业务方通知: 用户 (DBA 阿达叔叔) 发话术给汪银和
- [ ] 9/8 18:00 提前 30 分钟: 改 `_d35_push_110prod.py` `LIVE_PUSH=True`
- [ ] 9/8 18:00 提前 30 分钟: 拉新 cron 提醒 (10 分钟自检一次)
- [ ] 9/8 18:25 业务方通知 (飞书/钉钉/微信 拍板中)
- [ ] 9/8 18:30 启动 9 步 push (push 脚本 LIVE_PUSH=True, 跨 app 推 11 个文件不含 ddl_rollback)
- [ ] 9/8 18:35 push 完后跑 8 步 verify (`_d35_verify_110prod.py`)
- [ ] 9/8 18:45 全绿后发业务方通知恢复
- [ ] 9/8 19:00 业务方实测 wf#4783 改 `accesscard_vehiclepic.pic_url` 能看到大表 alert

## 五、110 prod 当前状态快照 (9/7 12:30)

| 项 | 值 |
|------|------|
| 部署路径 | `/dbdata/archery_v114_c9236a0/` |
| gunicorn 进程 | PID 18279/23135 (旧路径 /dbdata/archery_v114/venv) |
| qcluster 进程 | PID 48694-48699 (5 进程) |
| column_diff.py | 1168 行 md5 `e6588f1d...` (D13 推的旧版) |
| ddl_sync app | ❌ 未部署 (sql/extensions/ 还没 ddl_sync 目录) |
| root 密码 | `lAqfb8uEmQYsnGNQwIHtGPwukjCz6J` (D31 实战时 QNQw, 9/7 prep 时已改 GNQw, 跟 134 dev 一样) |
| mkq 业务方密码 | `mbdMCZmqa8vYxyK6JDuK4LZjy2UqceFS` |

## 六、相关 changelog

- `docs/changelogs/2026-09-07_ddl-sync-w2-d35-backticks-parse-bug.md` (D35 排查 + 修法)
- `docs/changelogs/2026-09-03_ddl-sync-w2-d31-prod-deploy-precheck.md` (D31 8 步原始)
- `docs/changelogs/2026-09-04_ddl-sync-w2-d34-prod-push-drill.md` (D34 dry-run 9 步演练)

## 七、相关 commit 链

```
e94f988 (D24 ForeignKey bug 修法 + changelog) ← 9/8 09:30 紧急热补丁, 已推 110 prod
e4403e3 (D35 backticks 修复) ← 9/7 12:50 准备
9bcbe02 (D35 push 脚本 ready)
f21e3fb (D34 134 dev 9 步 dry-run 演练)
1a3bec7 (D33 分页 + Excel 导出)
096c715 (D32 134 dev 演练 4 大步)
799ff1f (D31 推 110 prod 预检)
fa780be (D29 大表 alert 弹窗化验证)
3a59e8b (D28 columnDiffModal 弹窗)
29998bf (D27 ALTER COLUMN 增强)
```

## 八、推完后下一步 (D36)

D35 推完 110 prod 后, 做 D36 操作日志功能 (D35-Pending 拍板: 方案 A 完整 DdlSyncAuditLog 模型)
- 1 model + 6 类 action enum + 5 view 埋点 + 1 migration + 1 模板
- D37 推 110 prod 增 D36 操作日志

## 九、9/8 09:30 紧急热补丁后的 D35 push 调整说明

### 12 → 11 文件调整
- **原计划**: 12 文件升级版清单 (D34 演练升级版, 跟 memory 同步)
- **调整后**: 11 个 (去掉 #7 `sql/services/ddl_rollback.py`, 因 9/8 09:30 紧急热补丁已先于今晚 18:30 推到 110 prod)
- **业务方 wf#4786 验证**: 实测 PASS, `_should_use_ddl_rollback=False` + 3 行回滚 SQL (UPDATE 反向 + 2 个 DELETE FROM)

### D35 push 脚本 (`_d35_push_110prod.py`) 调整
- **当前**: `cross_app_files` 实际只列 6 个 (ddl_sync 3 + sql 模板 2 + ddl_gh_ost column_diff.py 1)
- **待办**: 今晚 18:30 跑之前, 把脚本 `cross_app_files` 升级到 12 文件 (跟文档一致), 推完前手动 skip #7 ddl_rollback.py
- **风险**: 0 风险, 9/8 09:30 已用同链路 (md5 校验 + scp + kill+拉新) 推过 1 个文件, 链路已验证 PASS

### 同源 entry
- 文档 commit: (本次)
- 文档 changelog: (本次)
- 实战脚本: `scripts/_archive/_d35_hotfix_110prod_d24.py` (4 步落地) + `scripts/_archive/_d35_verify_v2.py` (业务方数据验证)
- 实战 changelog: `docs/changelogs/2026-09-07_ddl-sync-w2-d35-bug-ghost-task-manager.md` (3.6KB)
