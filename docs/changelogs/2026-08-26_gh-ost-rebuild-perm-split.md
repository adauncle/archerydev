# 8/26 gh-ost 任务 / 碎片回收 菜单拆 perm 独立分配

> **时间**: 2026-08-26 22:16
> **作者**: mavis
> **commit**: TBD
> **影响范围**: 134 dev ✅ 验证 PASS / 110 prod 跟推
> **类型**: feat (DBA 权限细分)

---

## 一、需求背景

8/26 22:14 阿达叔叔反馈：

> "目前是分配一个 gh-ost view 权限给到组，用户就会看到 gh-ost 所有功能菜单。
> 需求是：gh-ost 任务-碎片回收菜单要独立分配。我不想让开发看到碎片回收页面。"

**业务场景**：
- **gh-ost 任务管理**（业务 RD 提单）—— 业务 RD 需要看到自己的工单进度
- **碎片回收**（DBA 专用运维工具）—— 业务 RD 根本不需要也不应该看到

**8/26 之前的状态**：
- `DdlGhostTask.Meta.permissions` 只有 Django 自动注册的 4 个标准 perm（view/add/change/delete ddlghosttask）
- 业务 RD 拿 `view_ddlghosttask` 后，base.html 父菜单"gh-ost 任务"下 2 个子菜单（任务管理 + 碎片回收）都显示
- 业务 RD 拿 `view_ddlghosttask` 后，4 个 rebuild 端点 perm 守卫是 `view_ddlghosttask`，业务 RD 也能访问（虽然 8/25 拍板时是 DBA 专用）

---

## 二、解决方案 (A 方案拍板)

**Meta.permissions 加 2 个新 perm**：
- `view_ddlghosttask_rebuild` —— "Can view gh-ost 碎片回收"
- `add_ddlghosttask_rebuild` —— "Can add gh-ost 碎片回收"

**修法**：
1. `models.py` Meta.permissions 加 2 个新 perm
2. `base.html` 父菜单"gh-ost 任务"下的子菜单"碎片回收"，perm 守卫从 `view_ddlghosttask` 改成 `view_ddlghosttask_rebuild`
3. `views.py` 4 个 rebuild 端点（rebuild_list / rebuild_status / rebuild_progress_page / rebuild_select_page）perm 守卫从 `view_ddlghosttask` 改成 `view_ddlghosttask_rebuild`
4. 4 个端点错误文案改"碎片回收"
5. 5 步必做 步骤 10 加 2 个新 perm idempotent 创建（跟 8/13 4 perm 同样模式）

**保留 4 个老 perm 不动**（add_ddlghosttask / change_ddlghosttask / delete_ddlghosttask / view_ddlghosttask），业务 RD 还能正常用任务管理菜单。

---

## 三、代码改动清单

### 1. `sql/extensions/ddl_gh_ost/models.py` Meta.permissions

```python
## CUSTOM-MODIFIED: 8/26 碎片回收独立 perm 拆分 @ 2026-08-26 @ mavis
## 业务: gh-ost 任务 (业务 RD 提单) 跟 碎片回收 (DBA 专用) 在业务上完全分离,
##      业务 RD 不应该看到碎片回收页面 (不需要也用不到)
## 8/26 之前: 业务 RD 拿 view_ddlghosttask 后, 父菜单"gh-ost 任务"下 2 个子菜单都显示
## 8/26 修法: 加 2 个新 perm, 业务 RD 拿 view_ddlghosttask 但不拿 view_ddlghosttask_rebuild,
##      只看"任务管理"菜单, 看不到"碎片回收"菜单
## 关联 changelog: docs/changelogs/2026-08-26_gh-ost-rebuild-perm-split.md
permissions = (
    ("view_ddlghosttask_rebuild", "Can view gh-ost 碎片回收"),
    ("add_ddlghosttask_rebuild", "Can add gh-ost 碎片回收"),
)
```

### 2. `common/templates/base.html` 菜单守卫 (line 142)

```html
{# 8/26 22:16 拆 perm 独立分配: 改用 view_ddlghosttask_rebuild 守卫 #}
{# 分配: DBA 在 admin 后台 /admin/auth/group/ 勾选 "Can view gh-ost 碎片回收" #}
{% if user.is_superuser or perms.ddl_gh_ost.view_ddlghosttask_rebuild %}
    <li>
        <a href="/gh_ost/rebuild/select/"><i class="fa fa-magic fa-fw"></i> 碎片回收</a>
    </li>
{% endif %}
```

### 3. `sql/extensions/ddl_gh_ost/views.py` 4 个端点 perm 守卫

| 端点 | 行号 | 修法 | 文案 |
|------|------|------|------|
| `rebuild_list` | 614 / 643 | `view_ddlghosttask` → `view_ddlghosttask_rebuild` | 403 JSON "您没有查看碎片回收表列表的权限..." |
| `rebuild_progress_page` | 903 / 913 | 同上 | raise PermissionDenied "您没有查看 gh-ost 任务进度的权限..." |
| `rebuild_status` | 926 / 940 | 同上 | 403 JSON "您没有查看 gh-ost 任务状态的权限..." |
| `rebuild_select_page` | 1125 / 1148 | 同上 | raise PermissionDenied "您没有访问碎片回收页面的权限..." |

**AJAX 端点**（rebuild_list / rebuild_status）返 403 JSON，**不能用 raise**（8/13 教训：raise 会让前端 AJAX 拿到整页 HTML 源码）。
**render 端点**（rebuild_select_page / rebuild_progress_page）用 raise PermissionDenied，跟 admin_list 一致。

### 4. `scripts/deploy/5step_prerequisites_110prod.sh` 步骤 10

```bash
# === 步骤 10: gh-ost 6 perm 预创建 (8/13 commit 0004 4 perm + 8/26 commit 2 perm) ===
echo "=== 步骤 10: gh-ost 6 perm 预创建 (8/13 + 8/26 拆 perm 5 步必做流程) ==="
echo "目的: 8/13 commit 0004 创建 4 个 perm: view/add/change/delete ddlghosttask"
echo "      8/26 commit 22:16 拆 perm 独立分配, 加 2 个新 perm:"
echo "        - view_ddlghosttask_rebuild (Can view gh-ost 碎片回收)"
echo "        - add_ddlghosttask_rebuild (Can add gh-ost 碎片回收)"
echo "      推 110 跑 migrate 后, 5 步必做 idempotent 检查这 6 个 perm 存在"
```

`for codename, name in [...]` 列表从 4 perm 扩到 6 perm。

---

## 四、134 dev 演练结果 (8/26 22:50)

### 演练脚本: `scripts/_archive/_drill_134_20260826_2225_permsplit.py`

### 步骤 1: 5 步必做 步骤 10 idempotent 创建 6 perm

```
ContentType: id=58 app_label=ddl_gh_ost model=ddlghosttask
perm 总数: 6
  - add_ddlghosttask: Can add gh-ost 任务
  - add_ddlghosttask_rebuild: Can add gh-ost 碎片回收  ← 新
  - change_ddlghosttask: Can change gh-ost 任务
  - delete_ddlghosttask: Can delete gh-ost 任务
  - view_ddlghosttask: Can view gh-ost 任务
  - view_ddlghosttask_rebuild: Can view gh-ost 碎片回收  ← 新
```

id=262, 263 是新 perm。

### 步骤 2: 业务 RD mkq 拿 4 老 perm 不拿 2 新 perm

```
[测试用户] mkq (id=2, is_superuser=False)
  分配 4 个老 perm: ['add_ddlghosttask', 'change_ddlghosttask', 'delete_ddlghosttask', 'view_ddlghosttask']
  不分配 2 个新 perm (view_ddlghosttask_rebuild / add_ddlghosttask_rebuild)

  has_perm("view_ddlghosttask")        = True  (期望 True)
  has_perm("view_ddlghosttask_rebuild") = False (期望 False)
  has_perm("add_ddlghosttask_rebuild")  = False  (期望 False)
  [PASS] 业务 RD perm 状态符合预期

  [base.html 菜单渲染]
    gh-ost 任务菜单可见
  ← 注意: "碎片回收菜单可见" 没出现 (因为没拿新 perm)
```

### 步骤 3: Django test client 验证 URL perm 守卫

```
[测试 1] GET /gh_ost/admin_list/  (期望 200, view_ddlghosttask=True)
    实际 status_code: 200
    [PASS] 任务管理页可访问

[测试 2] GET /gh_ost/rebuild/select/  (期望 403, view_ddlghosttask_rebuild=False)
    实际 status_code: 403
    [PASS] 碎片回收页 403, perm 守卫正确拦截

[测试 3] GET /gh_ost/rebuild/list/?instance_id=5  (期望 403 JSON, AJAX 端点)
    实际 status_code: 403
    Content-Type: application/json
    Body 头: {"ok": false, "error": "您没有查看碎片回收表列表的权限..."}
    [PASS] 返 403 JSON, AJAX 不会拿到整页 HTML (8/13 教训应用)
```

**全部 PASS** ✅

---

## 五、推 110 物料清单 (下次推 prod 时)

| 文件 | 大小 | 改动 |
|------|------|------|
| `sql/extensions/ddl_gh_ost/models.py` | 12,918 B | Meta.permissions 加 2 perm |
| `sql/extensions/ddl_gh_ost/views.py` | 62,350 B | 4 端点 perm 守卫 + 错误文案 |
| `common/templates/base.html` | 34,709 B | 菜单守卫 view_ddlghosttask_rebuild |
| `scripts/deploy/5step_prerequisites_110prod.sh` | +0.3 KB | 步骤 10 加 2 perm |

**5 步必做步骤 10** 在推 110 跑 `migrate` 后必跑，会 idempotent 创建 6 perm（已存在 4 perm + 新建 2 perm）。

---

## 六、关联

- **同源需求**: 8/12 gh-ost 任务管理列表页（`2026-08-12_gh-ost-task-list-page.md`）+ 8/13 gh-ost 4 perm 拆分（`2026-08-13_gh-ost-action-endpoint-perm.md`）+ 8/25 v0.4.5 rebuild 选表页面 perm 守卫（`2026-08-25_v0405-rebuild-perm-guard.md`）
- **关联 changelog**: `docs/changelogs/2026-08-25_v0405-rebuild-perm-guard.md`（8/25 4 端点 perm 守卫）→ 8/26 拆 perm 升级
- **关联 8/13 教训**: Django 模型加 `Meta.permissions` 不会自动创建 perm → 5 步必做 步骤 10 idempotent 手工 INSERT

---

## 七、记忆要点

1. **业务子菜单跟主菜单应该分别 perm 守卫** —— 父菜单用 `view_ddlghosttask` 是合理的（业务 RD 需看任务管理），子菜单"碎片回收"用 `view_ddlghosttask_rebuild`（DBA 专用），DBA 拿全两 perm，业务 RD 拿一半
2. **AJAX 端点返 403 JSON, render 端点 raise PermissionDenied** —— 8/13 教训再次应用
3. **Django Meta.permissions 改动后必须 idempotent 创建 perm** —— 5 步必做 步骤 10 模式（get_or_create）
4. **gunicorn HUP 不重载 Python 代码** —— 8/24 教训再次踩到，本次演练先 HUP 没生效，必须 pkill + nohup 拉新才生效
