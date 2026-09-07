# D35 修复: gh-ost 任务列表加 "审批人" 组白名单 (9/7 副总场景)

> **日期**: 2026-09-07 13:49
> **触发**: 业务方截图 110 prod /gh_ost/admin_list/, 副总 "李绍平" 只能看自己提交的任务, 看不到全量
> **决策**: 走 B 方案 — 新建 "审批人" 组 + 改白名单一行, 不继承 DBA 组长全套权限
> **影响范围**: 134 dev + 110 prod 同步修

---

## 一、问题

业务方反馈 (9/7 13:45): 副总"李绍平"作为关键审批人需要看全量 gh-ost 任务列表 (gh-ost 任务管理 /gh_ost/admin_list/), 但现在只 DBA / DBA 组长 / 超级管理员 能看全量。

页面顶部提示文字明确说明:
> "任务管理列表是 DBA 运维入口, 只 DBA / DBA 组长 / 超级管理员能看全量"
> "如需查看全量, 请联系 DBA 把你加到 DBA 或 DBA组长 组"

## 二、两个方案对比

| 方案 | 改动 | 副作用 |
|------|------|--------|
| **A: 直接加 DBA 组长组** | 0 代码, admin 后台加组 | 继承所有 DBA 组长权限: Archery 审批流 (李绍平会收到所有 DBA 审批 + 有审批权) + gh-ost rebuild 触发 (她看到"启动 gh-ost"按钮) + rebuild 选表页 |
| **B: 新建 "审批人" 组 + 改白名单一行** (推荐) | 134 dev 改 `_is_admin_or_dba` + admin 后台建组 + 推 110 prod | 严格只"看全量 gh-ost 任务列表", 不继承其他 DBA 组长权限 |

## 三、用户拍板 (9/7 13:49)

走 B 方案。

## 四、改法

### 1. `sql/extensions/ddl_gh_ost/views.py:1116-1133` `_is_admin_or_dba`
```python
# 修前
return user.groups.filter(name__in=("DBA", "DBA组长")).exists()
# 修后
return user.groups.filter(name__in=("DBA", "DBA组长", "审批人")).exists()
```

加 docstring 说明:
- True: superuser 或属于 DBA / DBA组长 / 审批人 组 → 看全量
- 2026-09-07 加 "审批人" 组白名单 @ mavis: 副总/总监/经理 等非 DBA 审批人
  需要看全量 gh-ost 任务列表做审批, 但不应该继承 DBA 组长整套权限
  (审批流 / rebuild 触发 / 选表页等). 单独建 "审批人" 组解耦.

### 2. `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/task_list.html:95, 100` 提示文案
```html
<!-- 修前 -->
任务管理列表是 DBA 运维入口, 只 DBA / DBA 组长 / 超级管理员能看全量。
如需查看全量, 请联系 DBA 把你加到 <code>DBA</code> 或 <code>DBA组长</code> 组。

<!-- 修后 -->
任务管理列表是 DBA 运维入口, 只 DBA / DBA 组长 / 审批人 / 超级管理员能看全量。
如需查看全量, 请联系 DBA 把你加到 <code>DBA</code> / <code>DBA组长</code> / <code>审批人</code> 组。
```

## 五、134 dev 演练 PASS (9/7 13:50)

演练脚本: `scripts/_archive/_d35_134dev_approver_test3.py`

```
[BEFORE] oa_tester_1 groups: ['', '']      (空字符串是 GBK 编码吃了"审批人")
[BEFORE] oa_tester_1 is_admin_or_dba: False
[STEP1]  oa_tester_1 + 审批人 组
  groups: ['', '', '']                       (加了一个组, 是审批人)
  is_admin_or_dba: True                      ✅
  [PASS STEP1] 加 审批人 组后 is_admin_or_dba=True (能看全量)
[CLEAN]   oa_tester_1 - 审批人 组 (回原状)
  groups: ['', '']
  is_admin_or_dba: False                     ✅ (回退)
```

## 六、commit 改动

| commit | 改动文件 |
|------|------|
| (待) | `sql/extensions/ddl_gh_ost/views.py` |
| (待) | `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/task_list.html` |
| (随) | `docs/changelogs/2026-09-07_ddl-sync-w2-d35-approver-group.md` (本文件) |

## 七、110 prod 推送影响

D35 push 9 步 runbook Step 6 跨 app 文件清单**新增 2 个**:

- `sql/extensions/ddl_gh_ost/views.py` (**新增 D35 approver**)
- `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/task_list.html` (**新增 D35 approver**)

**D35 push 完后, DBA 在 110 prod admin 后台 1 步收尾**:
1. 登录 `/admin/auth/group/add/`
2. 创建组"审批人"
3. 在 `/admin/auth/user/<李绍平id>/change/` 把李绍平加到"审批人"组
4. 李绍平刷新 /gh_ost/admin_list/ 即可看全量 (10 条 task)

## 八、相关 changelog

- `docs/changelogs/2026-08-13_gh-ost-admin-list-scope.md` (D6 拍板 DBA 视角 / 提交人视角)
- `docs/changelogs/2026-09-07_ddl-sync-w2-d35-backticks-parse-bug.md` (D35 backticks 修复)
- `docs/changelogs/2026-09-07_ddl-sync-w2-d35-no-version-label.md` (D35 去掉版本号文案)
