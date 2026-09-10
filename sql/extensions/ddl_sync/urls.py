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

1 导出端点 (D33):
- /pair/<int:pair_id>/history_export/ — 同步历史 Excel 导出

## CUSTOM-MODIFIED: v0.6.0-alpha-1 操作日志升级 @ 2026-09-10 @ mavis
## 1.4 同步表增删埋点: 2 个新端点
## 关联: docs/plans/2026-09-10_d35-oplog-roadmap.html 阶段 1.4
- /pair/<int:pair_id>/delete_table/<int:table_id>/ — 删除同步表
- /pair/<int:pair_id>/change_transform_rule/<int:table_id>/ — 改 transform_rule
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

    # v0.6.0-alpha-1 1.4 阶段 同步表增删端点
    path("pair/<int:pair_id>/delete_table/<int:table_id>/", api_views.delete_table_view, name="delete_table"),
    path("pair/<int:pair_id>/change_transform_rule/<int:table_id>/", api_views.change_transform_rule_view, name="change_transform_rule"),

    # D33 同步历史 Excel 导出
    path("pair/<int:pair_id>/history_export/", views.pair_history_export, name="pair_history_export"),
]
