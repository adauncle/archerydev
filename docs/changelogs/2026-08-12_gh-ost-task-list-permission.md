# gh-ost 任务管理列表页权限组细分 (2026-08-12)

## 症状

gh-ost 任务管理列表页 (`/gh_ost/admin_list/`) 守卫是 `is_superuser or perms.sql.sql_review`,
跟其他 SQL 菜单 (SQL上线 / SQL查询 / 实例管理) 一样宽, 无法按"组"细分:

- 8/12 用户反馈: 研发 / 测试同学登录后都能看到 gh-ost 任务菜单, 但实际只 DBA 关心这个运维入口
- 当前守卫 `perms.sql.sql_review` 在 Archery 里是"SQL 审核权" (DBA 大多绑定), 用它当菜单守卫太粗,
  跟 RD 角色无法区分
- 用户在 Django admin 看到"GH-OST 无锁 DDL (内部定制) > Gh-ost 任务"分类下有 4 个标准 perm
  (Can add/change/delete/view gh-ost 任务), 但产品级入口没用到, 形同虚设

**根因**: v0.3.0-beta 加 admin_list 视图时只塞了 `@login_required` + superuser 守卫,
没把权限组细分当成独立产品需求做。

## 修法 (C 方案, 0 DB 改动)

**核心思路**: Django admin 自动给所有 Model 注册 4 个标准 perm (view/add/change/delete),
`DdlGhostTask` 也不例外。直接复用 `ddl_gh_ost.view_ddlghosttask` 这个 perm,
DBA 在 admin 后台点权限组勾选即生效, 无需 migration / 无需建表。

### 改 1: 视图层加 perm 守卫

文件: `sql/extensions/ddl_gh_ost/views.py` (admin_list 视图)

```python
from django.core.exceptions import PermissionDenied

@login_required
@require_GET
def admin_list(request: HttpRequest) -> HttpResponse:
    """gh-ost 任务管理列表页 (DBA 运维入口).
    ...
    权限: 需 ``ddl_gh_ost.view_ddlghosttask`` 权限 ...
    """
    from django.db.models import Q

    # 0. perm 守卫 (跟其他 SQL 页面一致, 可在 admin 后台分配)
    if not request.user.has_perm("ddl_gh_ost.view_ddlghosttask"):
        logger.warning(
            "用户 %s 访问 /gh_ost/admin_list/ 被拒: 无 view_ddlghosttask 权限",
            request.user.username,
        )
        raise PermissionDenied("您没有查看 gh-ost 任务管理列表的权限, 请联系 DBA 在 admin 后台权限组中分配。")
    ...
```

### 改 2: 模板层菜单守卫细化

文件: `common/templates/base.html` (第 124 行, gh-ost 任务顶级菜单)

```django
{# 守卫: superuser 或有 ddl_gh_ost.view_ddlghosttask 权限 #}
{# 分配方式: DBA 在 admin 后台 /admin/auth/group/<id>/change/
            把"Can view gh-ost 任务"勾到目标组 (Django admin 自动注册的标准 perm) #}
{% if user.is_superuser or perms.ddl_gh_ost.view_ddlghosttask %}
    <li>
        <a href="#"><i class="fa fa-rocket fa-fw"></i> gh-ost 任务<span class="fa arrow"></span></a>
        <ul class="nav nav-second-level collapse">
            <li>
                <a href="/gh_ost/admin_list/"><i class="fa fa-list fa-fw"></i> 任务管理</a>
            </li>
        </ul>
    </li>
{% endif %}
```

**关键点**: 之前用 `perms.sql.sql_review` (太宽, RD 也可能有),
现在改 `perms.ddl_gh_ost.view_ddlghosttask` (Django admin 自动注册, 0 成本)。

### 改 3 (配套, 不在 commit 里): DBA 在 admin 后台分配

用户测试: 给"研发"组勾上"Can view gh-ost 任务" → 研发也能看;
不勾 → 研发看不到菜单 + 访问 URL 403。

操作路径: `/admin/auth/group/<group_id>/change/` → 左侧可用权限区找
"gh-ost 任务 > Can view gh-ost 任务" → 点 → 保存。

## 验证

### 134 dev 真表演练 4 Case

| Case | 角色 | 守卫 | 期望 | 实测 |
|------|------|------|------|------|
| A | superuser (archery) | 自动通过 | 200 + 菜单显示 | 200 OK + 菜单显示 |
| B | mkq (DBA 组, 有 view perm) | has_perm ✓ | 200 + 菜单显示 | 200 OK + 菜单显示 |
| C | oa_tester_1 (RD 组, 无 perm) | has_perm ✗ | 403 + 菜单不显示 | 403 + 菜单消失 |
| D | gyf (其他组, 无 perm) | has_perm ✗ | 403 + 菜单不显示 | 403 + 菜单消失 |

### 134 dev 演练脚本

`scripts/drill_admin_list_perm.py`:

- 登录 mkq → 访问 `/gh_ost/admin_list/` → 200, 列表显示
- 登录 oa_tester_1 → 访问 `/gh_ost/admin_list/` → 403, 中文提示"请联系 DBA 在 admin 后台权限组中分配"
- 登录 oa_tester_1 → 看 base.html 渲染 → "gh-ost 任务"菜单不出现
- DBA 在 admin 给"研发"组勾上 "Can view gh-ost 任务" → 重新登录 oa_tester_1 → 200 + 菜单出现

### 134 dev 浏览器用户验证 (2026-08-12)

- 用户用 oa_tester_1 (RD 角色, 无 perm) 登录 → 侧边栏**没有**"gh-ost 任务"菜单 ✓
- 手工访问 `/gh_ost/admin_list/` → **403 页面**显示中文提示 ✓
- DBA 在 admin 后台给"研发"组勾上"Can view gh-ost 任务" → oa_tester_1 重新登录
  → 菜单出现 + 访问 200 ✓

## 影响

- **正面**: 跟其他 SQL 页面菜单的权限模型对齐, DBA 可在 admin 后台自由分配
- **零 DB 改动**: 复用 Django admin 自动注册的标准 perm, 无 migration
- **零代码改动 (分配侧)**: DBA 在 admin 后台点勾选即生效, 不用改 settings / 不用重启
- **superuser 不受影响**: `is_superuser` 自动通过, 仍可访问
- **细节改进**: PermissionDenied 抛错 + logger.warning 写日志 + 中文提示 (跟其他 403 一致)

## 相关 commits / changelogs

- 前置: `47728bb` gh-ost 任务管理列表页 (引入 admin_list 视图, 但守卫太宽)
- 前置: `1f32976` v0.3.x 字段 diff 检测
- 前置: `fba0564` 字段 diff 补全 SQL + 一键复制
- 配套: `d99c7bf` Excel v3 17 条追加 (含"权限组细分"产品改进)
- 本次 commit: 任务列表 perm 守卫 (view_ddlghosttask)

## 产品决策记录

- **决策**: gh-ost 任务管理列表页跟 SQL 上线 / SQL 查询等菜单**对齐权限模型**,
  用 Django admin 标准 perm 守卫, 不写死 superuser / sql_review
- **决策时间**: 2026-08-12 17:05 (用户在 admin 后台截图, 确认 4 个 perm 已自动注册)
- **决策人**: 阿达叔叔 (产品) + mavis (执行)
- **替代方案 A** (否决): 加一个新的业务 perm `sql.gh_ost_manage` 在 settings.py 写死
  → 维护成本高, 跟 Django 习惯不符
- **替代方案 B** (否决): 复用 `perms.sql.sql_review`, 不细粒度
  → 用户明确反馈需要细粒度, 跟其他页面齐
- **选定 C**: Django admin 自动注册 perm + 视图/模板双守卫
