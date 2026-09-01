from django.apps import AppConfig


class DdlSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sql.extensions.ddl_sync"
    verbose_name = "DDL 跨库同步 (内部定制)"

    ## CUSTOM-MODIFIED: v0.5.0-alpha R3 注册 workflow_passed_handler signal @ 2026-09-01 @ mavis
    ## 关联: docs/changelogs/2026-09-01_ddl-sync-w2-d9-sync-trigger.md
    def ready(self):
        # 9/1 W1-D3 §5.1 拍板: 业务库 SqlWorkflow 状态变 PASSED → 触发同步
        # signal 在 @receiver(post_save, sender=SqlWorkflow) 注册, 这里只 import 让 ready 钩子跑
        from .services import sync_trigger  # noqa: F401
