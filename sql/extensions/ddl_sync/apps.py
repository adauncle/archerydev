from django.apps import AppConfig


class DdlSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sql.extensions.ddl_sync"
    verbose_name = "DDL 跨库同步 (内部定制)"
