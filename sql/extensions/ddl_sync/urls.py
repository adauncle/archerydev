"""DDL 跨库同步 URL 路由

## CUSTOM-MODIFIED: v0.5.0-alpha DDL 跨库同步 urls @ 2026-09-01 @ mavis
设计参考: docs/designs/2026-09-01_ddl-sync-implementation-design.md §2

5 view 端点 (D7 阶段 1):
- /pair/list/ — pair_list
- /pair/create/ — pair_create
- /pair/<int:pair_id>/ — pair_detail
- /pair/<int:pair_id>/edit/ — pair_edit
- /pair/<int:pair_id>/toggle/ — pair_toggle (启用/禁用)

5 AJAX 端点 (D8 阶段 2):
- /pair/<int:pair_id>/compute_diff/ — R2 差集
- /pair/<int:pair_id>/one_click_setup/ — R2 一键配
- /pair/<int:pair_id>/bulk_import/ — R1 批量导入
- /pair/<int:pair_id>/add_table/ — 单张加兜底
- /history/ — 同步历史列表
"""

from django.urls import path

from . import views
from .views import api_views

app_name = "ddl_sync"

urlpatterns = [
    # D7 阶段 1 库对管理 CRUD
    path("pair/list/", views.pair_list, name="pair_list"),
    path("pair/create/", views.pair_create, name="pair_create"),
    path("pair/<int:pair_id>/", views.pair_detail, name="pair_detail"),
    path("pair/<int:pair_id>/edit/", views.pair_edit, name="pair_edit"),

    # D8 阶段 1 5 AJAX 端点
    path("pair/<int:pair_id>/compute_diff/", api_views.compute_diff_view, name="compute_diff"),
    path("pair/<int:pair_id>/one_click_setup/", api_views.one_click_setup_view, name="one_click_setup"),
    path("pair/<int:pair_id>/bulk_import/", api_views.bulk_import_view, name="bulk_import"),
    path("pair/<int:pair_id>/add_table/", api_views.add_table_view, name="add_table"),
    path("history/", api_views.history_list_view, name="history_list"),
]
