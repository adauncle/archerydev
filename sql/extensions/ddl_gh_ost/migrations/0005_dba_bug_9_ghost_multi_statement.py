# CUSTOM-MODIFIED: DBA-bug-9 多 statement 工单支持 @ 2026-09-16 @ mavis
# 关联: docs/changelogs/2026-09-16_dba-bug-9-ghost-multi-statement.md
#       docs/designs/2026-09-16_dba-bug-9-ghost-multi-statement-design.md
# 根因 (9/16 wf#4841): 业务方实战工单含 CREATE TABLE + ALTER TABLE vehicle_risk_hit,
#       gh-ost 只处理 ALTER 一条, CREATE 丢失; 工单状态仍显示"已正常结束"
# 改法:
#   1. 加 statement_index + statement_type 字段, 标识"工单 SQL 列表的第几条"和"DDL 类型"
#   2. unique_together 从 (task_type, workflow) 改成 (task_type, workflow, statement_index)
#      允许一个工单多个 gh-ost task (每个 ALTER 一个)
#   3. precheck / poller / views / detail.html 配套改造 (见设计稿 §3)
# 数据迁移:
#   - 旧 task (没 statement_index) 默认 statement_index=0 (兼容)
#   - 旧 unique_together 跟新 unique 不冲突 (旧 (task_type, workflow) 是新 (task_type, workflow, 0) 的子集)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ddl_gh_ost", "0004_ddlghosttask_rebuilt_fields"),
    ]

    operations = [
        # 1. 加 statement_index 字段 (默认 0 兼容旧 task)
        migrations.AddField(
            model_name="ddlghosttask",
            name="statement_index",
            field=models.IntegerField(
                default=0,
                help_text="工单 SQL 列表的第几条 (从 0 开始);0 = 第一条",
                verbose_name="SQL 序号 (工单内的第几条)",
            ),
        ),
        # 2. 加 statement_type 字段 (默认 "ALTER" 兼容旧 task)
        migrations.AddField(
            model_name="ddlghosttask",
            name="statement_type",
            field=models.CharField(
                blank=True,
                default="ALTER",
                help_text="DDL 类型: ALTER / CREATE / INSERT / UPDATE / DELETE / USE (gh-ost 任务只存 ALTER)",
                max_length=16,
                verbose_name="DDL 类型",
            ),
        ),
        # 3. 删旧 unique_together (task_type, workflow)
        migrations.RemoveConstraint(
            model_name="ddlghosttask",
            name="uniq_task_type_workflow",
        ),
        # 4. 加新 unique_together (task_type, workflow, statement_index)
        migrations.AddConstraint(
            model_name="ddlghosttask",
            constraint=models.UniqueConstraint(
                fields=("task_type", "workflow", "statement_index"),
                name="uniq_task_type_workflow_stmt",
            ),
        ),
    ]