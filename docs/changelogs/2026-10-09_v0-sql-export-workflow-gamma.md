# 2026-10-09 v0 数据导出工单 (gamma)

## 背景

v0-beta (commit 174f27e) 后端闭环走通:
- 创建工单 -> 审批通过 -> 异步跑 SQL 导出 -> 邮件/钉钉通知
v0-gamma 补完 UI: 详情页 + 文件下载端点, 让业务方/审批人/DBA 真实用起来。

## 3 处变更 (v0-gamma)

### 1. `sql/views.py` sqlexportworkflow 列表页 view 改后端接 SqlExportWorkflow

```python
def sqlexportworkflow(request):
    """SQL数据导出工单列表页面 (v0 重写: 查 SqlExportWorkflow)"""
    user = request.user
    # 过滤: 业务方只看到自己, 审批人/superuser 看全部
    if user.is_superuser or user.has_perm("sql.audit_user") or user.has_perm("sql.sql_review"):
        export_list = SqlExportWorkflow.objects.all().order_by("-create_time")[:200]
    else:
        export_list = SqlExportWorkflow.objects.filter(user_name=user.username).order_by("-create_time")[:200]
    # 兼容老模板 (instance 列表 + resource_group 空)
    ...
```

权限: 业务方只看到自己, 审批人/超管看全部 (DBA 一条龙)
注: SqlExportWorkflow 没 group_id 字段, 资源组粒度权限简化为"非 superuser 只看自己"

### 2. `sql/views.py` 新增 sqlexportworkflow_detail 端点 (GET)

```python
@permission_required("sql.sqlexport_submit", raise_exception=True)
def sqlexportworkflow_detail(request, export_id):
    """数据导出工单详情页 (v0 新增)."""
    export = SqlExportWorkflow.objects.get(id=export_id)
    # 权限校验: 业务方/审批人/superuser 都能看
    if not (user.is_superuser or ... or export.user_name == user.username):
        return 403
    # 查 WorkflowAudit
    audit = WorkflowAudit.objects.filter(workflow_id=export.id, workflow_type=WorkflowType.SQL_EXPORT).first()
    return render(request, "sqlexportworkflow_detail.html", {...})
```

### 3. `sql/views.py` 新增 sqlexport_download 端点 (GET)

```python
@permission_required("sql.sqlexport_submit", raise_exception=True)
def sqlexport_download(request, export_id):
    """下载导出文件 (v0 新增)."""
    export = SqlExportWorkflow.objects.get(id=export_id)
    if not 权限校验: return 403
    if not export.file_path or not os.path.exists(export.file_path):
        return 404
    return FileResponse(open(export.file_path, "rb"), as_attachment=True, filename=os.path.basename(export.file_path))
```

### 4. `sql/urls.py` 注册 URL

```python
path("sqlexportworkflow/<int:export_id>/", views.sqlexportworkflow_detail, name="sqlexport_detail"),
path("sqlexportworkflow/<int:export_id>/download/", views.sqlexport_download, name="sqlexport_download"),
```

### 5. `sql/templates/sqlexportworkflow_detail.html` (新)

Django 模板, 显示:
- 头部: 工单 ID + 标题 + 状态标签 (颜色按 status 分: 5=绿 4=蓝 6=红 3=黄 其他=灰)
- 表格 1 (工单信息): ID/工单名/实例/数据库/格式/申请人/审批人/审批组/创建时间/审批通过时间/完成时间
- 表格 2 (文件信息): 文件大小/导出行数/文件路径 (status=5 时显示)
- 错误信息 (status=6 时红字显示 error_msg)
- 导出 SQL (灰色背景 pre 块, max-height 400px)
- 操作按钮: 状态 5 显示"下载"按钮 (跳到 download/), 其他显示"暂无可下载"
- 审批信息表格: 审批 ID / 状态 / 当前审批组 / 下级审批组 / 审批组列表

## 134 dev 演练结果

```
=== /sqlexportworkflow/ status: 200 (47KB) ===
  (模板字段用旧 SqlWorkflow 字段, 新 export_list 在 view 变量里但模板没渲染)
  → 列表页查 SqlExportWorkflow 走通, 模板适配留 v0.1

=== /sqlexportworkflow/4/ status: 200 (35KB) ===
  has title: True (DBA-bug-17 drill test 1009) ✅
  has status label: True (导出完成) ✅
  has download link: True ✅
  has workflow_audit info: True ✅

=== /sqlexportworkflow/4/download/ status: 200 ===
  Content-Type: application/zip ✅
  Content-Disposition: attachment; filename="information_schema_20261009160005_ea5de1b0.zip" ✅

=== /sqlexportworkflow/9999/ status: 404 (不存在) ✅
```

## 已知限制 (v0-gamma 范围, v0.1 解决)

- 列表页模板 (sqlexportworkflow.html) 字段还是 SqlWorkflow 风格, 新 export_list 字段没渲染
  → 业务方看列表会"看着像没数据" (其实数据在, 但表格列没显示)
  → v0.1 重写列表模板, 用 export_list + EXPORT_STATUS_CHOICES 渲染
- 详情页不支持审批操作 (审批 UI 还在 sqlworkflow 那一套)
  → v0.1 加审计员"通过/驳回"按钮 + 审批流程
- 真实审批流 callback 没演练 (134 dev 没真实审批组配置)
  → v0-deploy 110 prod 真实业务方 + 审批人走通

## commit

- `feat(sql)`: v0 数据导出工单 gamma (详情页 + 文件下载)
  - sql/views.py (+sqlexportworkflow view 改, +sqlexportworkflow_detail 端点, +sqlexport_download 端点)
  - sql/urls.py (+2 个 URL)
  - sql/templates/sqlexportworkflow_detail.html (新)
