# CUSTOM-MODIFIED: v0 gh-ost 智能模式 SqlWorkflow 加 gh_ost_mode + native_alter_results @ 2026-09-17 @ mavis
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
#
# 注: DdlGhostTask 加 depends_on 字段在 ddl_gh_ost migration 0006

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sql", "0001_initial"),  # 这个 sql migration 排在 sql app 0001 之后
        # 注: 文件名是 0002 但 dependencies 用 ("sql", "0001_initial") 因为 "0002" 重复了
    ]

    operations = [
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
    ]