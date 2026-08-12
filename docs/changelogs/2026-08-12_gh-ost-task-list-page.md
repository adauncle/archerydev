# 2026-08-12 · gh-ost 任务管理列表页（产品级入口）

> **作者**: mavis · **关联**: 设计稿 `docs/designs/2026-08-05_gh-ost-product-design.html` v0.3.0 §"DBA admin 列表页"
> **触发场景**: 8/12 用户浏览器验证时反馈 — "DBA admin 多一个 ext_ddl_ghost_task 列表页（取消/重试/回滚）" 这个列表页没有

## 一句话

Django admin 后台有 `ext_ddl_ghost_task`（DBA 入口隐藏太深），本次把它"提到产品级"——Archery 主侧边栏加 **gh-ost 任务** 顶级菜单，列表 + 状态统计 + 取消/重试/回滚一站式。

## 触发场景

设计图 v0.3.0-BETA 第 4 项原文：
> DBA admin 多一个 ext_ddl_ghost_task 列表页（取消/重试/回滚）

8/12 用户 134 dev 浏览器验证后反馈："这个列表页没有"。

排查发现：
- ✅ Django admin 后台 `/admin/ddl_gh_ost/ddlghosttask/` 实际上有完整列表 + 4 个 action（取消/重试/回滚/批量重建）
- ❌ 但在 Archery 主界面没有入口，DBA 不知道去 admin 后台翻
- ❌ 实际意义：列表页"有"但产品级"没有"

## 根因

- 早期只注册了 `@admin.register(DdlGhostTask)`（Django admin 标准做法）
- 没在 Archery 主侧边栏加产品级菜单入口
- `is_admin_user = request.user.is_superuser` 守卫让普通 DBA 不愿意进 admin 后台

## 修法

### 修 1：新增产品级 gh-ost 任务管理页面

- URL: `GET /gh_ost/admin_list/`
- 视图: `sql/extensions/ddl_gh_ost/views.py` `admin_list(request)` 视图
- 模板: `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/task_list.html`
- URL 路由: `sql/extensions/ddl_gh_ost/urls.py` `path("admin_list/", views.admin_list, name="admin_list")`

**功能**：
- 4 张状态统计卡：总任务数 / 进行中 / cut-over 成功 / 失败/回滚
- 筛选器：任务类型 (ghost/rebuild) + 状态 (active/success/failed/cancelled) + 关键字搜索
- 列表表格：每行显示任务 #、类型 tag、状态 badge、工单 + DB.表、进度条、启动/结束时间、操作按钮
- 操作按钮根据 task 状态动态显示：
  - 任何状态 → "查看"按钮 (跳 progress 页)
  - active (queued/running/cut_over/precheck_failed) → "取消"按钮
  - failed/cancelled → "重试"按钮
  - success + task_type=ghost → "回滚"按钮 (drop 影子表)
- AJAX 操作：取消/重试/回滚走 fetch 异步，调现有 `cancel/retry/rollback` 端点，刷新页面

### 修 2：Archery 主侧边栏加菜单入口

- 文件: `common/templates/base.html`
- 守卫: `{% if user.is_superuser or perms.sql.sql_review %}` (superuser + 有审阅权限的 DBA 都看到)
- 菜单: **gh-ost 任务** 顶级菜单（fa-rocket 图标）→ 子菜单 "任务管理" 链 `/gh_ost/admin_list/`
- 位置: 插在 "SQL审核" 之后，"SQL查询" 之前 (gh-ost 跟 SQL 审核是 DDL 紧密相关)

### 修 3：Django 模板 smartif 语法坑

- 错误写法: `{% if user.has_perm("sql.sql_review") %}` — 报 `Could not parse the remainder: '("sql.sql_review")'`
- 正确写法: `{% if perms.sql.sql_review %}` (Django 模板的 perms 字典访问语法)
- 原因: Django 模板 smartif parser 不接受带双引号参数的函数调用

## 134 dev 端到端验证

用 Django test client 测：

```
GET /gh_ost/admin_list/  →  200 (98KB)
  - 32 个 wf-link (DdlGhostTask 32 条)
  - 状态统计 4 个卡全在
  - 状态 badge 颜色正确
  - 进度条渲染正确 (progress_pct 字段)

GET / (follow → /sqlworkflow/)  →  200
  - 'gh-ost 任务' 1 次 ✓
  - 'gh_ost/admin_list' 1 次 ✓
  - 'fa-rocket' 1 次 ✓ (菜单图标)
```

## 变更文件清单

| 文件 | 变更 |
|------|------|
| `sql/extensions/ddl_gh_ost/views.py` | 新增 `admin_list` 视图 (+50 行) |
| `sql/extensions/ddl_gh_ost/urls.py` | 加 `path("admin_list/", ...)` |
| `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/task_list.html` | 新建 (~250 行) |
| `common/templates/base.html` | 侧边栏加"gh-ost 任务"菜单 |

## 110 prod 推 v0.3.0-beta 时同步

- 无 schema 变更
- 无 env var 新增
- 4 文件直接 include 进 tarball 即可

## 关联

- `docs/designs/2026-08-05_gh-ost-product-design.html` §v0.3.0 完整版 "DBA admin 列表页"
- `docs/changelogs/2026-08-11_gh-ost-dba-fallback.md` (DBA 兜底 + 大表 DDL 防呆)
