"""钉钉 OA 集成 — URLConf。

在 ``archery/urls.py`` 中按需 include：

    if getattr(settings, "CUSTOM_DINGTALK_OA_ENABLED", False):
        from django.conf import settings
        urlpatterns += [
            path("dingtalk/oa/", include(("sql.extensions.dingtalk_oa.urls", "dingtalk_oa"))),
        ]

最终 URL：
    POST /dingtalk/oa/callback         钉钉回调（公开）
    POST /dingtalk/oa/retry/<id>/       手动重试（需 sql.audit_user 权限）
"""

from django.urls import path

from . import callback, views

app_name = "dingtalk_oa"

urlpatterns = [
    path("callback", callback.dingtalk_oa_callback, name="callback"),
    path(
        "retry/<int:workflow_id>/",
        views.retry_oa,
        name="retry_oa",
    ),
]
