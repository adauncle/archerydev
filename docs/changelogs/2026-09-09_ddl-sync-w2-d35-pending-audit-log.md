# D35-Pending 操作日志功能上线 (2026-09-09 18:40)

## 业务方反馈 / 拍板
- 9/4 17:28 D35-Pending 拍板方案 A 完整 DdlSyncAuditLog 模型 (W2 期间一直挂账)
- 关联: `docs/plans/2026-09-04_ddl-sync-w2-d35-pending-audit-log.md`
- 9/9 18:00 DBA 拍板开始实施 (DBA 拍板 W2 收尾 P0 任务)

## 业务背景
- W1 D8 阶段 2 写 `pair_detail.html` "操作日志" tab 时留了占位符 ("D9 阶段 2 上线")
- W1 D9 阶段 2 没真做 (精力在 5 AJAX + signal + perm guard)
- W2 D22-D34 期间也没补, 一直挂着
- D7 阶段 1 设计的 `pair_toggle` (启用/禁用) 端点**一直没实现** (urls.py line 11 注释但没 path, views 里没 def)
  - 业务方启用/禁用实际走 `pair_edit` 改 `enabled` 字段

## 修法
D35-Pending 拍板方案 A 完整实施: 1 model + 1 migration + 5 view 埋点 + 1 模板 + 1 CSS 样式

### 1. 新增 DdlSyncAuditLog 模型 (db_table=ext_ddl_sync_audit_log)
- 7 字段: id / pair (FK PROTECT) / action (6 enum) / operator (FK SET_NULL) / operator_display / detail_json / created_at
- 6 类 action enum: `create` / `edit` / `enable` / `disable` / `one_click` / `bulk_import`
- 2 索引: `pair + -created_at` + `pair + action + -created_at`

### 2. Migration 0003_ddlsyncauditlog
- 134 dev 跑 `python manage.py makemigrations ddl_sync` 自动生成
- `python manage.py migrate` 创建表 + 4 个 perm (add/change/delete/view)

### 3. 5 view 埋点 emit 6 类 action
| view | action | 触发条件 |
|------|--------|----------|
| `views.pair_create` | `create` | 成功创建后 |
| `views.pair_edit` | `enable` | 仅 `enabled` 字段变化 (False→True) |
| `views.pair_edit` | `disable` | 仅 `enabled` 字段变化 (True→False) |
| `views.pair_edit` | `edit` | 其他字段变化 (e.g. `sync_mode` 改, 但 enabled 没变) |
| `api_views.one_click_setup_view` | `one_click` | 成功返回前 |
| `api_views.bulk_import_view` | `bulk_import` | 成功返回前 |

设计说明: 用 `pair_edit` 检测 `enabled` 字段变化区分 `enable` / `disable` / `edit`, 不需要新建 `pair_toggle` 端点 (D7 阶段 1 设计遗漏, 但 pair_edit 已能完成所有编辑功能)

公共 helper `_write_audit_log(pair, action, operator, detail)` 在 `views/__init__.py` + `views/api_views.py` 各一份, 失败不抛异常 (跟 D22 sync_trigger 错误兜底同套路)

### 4. 改 pair_detail.html "操作日志" tab 模板
- 原来: 占位符 `<div class="ddlsync-empty">D9 阶段 2 上线...</div>`
- 现在: 5 列表格 (ID / 操作类型 / 操作人 / 详情 / 操作时间) + 分页 (每页 20 条, 跟 history 一致)
- 6 类 action 用 6 种 CSS 颜色区分: 蓝(create)/灰(edit)/绿(enable)/红(disable)/紫(one_click)/橙(bulk_import)

### 5. 改 view `pair_detail` 传 context
- `audit_logs` / `audit_logs_count` / `audit_logs_page_obj` / `audit_logs_paginator`
- `LOGS_PER_PAGE = 20` (跟 history 一致)
- `select_related("operator")` 避免 N+1

## 演练 PASS (134 dev force_login archery superuser, 18:38-18:40)

### 演练 1: 6 类操作各 1 次
```
[1] create       archery 18:38:45 {"name": "D35-OpLog-测试A", "sync_mode": "blacklist", "enabled": true}
[2] edit         archery 18:38:45 {"changed_fields": ["sync_mode"], "enabled": null}
[3] disable      archery 18:38:45 {"from": true, "to": false}
[4] enable       archery 18:38:45 {"from": false, "to": true}
[5] one_click    archery 18:38:45 {"whitelist_count": 2, "blacklist_count": 1, "duration_ms": 4, ...}
[6] bulk_import  archery 18:38:45 {"imported_count": 2, "skipped_count": 0, "duration_ms": 3, ...}
```
- 6 类 action 各 1 条 ✅
- 详情 JSON 完整 ✅

### 演练 2: pair_detail.html "操作日志" tab 渲染
- pair_detail HTTP 200, size 59940
- tab-logs 块长度 3501 字符
- 6 类 action 全部含 `ddlsync-action-{action}` CSS class ✅
- 6 个中文 display 全部含 (创建库对/编辑库对/启用库对/禁用库对/一键配置/批量导入) ✅

### 演练 3: 边界 case (同时改 enabled + sync_mode)
- 改 sync_mode + enabled 保持 → 走 `edit` (不误判 enable) ✅
- 仅改 enabled True→False → 走 `disable` ✅

## 改动 4 个文件
1. `sql/extensions/ddl_sync/models.py` (新增 DdlSyncAuditLog 类 + import settings) (+74 行)
2. `sql/extensions/ddl_sync/migrations/0003_ddlsyncauditlog.py` (新, 134 dev makemigrations 生成, 拉回本地)
3. `sql/extensions/ddl_sync/views/__init__.py` (新增 _write_audit_log helper + 改 pair_create/pair_edit 埋点 + 改 pair_detail 传 context) (+85 行)
4. `sql/extensions/ddl_sync/views/api_views.py` (新增 _write_audit_log helper + 改 one_click_setup/bulk_import 埋点) (+50 行)
5. `sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html` (改 "操作日志" tab 占位符 → 真渲染 + 分页 + 加 6 颜色 CSS) (+60 行)

## 部署 (待做)
- 4 文件 scp 推 110 prod (md5 比对必覆盖全部 sql/extensions/ddl_sync/ 文件, D38 续 7 实战新发现)
- 110 prod 跑 `python manage.py migrate ddl_sync` (创建 ext_ddl_sync_audit_log 表)
- 110 prod gunicorn pkill + setsid nohup 重启
- 演练 force_login mkq (DBA 执行组) 走 5 view + 验证 audit_logs (跨项目可复用 D38 续 4 实战新发现)
- 演练 wf#4791 老工单 + 新工单两边 (D38 续 8 实战新发现)
- 业务方硬刷 (Ctrl+Shift+R) pair_detail.html

## 实战新发现 (跨项目可复用, 2 条)
1. **D35-Pending 拍板方案 A 完整 DdlSyncAuditLog 干净独立** (D35-OpLog 实战新发现) - 用 `pair_edit` 检测 `enabled` 字段变化区分 `enable` / `disable` / `edit`, 不需要新建 `pair_toggle` 端点 (D7 阶段 1 设计遗漏但 pair_edit 已能完成所有编辑). 跨项目做"操作日志"功能, 优先用 1 个 helper 函数 + 5 view 埋点, 不要新建一堆端点
2. **D7 阶段 1 设计遗漏 pair_toggle 端点 (urls.py line 11 注释但没 path)** (D35-OpLog 实战新发现) - 拍板"启用/禁用"功能时, 实际业务方走 `pair_edit` 改 enabled 字段也能 work, 但设计文档有遗漏. 跨项目设计 CRUD 时, 必先 `git grep` 实际实现的端点, 跟设计文档对比, 漏的补上或明确"走 edit"

## W2 状态
D6 → ... → D38 续 10 → **D35-Pending 操作日志功能上线 (P0, 18:40)**

## 后续挂账
- 推 110 prod (D38 续 7 实战新发现: 必列推送清单 + 三环境 md5 + 演练老工单新工单两边)
- 历史 audit_log 数据补录 (D35-Pending 拍板文档说"历史数据需 DBA 手工补录", 暂缓, 业务方当前不需要)
