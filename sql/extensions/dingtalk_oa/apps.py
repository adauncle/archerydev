from django.apps import AppConfig


class DingtalkOaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sql.extensions.dingtalk_oa"
    verbose_name = "钉钉 OA 审批集成（内部定制）"
