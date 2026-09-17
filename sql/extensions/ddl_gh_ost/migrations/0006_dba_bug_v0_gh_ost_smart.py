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
# - DdlGhostTask 加 depends_on ForeignKey (串行依赖链)
#
# 注: SqlWorkflow 加 gh_ost_mode + native_alter_results 字段在 sql migration 里
#     (0001_v0_gh_ost_smart.py 由 makemigrations 自动生成)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        # DdlGhostTask 加 depends_on 字段前要先有 DdlGhostTask 表本身
        ("ddl_gh_ost", "0005_dba_bug_9_ghost_multi_statement"),
        # SqlWorkflow 字段 (gh_ost_mode + native_alter_results) 在 sql migration
        ("sql", "0002_v0_gh_ost_smart"),
    ]

    operations = [
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