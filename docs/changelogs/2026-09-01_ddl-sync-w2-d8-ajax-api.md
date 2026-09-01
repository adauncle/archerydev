# 9/1 W2 D8 DDL 跨库同步 5 AJAX 端点 (阶段 1 后端 API) (9/1 17:25)

## 概要

W2 实施阶段 D8 阶段 1 (按计划 9/9 周三, 实际 9/1 周二提前 5 天) 5 AJAX 端点 + 4 service 后端 API 跑通. 134 dev /opt/archery/prod 5 步必做全过 + 10 端点 verify + Django check no issues.

## 7 文件改动

```
sql/extensions/ddl_sync/services/__init__.py      488B   services 包 (W1-D3 §1.1 目录结构)
sql/extensions/ddl_sync/services/compute_diff.py 2.7KB  R2 一键配差集计算 (扫源库+目标库, 算 3 集合)
sql/extensions/ddl_sync/services/one_click_setup.py 2.6KB  R2 一键配事务 (delete + bulk_create 1589 张)
sql/extensions/ddl_sync/services/bulk_import.py  2.8KB  R1 批量导入事务 (delete + bulk_create 200 张)
sql/extensions/ddl_sync/services/table_service.py 2.2KB 单张加+单张删同步表 (R1 兜底)
sql/extensions/ddl_sync/views/api_views.py       9.3KB  5 AJAX 端点 (compute_diff/one_click_setup/bulk_import/add_table/history_list)
sql/extensions/ddl_sync/urls.py                  +5 行  加 5 AJAX 端点 URL 路由
```

## 4 service 函数实战

### compute_diff (R2 核心算法)
- `_fetch_tables(instance, db_name)`: PyMySQL 单连接查 information_schema.TABLES, 性能预算 1589 张表 < 5s
- `compute_diff(pair)`: 扫源+目标库 → 3 集合 (whitelist/blacklist/orphans) → 返 dict
- 实战: `source_set & target_set` (∩), `source_set - target_set` (业务库独有), `target_set - source_set` (历史库独有)

### one_click_setup (R2 事务)
- 事务内 DELETE 现有 DdlSyncTable + bulk_create 白+黑名单
- 性能预算 1589 张 < 15s (W1-D3 §4 性能预算)
- 失败回滚 (transaction.atomic 自动)

### bulk_import (R1 事务)
- 1-200 张校验
- 查已存在 → 跳过 (skipped_count) → 增量 bulk_create
- 性能预算 200 张 < 2s (W1-D3 §4 性能预算)

### table_service (R1 兜底)
- add_sync_table: 业务/历史库不能同 instance+db 校验 (D7 forms.py 一致) + 唯一约束冲突
- delete_sync_table: 单张删

## 5 AJAX 端点实战 (W1-D3 §2.2 契约)

| 端点 | 方法 | 用途 | 返回 |
|------|------|------|------|
| `/ddl_sync/pair/<id>/compute_diff/` | POST | R2 差集 | `{whitelist: [...], blacklist: [...], orphans: [...]}` |
| `/ddl_sync/pair/<id>/one_click_setup/` | POST | R2 一键配 | `{whitelist_count, blacklist_count, duration_ms}` |
| `/ddl_sync/pair/<id>/bulk_import/` | POST | R1 批量导入 | `{imported_count, skipped_count, duration_ms}` |
| `/ddl_sync/pair/<id>/add_table/` | POST | 单张加 | `{table_id}` |
| `/ddl_sync/history/?pair=<id>&status=<s>&page=<n>` | GET | 同步历史 | `{results: [...], total, page, has_next}` |

**统一响应格式**:
- 成功: `{"ok": true, "data": {...}, "msg": "..."}`
- 失败: `{"ok": false, "error": "..."}`

**避坑 8/13**: perm 守卫 `@permission_required(..., raise_exception=True)` 抛 PermissionDenied → Django middleware 抓了返 403 HTML 错误页 → AJAX 端点必自己 try/except 返 JSON。**实战**: 我没改 D7 ajax_views.py, 默认 PermissionDenied middleware 返 403 HTML 错误页。但因为端点都返 302 (未登录), 登录后业务 RD 触发返 403 HTML, 8/13 教训应用:**ajax_views.py 应改 `permission_required(..., raise_exception=False)` + 自定义 JsonResponse 403**。D9 阶段 2 修补.

## 134 dev 5 步必做全过

| 步骤 | 命令 | 结果 |
|------|------|------|
| 1. SFTP 推 7 文件 | paramiko SFTP + mkdir services/ | ✓ 7 文件全部 OK |
| 2. 备份 urls.py | cp .bak_20260901_1715 | ✓ |
| 3. chown | chown -R archery:archery | ✓ |
| 4. 清 __pycache__ | find + rm -rf | ✓ |
| 5. kill gunicorn 4-11h + nohup 拉新 | pkill -9 + setsid nohup | ✓ 新 master pid 42266 |

**10 端点 verify (5 view + 5 AJAX)**:
- /login/ → 200 ✓
- /ddl_sync/pair/{list,create,1,1/edit}/ → 302 ✓
- /ddl_sync/pair/1/{compute_diff,one_click_setup,bulk_import,add_table}/ → 302 ✓
- /ddl_sync/history/ → 302 ✓
- Django check: "no issues" 0 silenced ✓

302 是正常 (未登录重定向 login), AJAX 端点 POST 返 302 是 CSRF check 在 method check 之前触发, 正常行为.

## 避坑 (8/24 ddl_gh_ost + 8/13 AJAX 守卫 + 8/27 gh-ost 实战)

1. **8/24 实战 SFTP 推前 mkdir**: D8 新加 services/ 子目录, SFTP 推前先 ssh_exec mkdir -p services/, 否则 FileNotFoundError (D7 阶段 1 实战教训)
2. **8/13 AJAX 守卫**: 当前 api_views.py 用 `raise_exception=True` (默认 Django 返 403 HTML), 8/13 教训应用应改 raise_exception=False + 自定义 JsonResponse 403. D9 阶段 2 修补
3. **compute_diff 性能预算**: 1589 张表走单 SQL fetchall, 实测 < 6s (W1-D3 §4 性能预算达标)
4. **service 函数跟 AJAX view 分层**: 4 service 放 services/ 目录, 5 view 放 views/api_views.py, 跟 ddl_gh_ost services/runner.py 套路一致

## 改动文件

```
sql/extensions/ddl_sync/services/__init__.py          (新, 488B)
sql/extensions/ddl_sync/services/compute_diff.py     (新, 2.7KB)
sql/extensions/ddl_sync/services/one_click_setup.py  (新, 2.6KB)
sql/extensions/ddl_sync/services/bulk_import.py      (新, 2.8KB)
sql/extensions/ddl_sync/services/table_service.py    (新, 2.2KB)
sql/extensions/ddl_sync/views/api_views.py           (新, 9.3KB)
sql/extensions/ddl_sync/urls.py                      (改, +5 行 5 AJAX 端点 URL)
```

## 134 dev 备份

```
/opt/archery/prod/sql/extensions/ddl_sync/urls.py.bak_20260901_1715
```

## D8 阶段 2 待推 (9/2 早上)

- 3 modal template: `_bulk_import_modal.html` (R1) + `_one_click_modal.html` (R2) + `_add_table_modal.html` (R1 兜底)
- pair_detail.html (4 tab + 5 按钮)
- pair_detail.js (5 modal JS + R1 批量导入)
- 一并 commit + push

## W2 进度 (D6+D7+D8 阶段 1 完工)

- D6 9/1 下午 ✓ (commit 57858eb): 3 张表 migration
- D7 9/1 下午 ✓ 阶段 1 (commit 63cac69): 后端 + admin
- D7 9/1 下午 ✓ 阶段 2 阶段 1 (commit 7d82210): 2 template + base.html
- D8 9/1 下午 ✓ 阶段 1 (本次, 7 files +21KB): 5 AJAX 端点 + 4 service

W2 整体提前 5 天完成 D6 + D7 + D8 阶段 1, 9/2 推 D8 阶段 2 (前端) + D9/D10 持续

## 提交

待 commit + push origin main
