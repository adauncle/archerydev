# -*- coding: utf-8 -*-
"""v0 数据导出工单 SqlExportWorkflow 新 model migration.

CUSTOM-MODIFIED: v0 数据导出工单 (DBA-bug 17) SqlExportWorkflow 新表 @ 2026-10-09 @ mavis
业务: 业务方填导出 SQL -> 审批 -> 后台自动导出 CSV/XLSX -> 邮件交付 (Archery 1.14.0 上游半成品)
表: sql_export_workflow (新表, 134 dev + 110 prod 都不存在, 需要 CREATE TABLE)
字段: title / instance / db_name / sql_content / export_format / audit_auth_groups /
      status (0-6 状态机) / file_path / file_size / row_count / error_msg /
      user_name / user_display / audit_user / create_time / approved_at / finished_at / sys_time
关联: docs/changelogs/2026-10-09_v0-sql-export-workflow.md
拍板: 10/9 14:52 阿达叔叔 (按我的建议: CSV+XLSX / 1万行 / 邮件 / 复用 SQL 审批流)
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("sql", "0002_v0_gh_ost_smart"),
    ]

    operations = [
        migrations.CreateModel(
            name="SqlExportWorkflow",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=50, verbose_name="导出工单名称")),
                ("db_name", models.CharField(max_length=64, verbose_name="源数据库")),
                (
                    "sql_content",
                    models.TextField(verbose_name="导出 SQL (SELECT only)"),
                ),
                (
                    "export_format",
                    models.CharField(
                        choices=[("csv", "CSV"), ("xlsx", "XLSX")],
                        default="csv",
                        max_length=10,
                        verbose_name="导出格式",
                    ),
                ),
                (
                    "audit_auth_groups",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=255,
                        verbose_name="审批权限组列表",
                    ),
                ),
                (
                    "status",
                    models.IntegerField(
                        choices=[
                            (0, "待审核"),
                            (1, "审核中"),
                            (2, "审批通过"),
                            (3, "驳回"),
                            (4, "导出中"),
                            (5, "导出完成"),
                            (6, "导出失败"),
                        ],
                        default=0,
                        verbose_name="工单状态",
                    ),
                ),
                (
                    "file_path",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=500,
                        verbose_name="导出文件路径",
                    ),
                ),
                (
                    "file_size",
                    models.BigIntegerField(
                        default=0, verbose_name="导出文件大小 (bytes)"
                    ),
                ),
                ("row_count", models.IntegerField(default=0, verbose_name="导出行数")),
                (
                    "error_msg",
                    models.TextField(
                        blank=True, default="", verbose_name="错误信息"
                    ),
                ),
                ("user_name", models.CharField(max_length=30, verbose_name="申请人")),
                (
                    "user_display",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=50,
                        verbose_name="申请人中文名",
                    ),
                ),
                (
                    "audit_user",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=30,
                        verbose_name="最后审批人",
                    ),
                ),
                ("create_time", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("approved_at", models.DateTimeField(blank=True, null=True, verbose_name="审批通过时间")),
                ("finished_at", models.DateTimeField(blank=True, null=True, verbose_name="完成时间")),
                ("sys_time", models.DateTimeField(auto_now=True, verbose_name="系统时间")),
                (
                    "instance",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="sql.instance",
                    ),
                ),
            ],
            options={
                "db_table": "sql_export_workflow",
                "managed": True,
                "verbose_name": "数据导出工单",
                "verbose_name_plural": "数据导出工单",
                "ordering": ["-create_time"],
            },
        ),
    ]
