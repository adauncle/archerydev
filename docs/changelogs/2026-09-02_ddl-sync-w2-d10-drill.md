# W2 D10: 134 dev 端到端演练 5 Case (commit pending) + hotfix UnboundLocalError

> **时间**: 2026-09-02 10:30
> **范围**: `services/sync_trigger.py` hotfix (D10 Case C 实战发现 UnboundLocalError) + 5 Case 演练报告
> **环境**: 134 dev 演练环境跑通, 5 Case ALL PASS
> **设计稿**: `docs/plans/2026-09-04_ddl-sync-drill-and-push-manual.md` (W1-D5)

## 5 Case 演练结果

| Case | 内容 | 结果 | 关键数据 |
|------|------|------|---------|
| A | 配 1 个真实库对 (hly_accesscard → archery_dev) | **PASS** | 库对 id=1, 业务/历史库不能同 instance+db 校验生效 |
| B | 一键配 5 张 whitelist | **PASS** | compute_diff 5+0+2 正确 (whitelist 5 + blacklist 0 + orphans 2), one_click_setup 5ms 完成 |
| C | 业务 RD 提 ALTER TABLE 触发 R3 signal | **PASS** | workflow 106+107, DdlSyncHistory syncing, 镜像工单走 audit_setting fallback (group_id=8 没配审流 → 留空兜底) |
| D | blacklist 跳过 (DBA 显式排除) → skipped | **PASS** | DdlSyncHistory id=2 sync_status=skipped + target_workflow=None + finished_at 写入 |
| E | 4 perm 4 角色权限验证 | **PASS** | 业务 RD 403+JSON / DBA 执行 view+change 200 / DBA 组长 全 200 / superuser 200 |

## D10 Case C 实战发现 bug + hotfix

**症状**: `_should_sync()` 报 `UnboundLocalError: cannot access local variable 'DdlSyncTable' where it is not associated with a value`

**根因** (9/2 10:20 实战):
```python
def _should_sync(pair: DdlSyncPair, table_name: str) -> bool:
    if not table_name:
        return False
    existing = DdlSyncTable  # 避免循环 import  ← Python 编译器认为 DdlSyncTable 是 local var
    from ..models import DdlSyncTable  # 实际 import 不生效, 因为 DdlSyncTable 已被标记为 local
    ...
```

Python 闭包坑: 函数体内任何位置给 `DdlSyncTable` 赋值 (`existing = DdlSyncTable`) 都会让 Python 编译器把 `DdlSyncTable` 整个函数体标记为 local variable, 导致 `from ..models import DdlSyncTable` 不会把名字绑到 local scope, 后续 `DdlSyncTable` 都是 unbound local。

**修法** (W1-D3 §9.3 实战 1 兜底救了一次, 业务库 DDL 主流程没崩):
```python
def _should_sync(pair: DdlSyncPair, table_name: str) -> bool:
    from ..models import DdlSyncTable  # 函数顶部直接 import, 不要赋值
    if not table_name:
        return False
    ...
```

实战 hotfix 推 134 dev + gunicorn restart (pid 30663 + 4 worker) 修后 _should_sync 正常工作。

## 演练数据准备

- 在 hly_accesscard 业务库造 5 张表 (跟 archery_dev 7 张表里重叠 5 张)
  - accesscard_account / accesscard_black_detail / accesscard_groupuser / accesscard_test_diff / accesscard_test_rollback
- archery_dev 演练库 7 张表
- 2 张 target 独有 (accesscard_black_detail_test / accesscard_black_detail_test2)
- source: hly_accesscard 5 张 → target: archery_dev 7 张

## 134 dev 验证 (5 Case 全部 PASS)

### Case A 配库对
```
1. created_by: archery
2. instance: archery 172.20.2.134:3306
4. 库对创建: id=1 name=accesscard 库对 (134 dev 演练)
   source: archery/hly_accesscard
   target: archery/archery_dev
   sync_mode=blacklist enabled=True
--- Case A 验证 ---
  库对总数: 1
  pair.id: 1
--- Case A forms 校验 ---
  校验失败 (期望): 业务库跟历史库不能是同一个 instance + 同一个 db
```

### Case B 一键配
```
--- 1. compute_diff 差集 ---
  耗时: 5ms
  whitelist (源+目标都有的): ['accesscard_account', 'accesscard_black_detail', 'accesscard_groupuser', 'accesscard_test_diff', 'accesscard_test_rollback']
  blacklist (源独有): []
  orphans (目标独有): ['accesscard_black_detail_test', 'accesscard_black_detail_test2']
--- 2. one_click_setup bulk_create ---
  耗时: 5ms
  whitelist_count: 5
  blacklist_count: 0
--- 4. 5 张表匹配验证 ---
  匹配: True
```

### Case C 业务 RD 提 DDL 触发 R3 signal (hotfix 后)
```
1. group_id=8 group_name=pod core for archery
2. 模拟业务 RD 提工单 ALTER TABLE accesscard_account ADD COLUMN phone VARCHAR(20)
   workflow.id=106 status=workflow_manreviewing
3. 模拟 passed() 走完 audit.id=4695 current_status=1
   workflow.status now: workflow_review_pass
4. 验证 DdlSyncHistory 写入:
   history.id=1
     pair: accesscard 库对 (134 dev 演练) (#1)
     source_workflow: #106
     target_workflow: #107
     table_name: accesscard_account
     sync_status: syncing
     ddl_text: ALTER TABLE accesscard_account ADD COLUMN phone VARCHAR(20)...
     transformed_ddl_text: ALTER TABLE accesscard_account ADD COLUMN phone VARCHAR(20)...
   镜像工单: id=107 name=[镜像] [Case C 演练] accesscard_account 加 phone 字段
     instance: archery db=archery_dev
     group: pod core for archery
     status: workflow_manreviewing
     audit_auth_groups: (留空, audit_setting fallback)
```

### Case D blacklist 跳过
```
1. 配 blacklist: accesscard_test_diff (DBA 显式排除)
2. 业务 RD 提工单: id=108 SQL=ALTER TABLE accesscard_test_diff ADD COLUMN blocked_field
4. 验证 DdlSyncHistory skipped:
   history.id=2
     pair: #1
     source_workflow: #108
     target_workflow: None (skipped 不创建镜像工单)
     table_name: accesscard_test_diff
     sync_status: skipped
     error_message: 白/黑名单不匹配 (orphan)
     finished_at: 2026-09-02 10:24:58.218919
5. hly_accesscard.accesscard_test_diff 字段 (期望无 blocked_field): False
```

### Case E 4 perm 4 角色
```
业务 RD (无 ddl_sync perm): status=403 content_type=application/json
  body: {"ok": false, "error": "权限不足: 需要 ddl_sync.change_ddlsyncpair"}
DBA 执行 (view+change): status=200
DBA 组长 (全 DdlSyncPair perm): status=200
superuser (archery): status=200
--- 3. 4 角色 期望判定 --- ALL PASS
--- 5. require_perm add_ddlsynctable 守卫 (DBA 执行无 add perm) ---
  status=403 (DBA 执行只有 DdlSyncPair perm 没 DdlSyncTable perm, 实战要配齐两套)
```

## 避坑 (跨项目可复用, 9/2 D10 实战总结 5 条)

1. **Python 闭包 UnboundLocalError**: 函数体内不要先 `existing = SomeName` 再 `from ... import SomeName`, Python 编译器会认为 SomeName 是 local var, import 不会写到 local scope. 必用"import 在函数顶部"或"lazy import 在用的时候"
2. **W1-D3 §9.3 实战 1 兜底救命**: signal handler 整个 try/except, UnboundLocalError 触发时业务库 DDL 主流程**没崩**, logger.exception 记了 + 业务库工单正常 execute. 这是 9/1 演练 W1-D3 §9.3 实战 1 设计兜底, 实战证明了
3. **MySQL audit_setting 没配 fallback**: 镜像工单 group_id=8 没配 WorkflowAuditSetting, audit_handler.create_audit() 抛 `审批类型 SQL上线申请 未配置审流`, 实战 W1-D3 §5.1 fallback 留空 audit_auth_groups, 等 DBA 兜底配
4. **业务 RD 默认有 sql.* perm**: Archery 134 dev 业务 RD 默认 is_staff=True 有 sql.* 各种 menu perm, 但**没** ddl_sync.* perm, 实战 8/13 教训验证 403 + JSON 完美
5. **DBA 角色要配齐 2 套 perm**: DdlSyncPair (view/add/change/delete) + DdlSyncTable (view/add/change/delete), 实战 DBA 组长只配了 DdlSyncPair 缺 DdlSyncTable, add_ddlsynctable 端点 403. 实战 DBA 角色 8 perm 都要配齐

## W2 进度 (9/1+9/2 两天爆肝, 8 commit + 8 大任务全部完工, 提前 5 天)

| 任务 | commit | 状态 |
|------|--------|------|
| D6 数据模型 migration | 57858eb | ✓ |
| D7 后端 + admin + templates | 63cac69 / 7d82210 | ✓ |
| D8 5 AJAX 端点 + 4 service | 5e78ccf | ✓ |
| D8 5 前端文件 | a792cdf | ✓ |
| D9 R3 + signal handler | 5420c81 | ✓ |
| D9 8/13 教训应用 | b712d05 | ✓ |
| **D10 134 dev 端到端演练 5 Case + hotfix** | **本次 commit** | **✓** |
| D11 推 110 prod 主手册 | 待推 | pending |
| D12 W1 周报 9/4 周五提交 | 待推 | pending |

## 下一步

- **D11 9/3 早**: 推 110 prod 主手册执行 (K1 SECRET_KEY / K2 CACHE_URL / K3 dev-only 变量 / K4 sql_config 3 key 4 步必做)
- **D12 9/4 周五**: W1 周报提交 (按 8/17 拍板 3 周周报格式)
- **W3 9/14-9/18 提测上线**: 按 8/28 17:58 拍板节奏
