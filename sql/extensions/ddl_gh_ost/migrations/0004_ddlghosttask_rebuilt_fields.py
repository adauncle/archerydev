# CUSTOM-MODIFIED: v0.4.5 拍板 3 决策加 rebuilt_* 字段 @ 2026-08-13 @ mavis
# 关联: docs/changelogs/2026-08-13_v0405-rebuilt-fields.md
#       docs/designs/2026-08-13_v0405-ghost-rebuild-design.md §3.2
# CUSTOM-MODIFIED: v0.4.5 简化 alter 到 1 层 ENGINE=InnoDB @ 2026-08-25 @ mavis
# 关联: docs/changelogs/2026-08-25_v0405-rebuild-8p0-instant-caveat.md
# 业务: rebuild 场景在 rebuild_start 时查 information_schema.tables 拿原表属性,
#       拼出 ENGINE=InnoDB 形式的 alter 子句 (8/25 17:30 简化: 1 层, 替换原 3 层防护 ENGINE+ROW_FORMAT+CHARSET,
#       避免破坏表 COMMENT 业务描述), 5 字段记录"原表属性" (charset/row_format/collation 排查用)
#       + "实际用的 alter" (rebuilt_alter_full, 列表页 truncated 显示).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ddl_gh_ost", "0003_ddlghosttask_instance"),
    ]

    operations = [
        migrations.AddField(
            model_name="ddlghosttask",
            name="rebuilt_charset",
            field=models.CharField(
                blank=True,
                help_text="rebuild 场景: 原表 DEFAULT CHARSET (utf8mb4 等), 记录用",
                max_length=32,
                null=True,
                verbose_name="原表 CHARSET",
            ),
        ),
        migrations.AddField(
            model_name="ddlghosttask",
            name="rebuilt_collation",
            field=models.CharField(
                blank=True,
                help_text="rebuild 场景: 原表 DEFAULT COLLATION (utf8mb4_general_ci 等), 记录用",
                max_length=64,
                null=True,
                verbose_name="原表 COLLATION",
            ),
        ),
        migrations.AddField(
            model_name="ddlghosttask",
            name="rebuilt_row_format",
            field=models.CharField(
                blank=True,
                help_text="rebuild 场景: 原表 ROW_FORMAT (Dynamic/Compact 等), 记录用",
                max_length=16,
                null=True,
                verbose_name="原表 ROW_FORMAT",
            ),
        ),
        migrations.AddField(
            model_name="ddlghosttask",
            name="rebuilt_alter_full",
            field=models.TextField(
                blank=True,
                help_text="rebuild 场景: 完整 alter 子句 (不带 ALTER TABLE t 前缀), 列表页 truncated 显示",
                verbose_name="rebuild 用的完整 alter 子句",
            ),
        ),
        migrations.AddField(
            model_name="ddlghosttask",
            name="rebuilt_at",
            field=models.DateTimeField(
                blank=True,
                help_text="rebuild 场景: 物理重写完成时间 (cut-over 成功时写)",
                null=True,
                verbose_name="rebuild 完成时间",
            ),
        ),
    ]
