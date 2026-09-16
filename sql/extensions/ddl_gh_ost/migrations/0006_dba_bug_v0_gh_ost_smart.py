# CUSTOM-MODIFIED: v0 gh-ost 智能模式 (smart mode) @ 2026-09-16 @ mavis
# 关联: docs/designs/2026-09-16_v0-gh-ost-smart-mode-design.md
#       docs/changelogs/2026-09-16_v0-gh-ost-smart-mode.md
# 拍板: 9/16 21:42 阿达叔叔 同意 5A
#   1. 大表阈值: 复用 10w 行 / 100MB
#   2. 小表走原生 mysql.execute() 直连 ALTER
#   3. task 串行依赖链 (depends_on)
#   4. gh_ost_mode 选法: 工单页下拉框
#   5. wf.status 控制: poller 统一 (全部 ghost task 终态 + 小表 ALTER 完成)
#
# 改造:
# - SqlWorkflow 加 gh_ost_mode 字段 (smart/all_ghost/all_native)
# - SqlWorkflow 加 native_alter_results JSONField (smart 模式小表 ALTER 结果)
# - DdlGhostTask 加 depends_on ForeignKey (串行依赖链)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ddl_gh_ost", "0005_dba_bug_9_ghost_multi_statement"),
    ]

    operations = [
        # SqlWorkflow 加 gh_ost_mode 字段
        migrations.AddField(
            model_name="sqlworkflow",
            name="gh_ost_mode",
            field=models.CharField(
                choices=[
                    ("smart", "智能 (默认: 大表 gh-ost + 小表原生 ALTER)"),
                    ("all_ghost", "全部 gh-ost (强制所有 ALTER 走 gh-ost)"),
                    ("all_native", "全部原生 ALTER (强制所有 ALTER 走原生)"),
                ],
                db_index=True,
                default="smart",
                help_text="smart=默认智能分流;all_ghost=全部 gh-ost;all_native=全部原生",
                max_length=16,
                verbose_name="gh-ost 模式",
            ),
        ),
        # SqlWorkflow 加 native_alter_results JSONField
        migrations.AddField(
            model_name="sqlworkflow",
            name="native_alter_results",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="smart 模式下小表原生 ALTER 的执行结果",
                verbose_name="小表原生 ALTER 结果",
            ),
        ),
        # DdlGhostTask 加 depends_on ForeignKey
        migrations.AddField(
            model_name="ddlghosttask",
            name="depends_on",
            field=models.ForeignKey(
                blank=True,
                help_text="串行依赖: 本 task 启动需要 depends_on 任务 success 状态",
                null=True,
                on_delete=models.SET_NULL,
                related_name="dependent_tasks",
                to="ddl_gh_ost.ddlghosttask",
                verbose_name="依赖 task (前一个串行任务)",
            ),
        ),
    ]