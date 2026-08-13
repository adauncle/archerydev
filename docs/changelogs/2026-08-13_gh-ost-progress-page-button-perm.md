# 2026-08-13 gh-ost 进度页守卫 + cancel 端点 JSON 错误码

## 业务背景

8/13 用户截图反馈 `oa_tester_1` (RD, 已分配 `view_ddlghosttask` perm) 视角下:
- **截图 2 (进度面板)**: `/gh_ost/progress/38/` 还能看到"取消迁移"按钮 (本不应该)
- **截图 3 (取消 bug)**: 点"取消迁移"后浏览器 alert 弹了完整 HTML 源码 (`<!DOCTYPE html>...<meta http-equiv="X-UA-Compatible"...>`), 而不是结构化 JSON 错误

## 根因

### 根因 1: progress.html 启动 + 取消按钮没加守卫 (前端缺陷)

之前给 `task_list.html` 列表行加了 `{% if is_admin_or_dba %}` 守卫 (commit `2d27a4a` 8/13),
但 `progress.html` 漏了——`progress.html` 的"启动 gh-ost" / "取消迁移" 按钮直接渲染, 无视 RD 视角。

### 根因 2: `_require_change_perm` raise PermissionDenied → Django 返 403 HTML 错误页 (后端缺陷)

`_require_change_perm` 端点守卫 (commit `eb5937b` 8/13) 实现是 `raise PermissionDenied(...)`。
Django middleware 抓了 `PermissionDenied` 后返默认 403 HTML 错误页 (整页 `<!DOCTYPE html>...` 模板),
而不是 JSON。

前端 `progress.html` 的 `postAction` JS:
```js
if (!r.ok) {
  const t = await r.text();   // ← 这里是整页 HTML 源码
  alert('操作失败：' + t.slice(0, 300));   // ← alert 弹 HTML
}
```

这是 `_require_change_perm` 抛异常的副作用, 适用于所有用 `_require_change_perm` 守卫的端点
(`start` / `cancel` / `retry` / `rollback`)。

### 根因 3: `start` 端点之前根本没加 perm 守卫 (遗漏)

之前 commit `eb5937b` 8/13 只给 `cancel` / `retry` / `rollback` 3 端点加了守卫,
`start` 端点 (line 274) 漏了——任何登录用户都能调 `start` 端点启 gh-ost。

## 修法

### 修法 1: progress.html 启动 + 取消按钮包到 `{% if is_admin_or_dba %}` 守卫

```django
{# CUSTOM-MODIFIED: 启动 + 取消按钮加 is_admin_or_dba 守卫 (DBA 专属) @ 2026-08-13 @ mavis #}
{# 业务: RD 视角 (oa_tester_1) 看进度面板不应该看到运维操作按钮 (start/cancel), #}
{#      跟 task_list.html 列表行 3 按钮 + admin_list 底部提示守卫保持一致。 #}
{# 后端端点也有 change_ddlghosttask 守卫, 这里是前端防御避免 RD 误点触发。 #}
{% if is_admin_or_dba %}
  {% if task.status == "queued" %}
    <button class="btn btn-primary" id="startBtn">启动 gh-ost</button>
  {% endif %}
  {% if task.status in "running,cut_over,queued" %}
    <button class="btn btn-danger" id="cancelBtn">取消迁移</button>
  {% endif %}
{% endif %}
```

### 修法 2: `_require_change_perm` 改 return JsonResponse (status=403) 替代 raise PermissionDenied

```python
def _require_change_perm(request, action: str = ""):
    """gh-ost 任务运维操作端点统一 perm 守卫。

    行为: 没 perm → 返 ``JsonResponse({"ok": False, "error": "..."}, status=403)``
          有 perm → 返 ``None``, 调用方继续执行。
    """
    if not request.user.has_perm("ddl_gh_ost.change_ddlghosttask"):
        logger.warning(
            "用户 %s 访问 gh-ost %s 端点被拒: 无 change_ddlghosttask 权限",
            request.user.username, action or "unknown",
        )
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    f"您没有 gh-ost 任务 {action} 权限。"
                    "请联系 DBA 在 admin 后台 /admin/auth/group/ 权限组中分配 \"Can change gh-ost 任务\"。"
                ),
            },
            status=403,
        )
    return None
```

### 修法 3: 4 端点 (start/cancel/retry/rollback) 统一调用方式

```python
perm_resp = _require_change_perm(request, "start")  # / cancel / retry / rollback
if perm_resp is not None:
    return perm_resp
```

`start` 端点之前没加, 这次补上。

### 修法 4: progress_page 视图加 `is_admin_or_dba` context 变量

```python
is_admin_or_dba = _is_admin_or_dba(request.user)
return render(request, "ddl_gh_ost/progress.html", {
    "workflow": workflow,
    "task": task,
    "is_admin_user": is_admin_user,  # 仅 superuser (admin 详情按钮)
    "is_admin_or_dba": is_admin_or_dba,  # DBA / DBA组长 (运维按钮)
})
```

`_is_admin_or_dba` 跟 admin_list 视图共用 (DBA / DBA组长), 跟 `_require_change_perm` (perm 硬墙) 解耦。

## 演练 (134 dev 4 Case + read-only 零污染)

`scripts/drill_progress_page_perm.py` — 134 dev 真实数据库, 0 数据污染 (cancel POST 用 fake wf_id=999999 测 perm 守卫, progress GET 用真实 queued wf_id=38 测按钮可见性)。

| Case | 用户 | perm | cancel 端点 | 按钮渲染 |
|------|------|------|------------|----------|
| A. superuser | archery | True (superuser) | 404 (perm 通过, task 不存在) | startBtn + cancelBtn ✓ |
| B. DBA | mkq | True (grant) | 404 (perm 通过) | startBtn + cancelBtn ✓ |
| C. **RD** | oa_tester_1 | False | **403 JSON** (perm 不通过) | **startBtn + cancelBtn 全部隐藏** ✓ |
| D. DBA组长 | gyf | True (grant) | 404 (perm 通过) | startBtn + cancelBtn ✓ |

**RD 错误信息** (示例):
```json
{
  "ok": false,
  "error": "您没有 gh-ost 任务 cancel 权限。请联系 DBA 在 admin 后台 /admin/auth/group/ 权限组中分配 \"Can change gh-ost 任务\"。"
}
```

之前 bug 是弹整页 HTML 源码 (`<!DOCTYPE html><html lang="zh-CN">...<meta http-equiv="X-UA-Compatible"...>`), 现在是结构化 JSON 错误。

**清理**: 演练后 mkq / oa_tester_1 / gyf 3 个 user 的 `change_ddlghosttask` perm 全部 revoke 还原; 5 个 queued task 状态保持不变 (用 fake wf_id 没真 cancel)。

## 验证清单

- [x] 134 dev drill 4 Case 全过 (read-only 零污染)
- [x] gunicorn restart 后代码生效
- [x] task 状态 0 变化 (5 个 queued task 完整)
- [ ] **用户浏览器手动验收** (用 oa_tester_1 登录 134 dev 9003, 进 /gh_ost/progress/38/ 应看不到按钮, 直 fetch /gh_ost/cancel/999999/ 应返 403 JSON)

## 风险

- `_require_change_perm` 改 return JsonResponse, 调用方必须接住返回值。如果有别的端点调用, 要同步改。
  - 当前 4 个调用方 (`start` / `cancel` / `retry` / `rollback`) 全部同步改完
- `progress.html` 的 JS `if (cancelBtn) cancelBtn.onclick = ...` 守卫的 null check 保留, RD 视角下按钮不渲染时 JS 不会绑事件

## 同源 entry

- `gh-ost 任务管理列表页 perm 守卫 (C 方案)` commit `c80c1ad` (8/12)
- `gh-ost 任务列表页可见性细分 (DBA 全量 / RD 自己)` commit `727f046` (8/13)
- `gh-ost 任务列表底部 AJAX 提示 (DBA 专属)` commit `2d27a4a` (8/13)
- `gh-ost 任务运维操作端点 perm 守卫 (A 方案)` commit `eb5937b` (8/13)
