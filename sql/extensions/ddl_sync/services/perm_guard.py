"""DDL 跨库同步 4 perm 守卫装饰器 (8/13 教训应用)

## CUSTOM-MODIFIED: v0.5.0-alpha 8/13 教训应用 — require_perm 装饰器 @ 2026-09-01 @ mavis
## 关联: docs/changelogs/2026-09-01_ddl-sync-w2-d9-perm-guard.md

实战避坑 (W1-D3 §7.3 + 8/13 实战):
- 8/13 教训: AJAX 端点 perm 守卫不能 raise PermissionDenied (返 HTML 错误页, 前端用
  `await r.text()` 拿到整页 HTML 源码, alert 弹 `<!DOCTYPE html><html lang="zh-CN">...
  <meta http-equiv="X-Frame-Options"...>` 一脸懵)
- 实战方案: `@permission_required(..., raise_exception=False)` + 自定义 helper
  返 JsonResponse({"ok": False, "error": "权限不足: 需要 ddl_sync.{perm}"}, status=403)
- 调用方 try/except, 不要默认 Django 返 403 HTML 错误页

避坑 (跨项目可复用, 实战 1 条):
1. **必走 require_perm 装饰器**: 不要直接用 `@permission_required(..., raise_exception=True)`,
   必用本文件 `require_perm(perm_codename)` 装饰器, 让 403 返 JSON
2. **端点 perm 命名**: codename 跟 model 名一致, 4 角色判定跟 8/12 gh-ost 复用
3. **3 处统一**: api_views.py (5 AJAX 端点) + 视图模板 (前端守卫) + admin (Django 后台)
"""

from functools import wraps

from django.http import JsonResponse


def require_perm(perm_codename: str):
    """AJAX 端点 perm 守卫 - 返 JsonResponse(403) 不 raise PermissionDenied.

    ## CUSTOM-MODIFIED: 8/13 教训应用 @ 2026-09-01 @ mavis
    实战避坑:
    - 8/13 教训: 默认 Django `@permission_required(raise_exception=True)` 返 403 HTML 错误页
    - 实战: 自定义装饰器返 JsonResponse({"ok": False, "error": "权限不足: 需要 ddl_sync.{perm}"}, status=403)
    - 调用方 try/except, 错误统一弹 toast

    ## 用法
    ```python
    @csrf_exempt
    @require_http_methods(["POST"])
    @require_perm("change_ddlsyncpair")
    def one_click_setup_view(request, pair_id):
        ...
    ```
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.has_perm(f"ddl_sync.{perm_codename}"):
                return JsonResponse(
                    {"ok": False, "error": f"权限不足: 需要 ddl_sync.{perm_codename}"},
                    status=403,
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
