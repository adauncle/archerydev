from django.urls import include, path
from django.contrib import admin
from common import views
from django.conf import settings

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(("sql_api.urls", "sql_api"), namespace="sql_api")),
    path("", include(("sql.urls", "sql"), namespace="sql")),
]

if settings.ENABLE_CAS:  # pragma: no cover
    import django_cas_ng.views

    urlpatterns += [
        path(
            "cas/authenticate/",
            django_cas_ng.views.LoginView.as_view(),
            name="cas-login",
        ),
    ]  # pragma: no cover

if settings.ENABLE_OIDC:  # pragma: no cover
    urlpatterns += [
        path("oidc/", include("mozilla_django_oidc.urls")),
    ]

if settings.ENABLE_DINGDING:  # pragma: no cover
    urlpatterns += [
        path("dingding/", include("django_auth_dingding.urls")),
    ]

## CUSTOM-MODIFIED: 钉钉 OA 二次开发 —— 接入 URL 路由 @ 2026-07-21 @ mavis
## 关联设计: docs/designs/2026-07-20_dingtalk-oa-workflow.md
## 注意：仅当 .env 中 CUSTOM_DINGTALK_OA_ENABLED=True 时 dingtalk_oa app 才会注册到 INSTALLED_APPS，
##       这里 include 也仅在那个条件下才有意义；用 if getattr(settings, ...) 包一下做容错
if getattr(settings, "CUSTOM_DINGTALK_OA_ENABLED", False):  # pragma: no cover
    urlpatterns += [
        path("dingtalk/oa/", include(("sql.extensions.dingtalk_oa.urls", "dingtalk_oa"), namespace="dingtalk_oa")),
    ]

## CUSTOM-MODIFIED: gh-ost 无锁 DDL 二次开发 —— 接入 URL 路由 @ 2026-08-05 @ mavis
## 关联设计: docs/designs/2026-08-05_gh-ost-product-design.html
## alpha 阶段不接前端 Vue，进度面板用 Django template（admin 内部可访问）
if getattr(settings, "CUSTOM_GH_OST_ENABLED", False):  # pragma: no cover
    urlpatterns += [
        path("gh_ost/", include(("sql.extensions.ddl_gh_ost.urls", "ddl_gh_ost"), namespace="ddl_gh_ost")),
    ]

handler400 = views.bad_request
handler403 = views.permission_denied
handler404 = views.page_not_found
handler500 = views.server_error
