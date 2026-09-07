# D35 实战推 110 prod 完整计划 (9/8 18:30 启动)

> **状态**: ✅ 准备就绪 (9/7 12:50 完成 prep)
> **启动时间**: 2026-09-08 18:30 (距今 30 小时)
> **提前 30 分钟**: 9/8 18:00 改 `LIVE_PUSH=True` + 拉新 cron 提醒
> **业务方通知**: ⏰ 待用户拍板渠道 (飞书/钉钉/微信)

## 一、本次推送范围 (9 步 runbook)

### 4 大步 (Django app 部署)
1. **Step 1**: copy 整个 `sql/extensions/ddl_sync/` 目录 (53+ 文件)
2. **Step 2**: `archery/settings.py` 加 `INSTALLED_APPS += ("sql.extensions.ddl_sync.apps.DdlSyncConfig",)`
3. **Step 3**: `archery/urls.py` 加 `path("ddl_sync/", include(("sql.extensions.ddl_sync.urls", "ddl_sync"), namespace="ddl_sync"))`
4. **Step 4**: `common/templates/base.html` 加 ddl_sync menu (带 `{% if perms.ddl_sync.view_ddlsyncpair %}` 守卫)

### 1 步数据库
5. **Step 5**: `cd /dbdata/archery_v114_c9236a0 && sudo -u archery venv/bin/python manage.py migrate ddl_sync`

### 1 步跨 app 文件 (Step 6: 6 文件)
6. **Step 6**: 推跨 app 6 文件:
   - `sql/templates/detail.html` (D18/D20/D25 v2)
   - `sql/templates/sqlsubmit.html` (D28/D29 弹窗化)
   - **`sql/extensions/ddl_gh_ost/services/column_diff.py` (D27 ALTER COLUMN + D35 backticks 修复 — 新增!)**
   - `sql/extensions/ddl_sync/views/__init__.py` (D22/D23/D25/D33 分页+导出)
   - `sql/extensions/ddl_sync/urls.py` (D33 history_export)
   - `sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html` (D33 同步历史 tab)

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

- [ ] 9/8 18:00 提前 30 分钟: 改 `_d35_push_110prod.py` `LIVE_PUSH=True`
- [ ] 9/8 18:00 提前 30 分钟: 拉新 cron 提醒 (10 分钟自检一次)
- [ ] 9/8 18:25 业务方通知 (飞书/钉钉/微信 拍板中)
- [ ] 9/8 18:30 启动 9 步 push (push 脚本 LIVE_PUSH=True)
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
e4403e3 (D35 backticks 修复) ← 新 (commit + push 完成)
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
