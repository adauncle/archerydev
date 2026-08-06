"""gh-ost 集成 — URLConf。

在 ``archery/urls.py`` 中按需 include：

    if getattr(settings, "CUSTOM_GH_OST_ENABLED", False):
        urlpatterns += [
            path("gh_ost/", include(("sql.extensions.ddl_gh_ost.urls", "ddl_gh_ost"))),
        ]

最终 URL：
    POST /gh_ost/precheck/<id>/         跑预检（需登录）
    POST /gh_ost/enable/<id>/           启用 gh-ost + 写 task
    POST /gh_ost/start/<id>/            启动（alpha 标 running）
    POST /gh_ost/cancel/<id>/           取消
    GET  /gh_ost/status/<id>/           进度查询
    GET  /gh_ost/progress/<id>/         进度面板页（Django template）
"""

from django.urls import path

from . import views

app_name = "ddl_gh_ost"

urlpatterns = [
    path("precheck/<int:workflow_id>/", views.precheck, name="precheck"),
    path("enable/<int:workflow_id>/", views.enable, name="enable"),
    path("start/<int:workflow_id>/", views.start, name="start"),
    path("cancel/<int:workflow_id>/", views.cancel, name="cancel"),
    path("status/<int:workflow_id>/", views.status, name="status"),
    path("progress/<int:workflow_id>/", views.progress_page, name="progress"),
]
