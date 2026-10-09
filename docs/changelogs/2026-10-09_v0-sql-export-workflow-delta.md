# 2026-10-09 v0 数据导出工单 (delta)

## 背景

v0-gamma (commit 7b1afda) 之后 134 dev 阿达叔叔验证, 发现:
1. **顶菜单没显示"数据导出"** — `perms.sql.menu_sqlexportworkflow` 模板渲染走了独立分支 (不是 superuser 自动 True)
2. **列表页"没有找到匹配的记录"** — sqlexportworkflow.html 模板 JS 拉的是 `/sqlworkflow_list/` (查 SqlWorkflow), 不是 SqlExportWorkflow, 业务方看不到 v0 工单

这两个都是 v0.0 已知限制外的"真根因", 必须修才能让 134 dev 真实演练通过。

## 2 处变更 (v0-delta)

### 1. `sql/views.py` 新增 `/sqlexport_list/` API 端点

```python
@permission_required("sql.menu_sqlexportworkflow", raise_exception=True)
def sqlexport_list(request):
    """数据导出工单列表 JSON API (供列表页 JS 拉数据).
    返回 {total: N, rows: [{id, title, user_name, instance_name, db_name,
                              status, status_display, create_time, file_size, ...}]}
    """
    # 权限: 业务方只看自己, superuser/audit_user/sql_review 看全部
    if user.is_superuser or has_perm("audit_user") or has_perm("sql_review"):
        queryset = SqlExportWorkflow.objects.all()
    else:
        queryset = SqlExportWorkflow.objects.filter(user_name=user.username)
    # 搜索 (title__icontains) + 分页 (limit/offset) + 排序 (sort)
    # 补 instance_name / status_display / ISO 时间格式
    return JsonResponse({"total": total, "rows": rows_data})
```

### 2. `sql/templates/sqlexportworkflow.html` 重写

- JS 改拉 `/sqlexport_list/` (代替 `/sqlworkflow_list/`)
- 字段: id / title (跳详情) / user_display / instance_name / db_name / export_format (CSV/XLSX) / status (7 状态机 + 颜色标签) / create_time / 操作
- 状态颜色映射: 0=灰 1/2/4=蓝 3=黄 5=绿 6=红
- 操作列: "详情" 按钮 (所有工单) + "下载" 按钮 (status=5 有 file_path)
- toolbar 加 "新建导出工单" 按钮 (跳 /sqlexportsubmit/)

### 3. `sql/urls.py` 注册 URL

```python
path("sqlexport_list/", views.sqlexport_list, name="sqlexport_list"),
```

## 134 dev 演练结果

```
=== POST /sqlexport_list/ (force_login archery) ===
  total: 2
  rows count: 2
  id=4 title=DBA-bug-17 drill test 1009 user=archery status=5 status_display=导出完成 file_size=774
  id=3 title=DBA-bug-17 drill test 1009 user=archery status=0 status_display=待审核 file_size=0

=== POST /sqlexport_list/ search='drill' ===
  total: 2 (搜索 OK)

=== /sqlexportworkflow/4/ === 
  has title: True ✅
  has download: True ✅
  page size: 35298

=== /sqlexportworkflow/4/download/ ===
  Content-Type: application/zip ✅
  Content-Disposition: attachment ✅
```

## 134 dev 业务方操作步骤 (更新)

1. **顶菜单权限** — 业务方/审批人/超管账号需要 `sql.menu_sqlexportworkflow` + `sql.sqlexport_submit` 权限
   - 134 dev: archery 用户已经手动加权限 (force_login 演练用)
   - 110 prod: 待 v0-deploy 时分配 (建议加到 `DBA` 组 或 新建 `数据导出用户` 组)
2. **业务方走全流程** (auto_pass):
   - 顶菜单 "SQL 查询" → "数据导出" (硬刷一次, 浏览器缓存)
   - 点 "新建导出工单" → 填表 → 提交
   - 跳到列表页, 工单显示在第一条 (7 状态机 + 颜色标签)
   - 等几秒 (后台异步跑 SQL + 写文件) → status=5 绿色
   - 点 "下载" 按钮 → 浏览器下载 zip
3. **真实审批流 (有审批组)**:
   - 提交后 status=0 待审核
   - 审批人 "SQL 审核" 看到工单 → 通过 → status=2 → status=4 → status=5

## 已知限制 (v0-delta 范围, v0.1 解决)

- 列表页没"批量审批"按钮, 审批人需逐个点详情页
- 详情页没"审批通过/驳回"按钮, 审批人需在 SQL 审核页审
- 列表页 status 过滤 (toolbar navStatus) 已加, 但其他字段 (按时间/格式) 没加
- 110 prod 权限分配策略待定 (DBA 组 / 新建数据导出组 / 手动加)

## commit

- `feat(sql)`: v0 数据导出工单 delta (修列表页 JS 拉错 url + 加 /sqlexport_list/ API)
  - sql/views.py (+sqlexport_list 端点)
  - sql/urls.py (+1 个 URL)
  - sql/templates/sqlexportworkflow.html (重写, 适配 SqlExportWorkflow + 7 状态机 + 颜色)
