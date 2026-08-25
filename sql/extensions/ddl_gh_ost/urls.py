"""gh-ost 集成 — URLConf。

## CUSTOM-MODIFIED: v0.4.5-alpha 加 rebuild 路由 @ 2026-08-06 @ mavis
关联设计: docs/designs/2026-08-05_gh-ost-product-design.html v0.4.5 §5

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

v0.4.5-alpha 新增（碎片回收）：
    GET  /gh_ost/rebuild/list/                       列可重建表（DBA 选表用）
    POST /gh_ost/rebuild/start/                      触发 rebuild task
    GET  /gh_ost/rebuild/status/<task_id>/           rebuild 进度查询
    GET  /gh_ost/rebuild/progress/<task_id>/         rebuild 进度面板（Django template）
"""

from django.urls import path

from . import views

app_name = "ddl_gh_ost"

urlpatterns = [
    path("precheck/<int:workflow_id>/", views.precheck, name="precheck"),
    path("enable/<int:workflow_id>/", views.enable, name="enable"),
    path("start/<int:workflow_id>/", views.start, name="start"),
    path("cancel/<int:workflow_id>/", views.cancel, name="cancel"),
    path("retry/<int:workflow_id>/", views.retry, name="retry"),
    path("rollback/<int:workflow_id>/", views.rollback, name="rollback"),
    path("status/<int:workflow_id>/", views.status, name="status"),
    path("progress/<int:workflow_id>/", views.progress_page, name="progress"),
    # v0.4.5-alpha rebuild 端点
    path("rebuild/list/", views.rebuild_list, name="rebuild_list"),
    path("rebuild/start/", views.rebuild_start, name="rebuild_start"),
    path("rebuild/status/<int:task_id>/", views.rebuild_status, name="rebuild_status"),
    path("rebuild/progress/<int:task_id>/", views.rebuild_progress_page, name="rebuild_progress"),
    # gh-ost 任务管理列表页 (DBA 运维入口) @ 2026-08-12
    path("admin_list/", views.admin_list, name="admin_list"),
    # v0.3.x 字段 diff 检测 @ 2026-08-12
    path("column_diff/", views.column_diff, name="column_diff"),
    # v0.4.5 选表页面 (DBA 主动重建入口) @ 2026-08-25
    path("rebuild/select/", views.rebuild_select_page, name="rebuild_select"),
]
