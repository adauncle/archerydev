# 2026-10-09 v0 数据导出工单 (alpha)

## 背景

10/9 14:52 阿达叔叔提需求:
1. 不存在独立的【数据导出申请工单】
2. 不支持"先写好导出 SQL,提交工单专门审批这条导出语句,审批通过后台自动导出文件给申请人"

调研 Archery 1.14.0 上游: sqlexport 是 UI 半成品
- 路由: `sqlexportworkflow` + `sqlexportsubmit` + `sqlexport_pre_check` 已注册
- 模板: `sqlexportsubmit.html` 34KB (表单/审批流/导出提交按钮 完整 UI)
- 视图: `sqlexportsubmit` (GET 渲染), `sqlexport_pre_check` (POST 预检导出行数)
- 缺失: **后端工单创建端点** + **审批通过自动导出** + **`class WorkflowType` 整个项目不存在** (dead code bug)

拍板方案 (10/9 14:52 阿达叔叔按我建议决策):
- 导出格式: CSV + XLSX
- 数据量上限: 1 万行 (max_export_rows)
- 文件交付: 邮件附件
- 审批人: 复用 SQL 上线工单审批流
- 范围: MVP (不含数据脱敏/定时/增量)

## 方案 (5 模块 / 5 天)

v0-alpha (本 commit):
- 模块 1: WorkflowType 枚举补完 (sql.models + common.utils.const 两边都加 SQL_EXPORT=4)
- 模块 2: SqlExportWorkflow 新 model + migration
- 模块 3: sqlexportsubmit_create POST 端点 (pre_check 预检 + 写 SqlExportWorkflow + 写 WorkflowAudit)

v0-beta (后续 commit):
- 模块 4: WorkflowAudit 审批通过 callback + django_q 异步任务
- 模块 5: 异步任务跑 SQL 导出 CSV/XLSX + 邮件/钉钉通知交付

v0-gamma (后续 commit):
- 模块 6: 详情页 + 列表页后端接 SqlExportWorkflow

v0-deploy (后续 commit):
- 模块 7: 110 prod 部署 + drill + 月度宣讲实战

## 4 处变更 (v0-alpha)

### 1. `common/utils/const.py` WorkflowType 加 SQL_EXPORT=4

```python
class WorkflowType(models.IntegerChoices):
    QUERY = 1, "查询权限申请"
    SQL_REVIEW = 2, "SQL上线申请"
    ARCHIVE = 3, "数据归档申请"
    SQL_EXPORT = 4, "数据导出申请"  # NEW
```

`api_workflow.py` line 35 从这里 import WorkflowType。

### 2. `sql/models.py` 新增 SqlExportWorkflow model + WorkflowType 枚举补完 + WorkflowAuditMixin 加 SQL_EXPORT 分支

- `class WorkflowType(models.IntegerChoices)`: QUERY=1 / SQL_REVIEW=2 / ARCHIVE=3 / SQL_EXPORT=4
  (跟 common.utils.const 同值,被 `WorkflowAuditMixin.workflow_type` property 引用)
- `class SqlExportWorkflow(models.Model, WorkflowAuditMixin)`: 新表
  - 字段 19 个: title / instance / db_name / sql_content / export_format / audit_auth_groups
    / status (0-6 状态机) / file_path / file_size / row_count / error_msg
    / user_name / user_display / audit_user / create_time / approved_at / finished_at / sys_time
  - 状态机: 0=待审核 1=审核中 2=审批通过 3=驳回 4=导出中 5=完成 6=失败
  - `db_table = "sql_export_workflow"`
- `WorkflowAuditMixin.workflow_type` / `workflow_pk_field` 各加 `SqlExportWorkflow` 分支

### 3. `sql/views.py` 新增 `sqlexportsubmit_create` 端点 + 顶部 import 补完

```python
@permission_required("sql.sqlexport_submit", raise_exception=True)
def sqlexportsubmit_create(request):
    """数据导出工单提交端点 (POST)."""
    # 1. 基础参数校验
    # 2. 实例校验
    # 3. 预检 OffLineDownLoad.pre_count_check
    # 4. 审批组解析 (逗号分隔 -> [int]; 空 = auto pass current_audit=-1)
    # 5. 事务: 写 SqlExportWorkflow (status=0) + 写 WorkflowAudit (workflow_type=4)
    return JsonResponse({status: 0, data: {workflow_id, audit_id, title}})
```

顶部 import 补:
- `from django.db import transaction` (新)
- `SqlExportWorkflow, WorkflowAudit` (在 `from .models import (...)` 块)
- `WorkflowStatus` (在 `from common.utils.const import ...`)

### 4. `sql/urls.py` 注册 URL

```python
path("sqlexportsubmit_create/", views.sqlexportsubmit_create),
```

(在 `sqlexport/pre_check/` 后面)

## 5. `sql/migrations/0003_v0_sql_export_workflow.py` 新 migration

- `CreateModel` SqlExportWorkflow (FK -> sql_instance)
- `dependencies: [("sql", "0002_v0_gh_ost_smart")]`
- 134 dev db 测试: `migrate sql 0003` OK

## 134 dev 演练结果

```
=== drill v0 ===
force_login OK, user: archery
=== instances count: 2 ===
  id= 1 name= archery
  id= 2 name= 测试 MySQL 8.0
test instance: archery id= 1

=== POST /sqlexportsubmit_create/ ===
status: 200
body: {"status": 0, "msg": "ok", "data": {"workflow_id": 3, "audit_id": 4737, "title": "DBA-bug-17 drill test 1009"}}

=== SqlExportWorkflow rows ===
  id= 3 title= DBA-bug-17 drill test 1009 status= 0 format= csv user= archery create_time= 2026-10-09 15:33:15

=== WorkflowAudit SQL_EXPORT=4 rows ===
  audit_id= 4737 wf_id= 3 title= DBA-bug-17 drill test 1009 current_status= 0 (WAITING) current_audit= -1 (auto_pass) create_user= archery

=== test 400: 缺 title ===
  status: 200 body: {"status": 1, "msg": "工单名/实例/数据库/SQL 不能为空"}

=== test 400: 实例不存在 ===
  status: 200 body: {"status": 1, "msg": "实例 no_such_instance_xyz 不存在"}

=== test 405: GET 不允许 ===
  status: 405 body: {"status": 1, "msg": "method not allowed"}

ALL PASS
```

## 已知限制 (v0-alpha 范围, v0-beta 解决)

- 审批通过 callback 还没接 — 工单建好后只能看 WorkflowAudit 列表, 没法触发"自动导出"
- 邮件 / 钉钉通知还没接 — v0-beta 异步任务完成后调
- 详情页 / 列表页 / 审批 UI 还没接 — v0-gamma 解决
- 110 prod 还没部署 — v0-deploy

## commit

- `feat(sql)`: v0 数据导出工单 alpha (WorkflowType + SqlExportWorkflow + 创建端点)
  - common/utils/const.py (+SQL_EXPORT=4)
  - sql/models.py (+class WorkflowType, +class SqlExportWorkflow, +mixin 2 分支)
  - sql/views.py (+sqlexportsubmit_create 端点, +3 个 import)
  - sql/urls.py (+1 个 URL)
  - sql/migrations/0003_v0_sql_export_workflow.py (新文件)
