from django.apps import AppConfig


class DdlGhOstConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sql.extensions.ddl_gh_ost"
    verbose_name = "gh-ost 无锁 DDL（内部定制）"
