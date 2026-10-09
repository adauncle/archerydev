# 2026-10-09 v0 数据导出工单 (beta)

## 背景

v0-alpha 拍板后 (commit f8f876d) 创建工单已走通: 业务方填 SQL -> POST /sqlexportsubmit_create/ -> SqlExportWorkflow + WorkflowAudit 表写入成功。
本 beta commit 补完 v0 的 "审批通过 -> 自动导出 -> 通知" 核心闭环:
- 模块 4: WorkflowAudit 审批通过 callback (api_workflow.py 加 SQL_EXPORT 分支)
- 模块 5: 异步任务 do_sql_export (sql.utils.sql_export) 跑 SQL 写 CSV/XLSX
- 模块 6: 邮件附件 + 钉钉文本通知 (复用 sql.notify / common.utils.sendmsg)

## 3 处变更 (v0-beta)

### 1. `sql/utils/sql_export.py` (新文件, 240 行)

异步任务模块:
- `do_sql_export(export_id)`: 跑 SqlExportWorkflow 的 SQL, 写 CSV/XLSX + zip 压缩, 存到 /opt/archery/prod/exports/
- `notify_for_sql_export(export_id)`: 邮件附件交付 (用 MsgSender.send_email) + 钉钉文本通知 (webhook POST)

业务流程:
1. 改 status=4 (导出中)
2. `check_engine.query(db_name, sql, max_execution_time)` 跑 SQL
3. `_save_format_file()` 写 CSV 或 XLSX + zip 压缩
4. `shutil.copy2()` 拷贝到 exports 根目录
5. 改 status=5, 写 file_path / file_size / row_count / finished_at
6. 调 notify_for_sql_export 通知申请人
7. 失败: 改 status=6, 写 error_msg

边界:
- max_export_rows 限制导出行数 (默认 10000)
- 邮件失败不影响 do_sql_export 主流程 (try/except 包裹)
- 钉钉 webhook 失败也只是 dingtalk_status: fail, 不阻塞

### 2. `sql_api/api_workflow.py` line 384 之后新增 SQL_EXPORT 分支

真实审批流 callback (走 audit_auth_groups 非空的情况):

```python
elif auditor.workflow_type == WorkflowType.SQL_EXPORT:
    from sql.models import SqlExportWorkflow
    from django.utils import timezone
    export = SqlExportWorkflow.objects.get(id=auditor.audit.workflow_id)
    if auditor.audit.current_status == WorkflowStatus.PASSED:
        export.status = 4  # 导出中
        export.audit_user = serializer.data["engineer"]
        export.approved_at = timezone.now()
        export.save(update_fields=["status", "audit_user", "approved_at", "sys_time"])
        async_task(
            "sql.utils.sql_export.do_sql_export",
            export_id=export.id,
            timeout=600,
            task_name=f"sqlexport-{export.id}",
        )
    elif auditor.audit.current_status in [ABORTED, REJECTED]:
        export.status = 3  # 驳回
        export.audit_user = serializer.data["engineer"]
        export.save(...)
```

### 3. `sql/views.py` sqlexportsubmit_create 端点尾部加 auto_pass 路径

`audit_auth_groups=""` (auto_pass) 工单提交后立刻改 status=2 (审批通过) + audit.current_status=1 + 入 async_task:

```python
if not audit_group_ids:
    # auto_pass 路径
    export.status = 2
    export.audit_user = "auto_pass"
    export.approved_at = timezone.now()
    export.save(update_fields=["status", "audit_user", "approved_at", "sys_time"])
    audit.current_status = WorkflowStatus.PASSED
    audit.save(update_fields=["current_status", "sys_time"])
    async_task("sql.utils.sql_export.do_sql_export", export_id=export.id, timeout=600, task_name=f"sqlexport-{export.id}")
```

## 134 dev 演练结果

### drill v0-beta 手工调 do_sql_export

```
=== manual call do_sql_export(4) ===
result: {'status': 'ok', 'file_path': '/opt/archery/prod/exports/information_schema_20261009160005_ea5de1b0.zip',
         'file_size': 774, 'row_count': 10, 'elapsed': 0.011}

=== reload SqlExportWorkflow id=4 ===
id= 4 title= DBA-bug-17 drill test 1009 status= 5 (导出完成) ✅
file_path: /opt/archery/prod/exports/information_schema_20261009160005_ea5de1b0.zip ✅
file_size: 774 ✅
row_count: 10 ✅
finished_at: 2026-10-09 16:00:05 ✅
err= (空, 成功) ✅
```

### 邮件发送

134 dev 没配 SMTP (`mail_smtp_server=None`), 邮件推送失败但被 try/except 捕获:

```
ERROR - 邮件推送失败
Traceback (most recent call last):
  File "/opt/archery/prod/common/utils/sendmsg.py", line 108, in send_email
    main_msg["From"] = formataddr(["Archery 通知", self.MAIL_REVIEW_FROM_ADDR])
  AttributeError: 'NoneType' object has no attribute 'encode'
```

不影响主流程 — 110 prod 配 SMTP 后会成功。

### 真实审批流 callback (api_workflow.py)

代码已写但 134 dev 演练受限 (没有真实审批组配置)。v0-deploy 110 prod 时真实业务方 + 审批人走通。

## 已知限制 (v0-beta 范围, v0-deploy 解决)

- qcluster worker 没自动 reload 新模块 — 推代码后必须重启 qcluster (`pkill -9 -f qcluster; setsid ... manage.py qcluster`)
- 134 dev 邮件没配 SMTP, 通知失败是预期
- 没有"下载文件"UI 端点 (v0-gamma 解决)
- 没有详情页 / 列表页 (v0-gamma 解决)

## commit

- `feat(sql)`: v0 数据导出工单 beta (审批 callback + 异步任务 + 通知)
  - sql/utils/sql_export.py (新文件, 240 行: do_sql_export + notify_for_sql_export)
  - sql_api/api_workflow.py (line 384 之后 + SQL_EXPORT 分支)
  - sql/views.py (sqlexportsubmit_create 端点尾部 + auto_pass 路径)
