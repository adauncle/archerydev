# D35 实战新发现 #4: base.html ddl_sync menu 位置错 (9/8 17:14 业务方反馈驱动)

> **日期**: 2026-09-08 17:14
> **触发**: 业务方 (mkq 业务方) 登录后访问 `/sqlworkflow/`, 左侧菜单不显示 "DDL 跨库同步" 菜单
> **截图**: `/admin/auth/group/3/change/` DBA 组已授权 12 个 ddl_sync perm (含 view_ddlsyncpair), 但 mkq 登录后左侧菜单没显示

## 根因 (9/8 17:14 排查锁定)

D35 push Step 4 加 ddl_sync menu 时, 找的位置是 `{% endif %}` + `{% if perms.sql.menu_query %}`, 实际 110 prod base.html 里有两个匹配:
1. **dropdown-user 块尾部** (line 84 之后) ← 实际匹配
2. **sidebar 块 SQL 查询菜单前** (line 168 之后) ← 应该是这个

D35 push 脚本用的是 `re.search` + `(?=...)` lookahead, 默认找**第一个匹配**, 实际找到的是 dropdown-user 块 (用户头像下拉), 不是 sidebar 块 (左侧主菜单).

业务方刷新页面后:
- 右上角用户头像下拉菜单 - 加了 "DDL 跨库同步" 但因为位置深, 不显眼
- 左侧主菜单 - 没显示 (D35 push 加错位置)

mkq 用户的 perm 全部 OK (`has_perm("ddl_sync.view_ddlsyncpair"): True` + groups=`['DBA', 'DBA执行']`), 根因 100% 锁定是 menu 位置错.

## 修法 (9/8 17:16 修复 PASS)

1. 删 110 prod base.html line 78-85 (dropdown-user 块的 ddl_sync menu, 362 字符)
2. 在 line 148 之后 (gh-ost 任务 menu `{% endif %}` 之后, sidebar 块内) 加 dropdown style ddl_sync menu (433 字符)
3. 拉新 gunicorn 6 进程, /login/ 200

最终 110 prod base.html line 147-167 (跟 134 dev 一致, dropdown style):
```html
{# CUSTOM-MODIFIED: DDL 跨库同步 菜单 @ 2026-09-08 @ mavis #}
{# 守卫: superuser 或有 ddl_sync.view_ddlsyncpair 权限 #}
{% if user.is_superuser or perms.ddl_sync.view_ddlsyncpair %}
    <li>
        <a href="#"><i class="fa fa-exchange fa-fw"></i> DDL 跨库同步<span class="fa arrow"></span></a>
        <ul class="nav nav-second-level collapse">
            <li>
                <a href="{% url 'ddl_sync:pair_list' %}"><i class="fa fa-list fa-fw"></i> 库对列表</a>
            </li>
        </ul>
        <!-- /.nav-second-level -->
    </li>
{% endif %}
```

## 教训

D35 push 脚本 Step 4 (commit `8417c5e` 内含修复) 改用:
- 找 `gh-ost 任务 menu 的 {% if user.is_superuser or perms.ddl_gh_ost.view_ddlghosttask %}...{% endif %}` 完整块
- 替换: 在 gh-ost 任务 menu 后加 ddl_sync menu (sidebar 块, 跟 134 dev 一致)
- 用 dropdown style (跟 134 dev 风格统一, 不是简单版 `<li><a>...</a></li>`)

下次推 110 prod 必演练 4 大步, base.html 必验证:
- 业务方登录后左侧菜单能看到 ddl_sync 父菜单 + 库对列表子菜单
- 不能只验 `curl /login/ 200` + `curl /ddl_sync/ 302`, 那是路由生效, 跟菜单显示无关

## 实战 changelog 同源 entry

- 实战脚本: `scripts/_archive/_d35_check_menu_perm.py` (查 mkq perm + base.html 引用)
- 实战脚本: `scripts/_archive/_d35_check_mkq_v2.py` (用 sql.models.Users 查 mkq)
- 实战脚本: `scripts/_archive/_d35_view_base.py` (看 base.html ddl_sync 位置)
- 实战脚本: `scripts/_archive/_d35_fix_base_menu.py` (第一次修, dropdown-user 块删 + sidebar 块加简单版)
- 实战脚本: `scripts/_archive/_d35_fix_base_menu_v2.py` (第二次修, 升级到 dropdown style 跟 134 dev 一致)
- 实战脚本: `scripts/_archive/_d35_view_sidebar.py` (看 sidebar 块结构)
- 修法 commit: `0381368` + `8417c5e` + 后续
