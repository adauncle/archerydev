# W2 D9 阶段 1: R3 走当前配置 + workflow_passed_handler signal (commit pending)

> **时间**: 2026-09-01 18:00
> **范围**: `services/sync_trigger.py` + `apps.py` 改 ready() 注册 signal
> **环境**: 134 dev 演练环境跑通, 12 端点 verify + signal 注册验证 + 5 case `_extract_table_name` 全过
> **设计稿**: `docs/designs/2026-09-01_ddl-sync-implementation-design.md` §5.1

## 改动文件 (2 个, 11.6KB)

| 文件 | 大小 | 作用 |
|------|------|------|
| `services/sync_trigger.py` | 10.7KB | R3 镜像工单 + workflow_passed_handler signal + 3 辅助函数 |
| `apps.py` | 663B (改 1 行) | `ready()` 钩子 import sync_trigger, 触发 @receiver 装饰器执行 |

## R3 核心 (sync_trigger.py)

### 4 函数实战

| 函数 | 作用 | 实战要点 |
|------|------|---------|
| `create_target_workflow(source, pair, transformed_ddl)` | 创建镜像工单 + SqlWorkflowContent + 走 audit_handler.create_audit() 自动配 | group_id/name 跟 source 同 (业务组审完镜像工单在同组继续走); `audit_auth_groups=""` 占位后被 audit_handler 覆盖 |
| `workflow_passed_handler(sender, instance, created, **kwargs)` | post_save signal handler | 整个 try/except 兜底 (W1-D3 §9.3 实战 1), 异常不能阻塞业务库 DDL 主流程 |
| `_extract_table_name(sql_content)` | 解析 ALTER TABLE 提表名 | 5 case 全过: `accesscard_black_detail` / `hly_doc.foo`→`foo` / 空 / CREATE TABLE 不识别 / 带 schema 跟表名 |
| `_should_sync(pair, table_name)` | 白/黑名单判定 | sync_mode=blacklist (默认 R1): 在黑名单=排除; sync_mode=whitelist: 在白名单=同步 |
| `_apply_transform_rule(sql_content, pair, table_name)` | 转换 DDL (Phase 3) | 暂时原样返回 (DBA 还在配过滤规则) |

### Signal handler 业务流

```
业务库 SqlWorkflow.status = 'workflow_review_pass' (audit PASSED)
  → post_save signal 触发 workflow_passed_handler
  → 找匹配库对 (source_instance + source_db + enabled=True)
  → 提取 table_name from sql_content
  → _should_sync() 白/黑名单判定
    ├─ 不匹配 → history sync_status="skipped" + error_message="orphan"
    └─ 匹配 → _apply_transform_rule() 转换 DDL
       → create_target_workflow() 创建历史库镜像工单 + audit_handler.create_audit() 走 audit_setting
         ├─ 失败 → history sync_status="failed" + error_message=...
         └─ 成功 → history sync_status="syncing" (等 target_workflow 执行完切 synced/failed)
```

### 实战修正 (W1-D3 §5.1 跟 Archery 上游对齐)

1. **group_id/name 跟 source_workflow 同** — W1-D3 §5.1 写 `pair.target_instance.group_id` 错 (Instance 是 ManyToMany ResourceGroup, 没 group_id 字段), 实战改用 source_workflow 的, 业务组审完镜像工单在同组继续走
2. **audit_handler.create_audit() 必调** — W1-D3 §5.1 写 `audit_auth_groups=""` 占位, 但 Archery 上游走 audit_setting 才能从 WorkflowAuditSetting 拿当前配置, 实战必调 get_auditor().create_audit() 自动配
3. **SqlWorkflowContent 必建** — sql_content 关联是 OneToOne, W1-D3 §5.1 没写, 实战必建否则 detail 页面 sql_content 报 DoesNotExist
4. **status 默认 `workflow_manreviewing`** — W1-D3 §5.2 拍板: 镜像工单不自动跑, 走人工审核兜底, DBA 手动审 + 手动执行

## apps.py ready() 钩子

```python
## CUSTOM-MODIFIED: v0.5.0-alpha R3 注册 workflow_passed_handler signal @ 2026-09-01 @ mavis
def ready(self):
    # 9/1 W1-D3 §5.1 拍板: 业务库 SqlWorkflow 状态变 PASSED → 触发同步
    from .services import sync_trigger  # noqa: F401
```

实战要点 (9/1 D8 阶段 2 实战 1 复用):
- 134 dev 跑完 `manage.py check ddl_sync` + gunicorn restart, signal 真的注册
- 验 `post_save.receivers` 列表里有 `workflow_passed_handler` (用 weakref dereference 验)
- 验 DdlSyncConfig.ready() 强制调 no exception

## 134 dev 验证 (5 项全过)

| 验证项 | 结果 | 备注 |
|--------|------|------|
| sync_trigger 5 函数 import | OK | django.setup() + 5 函数全 import |
| `_extract_table_name` 5 case | OK | `accesscard_black_detail` / `hly_doc.foo`→`foo` / 空 / CREATE TABLE / `hly_activity.log_2024`→`log_2024` |
| signal 注册 | True | `workflow_passed_handler in post_save.receivers: True` |
| 12 端点 verify | OK | /login/=200 + 4 view 端点=302 + 5 AJAX 端点=302 + /static/ddl_sync/pair_detail.js=200 |
| Django check | OK | "no issues" 0 silenced |

## 避坑 (跨项目可复用)

1. **signal handler 整个 try/except 兜底** — W1-D3 §9.3 实战 1: 异常不能阻塞业务库 DDL 主流程. 实战必用 try/except 包围整个 handler, 捕获后 logger.exception 不 raise
2. **apps.ready() 必 import sync_trigger** — Django AppConfig 的 ready() 是触发 @receiver 装饰器执行的钩子, 必 import 才能让 signal 注册
3. **post_save.receivers 是 weakref** — 验 signal 注册时, receiver 是 `weakref` 不是 function 本身, 必 `recv_ref()` dereference 才能拿真函数. 实战 9/1 第一次验 receivers 返 False 是因为 callable(weakref) True 但 weakref.__name__ 是 None, 实战用 `if hasattr(recv_ref, '__call__') and not hasattr(recv_ref, '__name__'): recv = recv_ref()` 判别
4. **group_id 不能从 instance 拿** — Archery Instance 是 ManyToMany ResourceGroup, 没 group_id 字段. R3 镜像工单实战用 source_workflow 的 group_id/name, 业务组审完镜像工单在同组继续走
5. **SqlWorkflowContent OneToOne 必建** — sql_content 在 SqlWorkflowContent 表 (OneToOne 关联), 创建 SqlWorkflow 后必建 SqlWorkflowContent, 不建 detail 页面报 DoesNotExist
6. **audit_handler.create_audit() 必调** — `audit_auth_groups=""` 占位不够, Archery 上游走 audit_setting 才能从 WorkflowAuditSetting 拿当前配置, 实战必 `get_auditor(workflow=target_workflow).create_audit()` 自动配
7. **bash 嵌套 -c 引号又是坑 (9/1 D8 阶段 2 实战 1 复用)** — Python `python -c "..."` 嵌套引号, 实战用 here-doc 写测试文件 + `manage.py shell < file.py` 走 Django 完整 setup, 避开引号问题

## 下一步 (9/2 早上 D9 阶段 2)

- **8/13 教训应用修补**: api_views.py 5 个 `@permission_required(..., raise_exception=True)` → 改 `raise_exception=False` + 自定义 `require_perm` 装饰器 (W1-D3 §7.3) 返 JsonResponse({"ok": False, "error": "权限不足"}, status=403)
- 创建 `services/perm_guard.py` 抽出装饰器
- 修补后 12 端点 + 403 JSON 验证 (curl 测 403 返 JSON 不返 HTML 8/13 教训)
- 推 commit + push origin main

## W2 进度 (9/1 一天 7 commit + 6 大任务全部完工, 提前 5 天)

| 任务 | commit | 状态 |
|------|--------|------|
| D6 数据模型 migration | 57858eb | ✓ |
| D7 后端 + admin + templates | 63cac69 / 7d82210 | ✓ |
| D8 5 AJAX 端点 + 4 service | 5e78ccf | ✓ |
| D8 5 前端文件 | a792cdf | ✓ |
| **D9 R3 + signal handler** | **本次 commit** | **✓** |
| D9 8/13 教训应用修补 | 待推 | pending |
| D10 134 dev 端到端演练 5 Case | 待推 | pending |
