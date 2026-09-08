# D35 实战新发现 #5: base.html ddl_sync menu 位置踩坑第 2 次 (9/8 17:47 业务方反馈)

> **日期**: 2026-09-08 17:47
> **触发**: 业务方 mkq 硬刷后看到菜单, 但 DDL 跨库同步菜单 **嵌套在 gh-ost 任务 menu 的子菜单里** (不是平级)
> **根因**: D35 push 脚本 + 我 17:16 修法都用了 `non-greedy [\s\S]*?{% endif %}` 找 gh-ost 任务 menu 关闭, 但 gh-ost 任务块内有 2 个 `{% endif %}` (内层碎片回收 + 外层 gh-ost 任务), non-greedy 找的是内层碎片回收 `{% endif %}`, 加错位置

## 实战时间线 (踩坑全链路)

| 时间 | 事件 | 菜单位置 |
|---|---|---|
| 9/8 16:36 | D35 push Step 4 加 ddl_sync menu (non-greedy) | 嵌套 gh-ost 任务 (line 146) |
| 9/8 17:14 | 业务方反馈"看不到 DDL 跨库同步菜单" | 实际是渲染 OK, mkq 浏览器缓存 |
| 9/8 17:16 | 修 #1 (用同样 non-greedy pattern) | 嵌套 gh-ost 任务 (line 148) |
| 9/8 17:34 | 渲染检查 PASS, 告诉业务方硬刷 | 业务方硬刷 |
| 9/8 17:47 | 业务方硬刷后看到菜单, 但位置错 (嵌套) | 嵌套 gh-ost 任务 (实际渲染) |
| 9/8 17:50 | 修 #2 (清 2 份 menu + 加 1 份平级) | 错! 同时删了 gh-ost 任务关闭, 模板渲染会出错 |
| 9/8 17:55 | 修 #3 (恢复 gh-ost 任务关闭 + 加 1 份平级) | ✅ 平级 (line 151-167) |

## 根因深度分析

### 110 prod base.html gh-ost 任务 menu 完整结构 (line 130-150):
```html
{% if user.is_superuser or perms.ddl_gh_ost.view_ddlghosttask %}     ← 外层 if
    <li>
        <a href="#">gh-ost 任务</a>
        <ul class="nav nav-second-level collapse">
            <li>任务管理</li>
            {% if user.is_superuser or perms.ddl_gh_ost.view_ddlghosttask_rebuild %}
                <li>碎片回收</li>
            {% endif %}                                                    ← 内层 endif (碎片回收)
        </ul>                                                             ← nav-second-level </ul>
        <!-- /.nav-second-level -->
    </li>
{% endif %}                                                                ← 外层 endif (gh-ost 任务)
```

**关键**: 块内有 2 个 `{% endif %}`. 

### 错误 pattern (踩坑):
```python
pattern = r'({% if user\.is_superuser or perms\.ddl_gh_ost\.view_ddlghosttask %\}[\s\S]*?{% endif %})'
```

`[\s\S]*?` 是 non-greedy, 找最短匹配, 实际找到的是**内层碎片回收 `{% endif %}`** (第一个). 加 ddl_sync menu 在碎片回收 `{% endif %}` 之后, 但在 gh-ost 任务 `{% endif %}` 之前, 嵌套在 gh-ost 任务 ul 块内!

### 134 dev base.html 实战 (D7 admin views 演练 9/1 加的):
134 dev 实际位置 line 151-167, 紧跟 gh-ost 任务 `{% endif %}` (line 150) 之后, 跟 gh-ost 任务平级. 134 dev 是对的, 9/1 演练时人手工加, 没踩这个坑.

### 修法 (D35 push 脚本 Step 4 v3):
```python
pattern = re.compile(
    r'(</ul>\s*<!-- /\.nav-second-level -->\s*</li>\s*{% endif %\})',
    re.DOTALL
)
```

**锚定外层 `{% endif %}` 上下文** (`</ul>` + `<!-- -->` + `</li>` + `{% endif %}`), 不用 `[\s\S]*?` non-greedy. 这样 ddl_sync menu 加在 gh-ost 任务外层关闭之后, 跟 gh-ost 任务平级.

## 业务方验证 (9/8 17:55 PASS)

Django 渲染 for mkq 业务方:
- `has_perm ddl_sync.view_ddlsyncpair: True` ✅
- DDL 跨库同步 出现次数: 1 (期望 1, 平级不是嵌套) ✅
- HTML 输出: DDL 跨库同步 父菜单 + 库对列表 子菜单, 在 gh-ost 任务平级 ✅

## 教训

1. **nested `{% if %}` 块用 `[\s\S]*?` 找配对 `{% endif %}` 100% 踩坑**, 必须用上下文锚定 (前后几行模板) 或 lazy match 配对
2. **D35 push 演练 D32 4 大步 + D34 9 步 dry-run 都没真加 ddl_sync menu** (用 `if False:` 替换 4 大步守卫, 演练 1 干净状态). 真到 9/8 16:32 实战才真加, 第一次实战就踩坑
3. **业务方反馈后 17:34 渲染检查 PASS 但没真用业务方账号看菜单**, 17:47 业务方硬刷才真看到. 验证方式: 不能只 ssh 端渲染, 必真用业务方浏览器看
4. **修法 #2 用了 `re.sub` count=0 删 2 份 menu, 但 `{% endif %}\n` 范围太大**, 连带删了 gh-ost 任务关闭. 修法 #3 才恢复 + 重新加. 教训: 修 base.html 不要用 wide-range regex 删模板块

## 实战脚本

- `scripts/_archive/_d35_fix_menu_v3.py` (修 #2, non-greedy 找错位置 + 删 2 份)
- `scripts/_archive/_d35_fix_menu_v4.py` (修 #3, 清 2 份 + 加 1 份, 但删模板上下文)
- `scripts/_archive/_d35_fix_menu_v5.py` (修 #4, 恢复 gh-ost 任务关闭 + 加 1 份平级 PASS)
- `scripts/_archive/_d35_compare_menu.py` (跟 134 dev 对比)
- `scripts/_archive/_d35_view_state.py` (看 base.html 改后状态)

## 修法 commit

- `d098d43` (17:20 实战新发现 #4 第一次修, 错位)
- `8417c5e` (17:00 D35 push 实战 bug 修复 + changelog)
- 待 commit: D35 push 脚本 Step 4 v3 + 本次 changelog
