# v0.4.5 rebuild 模块 4 端点 perm 守卫统一 — 8/25 16:09

## 症状 / 背景

8/25 11:00 v0.4.5 选表页面 (方案 B) 上线后, 8/25 16:09 用户问:
"碎片回收页面是不是可以自定义分配给权限组, 跟其他页面一样的逻辑?"

排查发现两个问题:
1. **`rebuild_select_page` 走 `_is_admin_or_dba` group 守卫** (写死 DBA/DBA组长),
   跟 `admin_list` 的 `view_ddlghosttask` perm 守卫**不一致**, 不能 perm 分配
2. **`rebuild_start` 只有 `@login_required`**, 任何登录用户都能 POST 触发 rebuild —
   **安全漏洞** (虽然 8/25 11:00 推 110 前没人知道这接口, 110 prod 推 110 后业务 RD 可能误触发)

8/25 16:09 用户拍板方案 A: **跟 admin_list 对齐, 全部用 perm 守卫**
("权限管控是原则")

## 拍板方案 A

| 端点 | 改前守卫 | 改后守卫 |
|------|---------|---------|
| `rebuild_select_page` (选表页) | `_is_admin_or_dba` group 守卫 | `view_ddlghosttask` perm |
| `rebuild_list` (拉表 JSON) | 只 `@login_required` | `view_ddlghosttask` perm |
| `rebuild_status` (查进度 JSON) | 只 `@login_required` | `view_ddlghosttask` perm |
| `rebuild_progress_page` (进度页) | 只 `@login_required` | `view_ddlghosttask` perm |
| `rebuild_start` (触发 rebuild) | 只 `@login_required` (漏洞) | **`add_ddlghosttask` perm** (更严) |
| 主菜单"碎片回收"链接 | group 守卫 (DBA/DBA组长) | `view_ddlghosttask` perm |

**view vs add**:
- view = 看, 勾上就能进
- add = 触发, 写 task + 启 gh-ost, 必须更严

## 实施

### 1. 4 端点加 perm 守卫 (`views.py`)

```python
# rebuild_select_page (render 端点, raise PermissionDenied 即可, 8/13 教训: 返 403 HTML)
if not request.user.has_perm("ddl_gh_ost.view_ddlghosttask"):
    raise PermissionDenied("您没有访问碎片回收页面的权限, 请联系 DBA ...")

# rebuild_list / rebuild_status (JSON 端点, 不能 raise, 8/13 教训: 否则前端 AJAX 拿到整页 HTML)
if not request.user.has_perm("ddl_gh_ost.view_ddlghosttask"):
    return JsonResponse({"ok": False, "error": "..."}, status=403)

# rebuild_start (触发动作, 更严的 add perm)
if not request.user.has_perm("ddl_gh_ost.add_ddlghosttask"):
    return JsonResponse({"ok": False, "error": "..."}, status=403)

# rebuild_progress_page (render 端点, raise)
if not request.user.has_perm("ddl_gh_ost.view_ddlghosttask"):
    raise PermissionDenied("您没有查看 gh-ost 任务进度的权限, ...")
```

### 2. 主菜单从 group 守卫改 perm (`common/templates/base.html`)

```html
{% comment %} 改前 (group 守卫) {% endcomment %}
{% if user.is_superuser %}
    <li><a href="/gh_ost/rebuild/select/">碎片回收</a></li>
{% else %}
    {% for g in user.groups.all %}{% if g.name == "DBA" or g.name == "DBA组长" %}
        <li><a href="/gh_ost/rebuild/select/">碎片回收</a></li>
    {% endif %}{% endfor %}
{% endif %}

{% comment %} 改后 (perm 守卫, 跟"gh-ost 任务"菜单一致) {% endcomment %}
{% if user.is_superuser or perms.ddl_gh_ost.view_ddlghosttask %}
    <li><a href="/gh_ost/rebuild/select/">碎片回收</a></li>
{% endif %}
```

## 验证 (134 dev 4 case 演练, 16/16 PASS)

```
=== 当前 perm 状态 ===
view perm 在 3 个 group: ['研发', 'DBA', 'DBA组长']   (8/13 演练残留)
add perm 在 0 个 group: []
oa_tester_1 直挂 view: True (v1 演练残留)
oa_tester_1 直挂 add: True (v1 演练残留)

=== 清理后 (演练用) ===
view perm in groups: 0
oa_tester_1 has_perm view: False
oa_tester_1 has_perm add: False

Case 1: superuser archery (4 端点全 OK)
  [PASS] SELECT 200, LIST 200, START 200 (perm 过), STATUS 200

Case 2: RD oa_tester_1 无 perm (4 端点全 403)
  [PASS] SELECT 403, LIST 403 JSON, START 403 JSON (防误触发), STATUS 403 JSON

Case 3: RD 加 view perm (SELECT/LIST/STATUS 200, START 403)
  [PASS] SELECT 200 (view 够), LIST 200, START 403 (view 不够, 要 add), STATUS 200

Case 4: RD 加 add perm (4 端点全过 perm 守卫)
  [PASS] SELECT 200, LIST 200, START 500 (perm 过, gh-ost 启动失败算业务问题, 不是 perm 守卫), STATUS 200

=== 恢复 134 dev 原始 perm 状态 ===
恢复: 3 group 加回 view, 0 group 加回 add
恢复: oa_tester_1 user view=True, add=True
```

## 推 110

- 134 dev push + kill master (12469 → 4357) + /login/ 200 OK
- 110 prod 默认所有 group 都没 ddl_gh_ost perm, RD 默认全部 403 (跟改前一致, 推 110 后行为不变)
- DBA 在 110 prod admin 后台 /admin/auth/group/ 勾 perm 就能分配谁看/谁触发
- 8/27 推 110 范围已包含

## 教训 (跨项目可复用)

1. **"权限管控是原则"** (用户 8/25 16:09 原话): 新功能 perm 守卫要跟其他模块统一, 不要走"特殊 group 守卫"捷径
2. **view vs add 区分**: "看"用 view perm, "做"用 add/change perm, 触发动作永远比查看更严
3. **render 端点用 raise PermissionDenied, JSON 端点用 JsonResponse 403** (8/13 教训: AJAX 拿到整页 HTML 源码会弹 alert)
4. **演练要清残留 perm**: 134 dev 之前 DBA 在 admin 后台勾过 perm 给"研发"组 + 演练脚本可能给 oa_tester_1 加 user 直挂 perm, 演练前必须清理, 演练后必须还原, 否则测不出真守卫
5. **演练用 perm 反查 + 备份还原**: `Group.objects.filter(permissions=PERM)` 拿所有有 perm 的 group, 备份 list, 演练完 `g.permissions.add(PERM)` 还原
6. **Case 4 START 500 不算 perm 守卫 bug**: gh-ost 启动可能因环境问题失败, 演练只看 "perm 守卫没拒" (status != 403), 不看业务是否成功

## 关联

- v0.4.5 选表页面: `docs/changelogs/2026-08-25_v0405-rebuild-select-page.md`
- admin_list 守卫: `docs/changelogs/2026-08-12_gh-ost-task-list-permission.md`
- 8/13 cancel perm: `docs/changelogs/2026-08-13_gh-ost-action-endpoint-perm.md`
- 演练脚本: `scripts/_archive/_drill_perm_guard_4case_v3.py`
- 134 dev 演练日志: `cat /tmp/drill_perm_guard_v3.log` (本地 v3 跑完)
