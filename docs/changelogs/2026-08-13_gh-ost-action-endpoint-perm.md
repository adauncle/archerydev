# gh-ost 任务运维操作端点加 perm 守卫 (A 方案) (2026-08-13)

## 症状

8/13 用户截图反馈底部 AJAX 提示行后, 进一步追问: 列表上还有 cancel / retry / rollback
按钮, RD 点了能执行吗? 排查后发现:

- `cancel` / `retry` / `rollback` 3 个端点 (sql/extensions/ddl_gh_ost/views.py) **只有
  `@login_required` 守卫, 没有 perm 守卫**
- 任何登录用户都能 POST 调用, 执行取消 / 重试 / 回滚 gh-ost 任务的副作用操作
- 这意味着即使前端列表页给 RD 隐藏了按钮, RD 仍可以直接调 API

**根因**: 8/12 commit `c80c1ad` 加 view_ddlghosttask perm 守卫时, 漏掉了 3 个
动作端点 (cancel / retry / rollback) 的 perm 守卫, 这些是更高权限的操作,
应跟 view 区分开。

## 修法 (A 方案, 0 DB 改动)

**用户拍板**: A 方案 — 跟 `view_ddlghosttask` 同样套路, 端点加 `change_ddlghosttask` perm 守卫,
DBA 在 admin 后台点勾选即生效。

### 改 1: 后端 helper

文件: `sql/extensions/ddl_gh_ost/views.py` (新增函数)

```python
def _require_change_perm(request, action: str = "") -> None:
    """gh-ost 任务运维操作端点统一 perm 守卫。

    调用方: cancel / retry / rollback 3 端点, 任何登录用户都能访问
            但需要 ddl_gh_ost.change_ddlghosttask 权限才能执行。
    """
    if not request.user.has_perm("ddl_gh_ost.change_ddlghosttask"):
        logger.warning(...)
        raise PermissionDenied("您没有 gh-ost 任务运维操作权限 (cancel/retry/rollback), 请联系 DBA ...")
```

**为什么用 helper**: 3 个端点都需要同一段守卫代码, 提 helper 避免重复 + 统一日志 + 统一提示。

### 改 2: 3 个端点加守卫

文件: `sql/extensions/ddl_gh_ost/views.py`

- `cancel` (line ~479) 开头加 `_require_change_perm(request, "cancel")`
- `retry` (line ~350) 开头加 `_require_change_perm(request, "retry")`
- `rollback` (line ~416) 开头加 `_require_change_perm(request, "rollback")`

每个端点只多 1 行, 守卫在所有业务逻辑前 (包括"task 不存在"检查), 防止 RD 用 404 探测。

### 改 3: 前端按钮按视角隐藏

文件: `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/task_list.html`

```django
{# view 按钮所有有 view_ddlghosttask perm 的用户都可见 #}
<a class="gh-ost-act-btn view mini" ...>...</a>

{# cancel / retry / rollback 按钮只 DBA / 管理员可见 #}
{% if is_admin_or_dba %}
  {% if t.status == "queued" or ... %}
    <button data-act="cancel" ...>...</button>
  {% endif %}
  ...
{% endif %}
```

**view 按钮 vs 操作按钮分离**:
- view: RD 也能看自己 task 进度 (`progress.html` 只读 polling)
- cancel/retry/rollback: 后端硬墙 + 前端隐藏, 双层防御

**与已存在的 `is_admin_or_dba` 上下文变量解耦**:
- `_is_admin_or_dba` (前端列表"看全量 vs 看自己" 角色判定, 跟 group 绑定)
- `_require_change_perm` (端点硬墙, 跟 perm 绑定)
- 列表页可以按角色给某些人看全量, 但端点永远需要 perm
- 同一个用户可能: 能看全量 (DBA) 但没有 change perm (没勾) → 端点 403

## 验证

### 134 dev 真表演练 4 Case (端点 + 前端)

| Case | 用户 | view | cancel POST | retry POST | rollback POST | 前端按钮 (列表页) |
|------|------|------|-------------|-------------|---------------|------------------|
| A | archery (superuser) | 200 | 200 | 200 | 200 | 全部显示 |
| B | mkq (DBA 组) | 200 | 200 | 200 | 200 | 全部显示 |
| C | oa_tester_1 (RD 组) | 200 | **403** | **403** | **403** | 只显示 view |
| D | gyf (DBA组长组) | 200 | 200 | 200 | 200 | 全部显示 |

**端点 POST 测试**: 演练用 status 处于 queued / failed / success 的 task, 调 cancel / retry / rollback,
检查返回码。RD 无 perm 全部 403, DBA / superuser 走业务逻辑。

**前端按钮测试**: 解析 admin_list 页面 body, 统计 cancel / retry / rollback 按钮渲染数:
- RD 视角: 0 个 (全部隐藏)
- DBA 视角: N 个 (按 status 条件渲染)

### 134 dev 演练脚本

`scripts/drill_action_endpoint_perm.py`:
- 给"DBA"/"DBA组长"/"研发" 临时分配 view_ddlghosttask + change_ddlghosttask
- 登录 mkq (DBA, 有 view + change) → 调 3 端点 + 看 body
- 撤销 mkq 的 change perm → 调 3 端点 → 全 403
- 撤销 mkq 的 view perm → 调 admin_list → 403
- 登录 oa_tester_1 (RD, 有 view 无 change) → 调 3 端点 → 全 403
- 清理还原所有 perm

## 影响

- **正面**: 后端是硬墙, RD 怎么点都 403 (即使绕过前端按钮直接 curl 也不行)
- **正面**: 跟 view_ddlghosttask perm 同样的产品模型, DBA 在 admin 后台自由分配
- **零 DB 改动**: 0 migration, 复用 Django admin 自动注册的标准 perm
- **零 settings 改动**: 不需新增 env var
- **前端 + 后端双层防御**: 端点是硬墙, 按钮按视角隐藏是 UX
- **DBA 自由分配**:
  - 默认所有组都没 change perm (DBA 主动勾才能 cancel/retry/rollback)
  - 想让 RD 也能 cancel 自己的? 给"研发"组勾 change_ddlghosttask
  - 想让测试组能 retry? 给"测试"组勾 change_ddlghosttask
- **view 按钮不受影响**: RD 仍能 view 自己 task 进度 (只读操作)

## 边界情况

- **404 探测保护**: perm 守卫在 task 查询前, RD 不知道 task 是否存在 (避免信息泄露)
- **没有 view perm 但有 change perm**: 进不来 admin_list, 但能调端点 — 实际场景不存在 (DBA 都会勾 view)
- **view perm + change perm 同时勾**: view 列表 + 端点执行, DBA 标准操作
- **superuser**: has_perm 永远 True, 自动通过

## 相关 commits / changelogs

- 前置: `c80c1ad` 任务列表页 perm 守卫 (view_ddlghosttask)
- 前置: `727f046` 任务列表页可见性细分 (DBA 全量 / RD 自己)
- 前置: `2d27a4a` 底部 AJAX 提示 + admin 链接 (DBA 视角专属)
- 本次 commit: cancel / retry / rollback 端点加 perm 守卫 (change_ddlghosttask) + 前端按钮按视角隐藏

## 产品决策记录

- **决策**: gh-ost 任务 cancel / retry / rollback 端点加 change_ddlghosttask perm 守卫
- **决策时间**: 2026-08-13 09:33 (用户拍板 A 方案)
- **决策人**: 阿达叔叔 (产品) + mavis (执行)
- **替代方案 A** (选定): 端点加 change_ddlghosttask perm 守卫
  - 跟 view_ddlghosttask 同样套路, 0 DB 改动, DBA 在 admin 后台勾选
  - 端点是硬墙, 前端按钮按视角隐藏
- **替代方案 B** (否决): 端点走 _is_admin_or_dba 判定
  - 不依赖 perm 分配, 但跟 group 强绑定, 不够灵活
- **替代方案 C** (否决): 端点允许 RD cancel 自己提的 (engineer 校验)
  - 需要写 3 段不同逻辑, 太复杂, 跟当前"端点是硬墙"的产品思路不符
