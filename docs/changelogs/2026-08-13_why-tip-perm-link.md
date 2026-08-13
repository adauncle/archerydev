# 2026-08-13 "为什么?" 弹窗去掉"权限组管理"链接

## 业务背景

8/13 用户反馈, `oa_tester_1` (RD) 视角下, 点 admin_list 页面副标题的"为什么?"按钮, 弹窗里显示"权限组管理"链接对 RD 没用 (RD 进不了 admin 后台)。

截图 2 弹窗内容:
> 任务管理列表是 DBA 运维入口, 只 DBA / DBA 组长 / 超级管理员能看全量。
> 您有 `view_ddlghosttask` 权限, 但属于普通角色, 所以只能查看自己提交的工单 (workflow.engineer = 您的用户名)。
> 如需查看全量, 请联系 DBA 把你加到 `DBA` 或 `DBA组长` 组 (**权限组管理**)。

"权限组管理" 是 `<a href="/admin/auth/group/" target="_blank">` 链接, RD 点了会跳 admin 登录页 (没权限)。

## 修法

去掉 task_list.html 弹窗里的"权限组管理"链接, 改成纯文本提示:
> 如需查看全量, 请联系 DBA 把你加到 `DBA` 或 `DBA组长` 组。

**为什么不去掉整个"为什么?"按钮?**
- 弹窗本身只在 RD 视角 (`{% else %}` 块) 渲染, DBA 视角不渲染
- 弹窗对 RD 有教学意义 (解释"提交人视角"为啥跟 DBA 看到的不一样)
- 唯一的问题是"权限组管理"链接对 RD 没用, 直接去掉链接最干净, 不需要 is_admin_or_dba 守卫

**为什么不隐藏 base.html 侧边栏的"权限组管理"菜单?**
- `base.html:264` 侧边栏的"权限组管理"是 Archery 上游菜单, 跟本任务无关
- 它在"其他配置管理 → 权限组管理", 严格守卫在 archery 上游菜单的可见性逻辑, RD 看到也点不动
- 本任务只修 task_list.html 弹窗里的链接, 不动侧边栏

## 演练 (134 dev 4 Case + read-only)

`scripts/drill_why_tip_perm.py` — 用正则 `<div id="gh-ost-scope-tip">...</div>` 抓弹窗内容, 不被侧边栏污染。

| Case | 用户 | 弹窗渲染 | 弹窗内"权限组管理" |
|------|------|----------|---------------------|
| A. superuser | archery | False (DBA 视角, 走 if 分支) | — |
| B. DBA | mkq | False | — |
| C. **RD** | oa_tester_1 | True | **False (文本 + 链接都不渲染)** ✓ |
| D. DBA组长 | gyf | False | — |

**清理**: 演练后 mkq/oa_tester_1/gyf 3 个 user 的 `view_ddlghosttask` perm 全部 revoke 还原。

## 验证清单

- [x] 134 dev 4 Case drill 全过
- [x] gunicorn reload 后代码生效
- [ ] **用户浏览器手动验收** (用 oa_tester_1 登录 134 dev 9003, 进 /gh_ost/admin_list/ 点"为什么?", 弹窗里没"权限组管理"链接)

## 同源 entry

- `gh-ost 任务管理列表页 perm 守卫 (C 方案)` commit `c80c1ad` (8/12)
- `gh-ost 任务列表页可见性细分 (DBA 全量 / RD 自己)` commit `727f046` (8/13)
- `gh-ost 任务列表底部 AJAX 提示 (DBA 专属)` commit `2d27a4a` (8/13)
