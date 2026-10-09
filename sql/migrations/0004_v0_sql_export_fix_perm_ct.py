# -*- coding: utf-8 -*-
"""v0 数据导出工单 (DBA-bug 17) 修 2 个 perm 的 ContentType 错挂

CUSTOM-MODIFIED: v0 修 menu_sqlexportworkflow + sqlexport_submit 的 ContentType 错挂 @ 2026-10-09 @ mavis
关联: docs/changelogs/2026-10-09_v0-sql-export-workflow-delta.md
业务: 134 dev migrate 0003 之后, 2 个 tuple perm (`menu_sqlexportworkflow` + `sqlexport_submit`)
       残留在 ct=permission (ContentType id=7) 而非 ct=sqlexportworkflow (ContentType id=63)
       admin 搜索"导出" 找不到这 2 个 perm, 业务方/审批人无法通过 admin 配权限
       134 dev 手工 fix 了 db, 110 prod 部署时需要这个 migration 自动 fix
       (如果 110 prod 上 perm 残留, 没这个 migration admin 搜索也找不到)

修法: RunSQL 把 2 个 perm rows 的 content_type_id 改到 sqlexportworkflow (ct_sql_export_workflow.id)
"""
from django.db import migrations


def fix_perm_ct(apps, schema_editor):
    """把 menu_sqlexportworkflow + sqlexport_submit 的 content_type 改到 sqlexportworkflow"""
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType
    ct, _ = ContentType.objects.get_or_create(app_label="sql", model="sqlexportworkflow")
    for codename in ("menu_sqlexportworkflow", "sqlexport_submit"):
        try:
            p = Permission.objects.get(codename=codename)
            if p.content_type_id != ct.id:
                old_ct = p.content_type.model
                p.content_type = ct
                p.save(update_fields=["content_type"])
                print(f"  [fix_perm_ct] {codename}: ct {old_ct} -> {ct.model}")
        except Permission.DoesNotExist:
            pass


def reverse_noop(apps, schema_editor):
    """不回滚 (ct 改回 permission 是错的)"""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("sql", "0003_v0_sql_export_workflow"),
    ]

    operations = [
        migrations.RunPython(fix_perm_ct, reverse_noop),
    ]
