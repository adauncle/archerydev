# gh-ost 任务列表页底部 AJAX 提示 + admin 链接 (DBA 视角专属) (2026-08-13)

## 症状

8/13 用户截图反馈: oa_tester_1 (RD 角色, 提交人视角) 访问
`/gh_ost/admin_list/` 后, 页面底部显示这一行:

> 操作走 AJAX 异步 (cancel/retry/rollback), 完成后自动刷新页面 ·
> Django admin 后台完整版: `/admin/ddl_gh_ost/ddlghosttask/`

期望: **这一行对 RD 隐藏**, 只 DBA / 超级管理员 / DBA 组长能看。

## 根因

8/13 commit `727f046` (可见性细分) 改了头部副标题 + 加"提交人"列, 但漏了底部这一行。
底部这一行包含 2 个 RD 不该看到的信息:

1. **"操作走 AJAX 异步 (cancel/retry/rollback)..."** — 误导性提示, RD 提交人视角没有
   运维操作权, 后端 `cancel` / `retry` / `rollback` 端点目前只有 `@login_required` 没 perm
   守卫, 点了按钮会真的执行 (这是另一个 UX bug, 见"未解决问题"段)
2. **"Django admin 后台完整版: /admin/ddl_gh_ost/ddlghosttask/"** — 技术后台入口,
   暴露给普通 RD 不合适, 防止误入 / 信息泄露

## 修法 (0 DB 改动 / 0 后端改动)

文件: `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/task_list.html` (底部 p 标签)

```django
{# CUSTOM-MODIFIED: 底部 AJAX 提示 + Django admin 链接只 DBA/管理员可见 @ 2026-08-13 @ mavis #}
{% if is_admin_or_dba %}
  <p class="gh-ost-sub" style="margin-top:24px;">
    <i class="fa fa-info-circle"></i>
    操作走 AJAX 异步 (cancel/retry/rollback), 完成后自动刷新页面 · Django admin 后台完整版: <a href="/admin/ddl_gh_ost/ddlghosttask/">/admin/ddl_gh_ost/ddlghosttask/</a>
  </p>
{% endif %}
```

`is_admin_or_dba` 上下文变量已在 `admin_list` 视图 (commit `727f046`) 里传过来, 直接复用,
**0 后端代码改动**。

## 验证

### 134 dev 真表演练 4 Case

| Case | 用户 | 角色 | 期望: 底部这一行 | 实测 |
|------|------|------|-----------------|------|
| A | archery (superuser) | 全权限 | 显示 (含 admin 链接) | ✓ |
| B | mkq (DBA 组) | DBA 视角 | 显示 (含 admin 链接) | ✓ |
| C | oa_tester_1 (研发组) | 提交人视角 | **不显示** | ✓ |
| D | gyf (DBA组长组) | DBA 视角 | 显示 (含 admin 链接) | ✓ |

### 134 dev 演练脚本

`scripts/drill_admin_list_bottom_tip.py`:
- 登录 mkq → 访问 /gh_ost/admin_list/ → body 含 "操作走 AJAX" 和 "/admin/ddl_gh_ost/ddlghosttask/"
- 登录 oa_tester_1 → 访问 /gh_ost/admin_list/ → body **不**含 "操作走 AJAX" 字符串, **不**含 admin 链接
- 登录 archery → 同 mkq
- 登录 gyf → 同 mkq (DBA组长也算 DBA 视角)

### 134 dev 浏览器用户验证

- 用户用 oa_tester_1 登录 → 底部这一行消失 ✓
- 用户用 archery 登录 → 底部这一行还在, admin 链接可点 ✓

## 影响

- **正面**: RD 提交人视角不暴露 Django admin 后台入口, UX 干净
- **正面**: 误导性 "cancel/retry/rollback" 提示不再对没运维权的用户显示
- **零后端代码改动**: 只改模板, 复用现有 `is_admin_or_dba` 上下文
- **零 DB 改动**: 0 migration
- **DBA 视角不受影响**: 底部这一行仍显示, admin 链接仍可点

## 未解决问题 (后续评估)

- **`cancel` / `retry` / `rollback` 后端端点无 perm 守卫**: 当前只有 `@login_required` 守卫,
  意味着任何登录用户都能调这些端点 (虽然前端按钮仅 RD 看到一部分, 但 RD 也能调通)
- **修法选项** (后续如要修, 跟用户拍板):
  - **A**: 端点加 `change_ddlghosttask` perm 守卫 (DBA 在 admin 后台给目标组勾选,
    跟 view 一样 0 DB 改动, 跟现有守卫模式一致)
  - **B**: 端点走 `_is_admin_or_dba` 判定 (跟前端列表一样, 不依赖 perm 分配)
  - **C**: 端点允许 RD cancel 自己提的 (engineer 校验), retry/rollback 仍只 DBA
- **前端按钮的"按视角隐藏"**: 跟选项 A/B/C 配对, 端点禁了什么, 按钮也藏什么
- **本次不修原因**: 用户只问了底部这一行, 操作按钮 + 端点守卫是独立的产品决策
  (RD 应不应该能 cancel 自己提的? 失败后 RD 能不能 retry?), 等用户拍板

## 相关 commits / changelogs

- 前置: `727f046` 任务列表页可见性细分 (DBA 全量 / RD 自己) — 引入了 `is_admin_or_dba` 上下文
- 前置: `c80c1ad` 任务列表页 perm 守卫 (view_ddlghosttask) — 进了页面的门
- 本次 commit: 底部 AJAX 提示 + admin 链接 (DBA 视角专属)

## 产品决策记录

- **决策**: 底部 AJAX 提示 + Django admin 链接只 DBA / DBA 组长 / 超级管理员可见
- **决策时间**: 2026-08-13 09:24 (用户截图反馈底部这一行该隐藏)
- **决策人**: 阿达叔叔 (产品) + mavis (执行)
- **替代方案 A** (否决): 整段删掉, 不分视角
  → DBA 仍需 admin 链接, 而且操作说明对 DBA 有用
- **替代方案 B** (否决): 移到 "系统管理" 顶级菜单下, 跟其他 admin 链接一起
  → 这个链接是 gh-ost 列表页的"扩展入口", 跟列表页紧耦合
- **选定 C**: `{% if is_admin_or_dba %}` 包住, 复用 `727f046` 引入的上下文变量, 0 后端改动
