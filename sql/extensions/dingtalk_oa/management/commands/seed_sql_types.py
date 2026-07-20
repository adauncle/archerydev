"""灌入 13 个内置 SQL 类型。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §5.3 / §8.4

使用：

    python manage.py seed_sql_types

idempotent：已存在的 code 会更新 pattern / severity / description，重复跑
不会创建重复行。
"""

from django.core.management.base import BaseCommand

from sql.extensions.dingtalk_oa.models import SqlTypeRegistry


SEED_DATA = [
    # DQL
    {
        "code": "SELECT", "category": "DQL",
        "description": "SELECT 查询",
        "pattern": r"^\s*SELECT\b",
        "default_severity": "low", "has_affected_rows": False, "is_critical": False,
    },
    # DML
    {
        "code": "INSERT", "category": "DML",
        "description": "INSERT 插入",
        "pattern": r"^\s*INSERT\b",
        "default_severity": "low", "has_affected_rows": True, "is_critical": False,
    },
    {
        "code": "UPDATE", "category": "DML",
        "description": "UPDATE 更新",
        "pattern": r"^\s*UPDATE\b",
        "default_severity": "medium", "has_affected_rows": True, "is_critical": False,
    },
    {
        "code": "DELETE", "category": "DML",
        "description": "DELETE 删除",
        "pattern": r"^\s*DELETE\b",
        "default_severity": "high", "has_affected_rows": True, "is_critical": True,
    },
    {
        "code": "REPLACE", "category": "DML",
        "description": "REPLACE 替换",
        "pattern": r"^\s*REPLACE\b",
        "default_severity": "high", "has_affected_rows": True, "is_critical": True,
    },
    # DDL
    {
        "code": "ALTER", "category": "DDL",
        "description": "ALTER 修改表结构",
        "pattern": r"^\s*ALTER\b",
        "default_severity": "high", "has_affected_rows": False, "is_critical": True,
    },
    {
        "code": "DROP", "category": "DDL",
        "description": "DROP 删除对象",
        "pattern": r"^\s*DROP\b",
        "default_severity": "high", "has_affected_rows": False, "is_critical": True,
    },
    {
        "code": "TRUNCATE", "category": "DDL",
        "description": "TRUNCATE 清空表",
        "pattern": r"^\s*TRUNCATE\b",
        "default_severity": "high", "has_affected_rows": False, "is_critical": True,
    },
    {
        "code": "CREATE", "category": "DDL",
        "description": "CREATE 创建对象",
        "pattern": r"^\s*CREATE\b",
        "default_severity": "high", "has_affected_rows": False, "is_critical": True,
    },
    {
        "code": "RENAME", "category": "DDL",
        "description": "RENAME 重命名",
        "pattern": r"^\s*RENAME\b",
        "default_severity": "high", "has_affected_rows": False, "is_critical": True,
    },
    # DCL
    {
        "code": "GRANT", "category": "DCL",
        "description": "GRANT 授权",
        "pattern": r"^\s*GRANT\b",
        "default_severity": "high", "has_affected_rows": False, "is_critical": True,
    },
    {
        "code": "REVOKE", "category": "DCL",
        "description": "REVOKE 撤销权限",
        "pattern": r"^\s*REVOKE\b",
        "default_severity": "high", "has_affected_rows": False, "is_critical": True,
    },
    {
        "code": "SET", "category": "DCL",
        "description": "SET 设置变量 / 字符集等",
        "pattern": r"^\s*SET\b",
        "default_severity": "low", "has_affected_rows": False, "is_critical": False,
    },
]


class Command(BaseCommand):
    help = "灌入 13 个内置 SQL 类型（idempotent，重复跑仅 update）"

    def handle(self, *args, **options):
        created, updated = 0, 0
        for data in SEED_DATA:
            obj, was_created = SqlTypeRegistry.objects.update_or_create(
                code=data["code"],
                defaults={
                    "category": data["category"],
                    "description": data["description"],
                    "pattern": data["pattern"],
                    "default_severity": data["default_severity"],
                    "has_affected_rows": data["has_affected_rows"],
                    "is_critical": data["is_critical"],
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(self.style.SUCCESS(
            f"seed_sql_types: {created} created, {updated} updated (total={created + updated})"
        ))
