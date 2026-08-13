# gh-ost 任务列表页可见性细分 (DBA 全量 / RD 自己) (2026-08-13)

## 症状

8/13 用户截图反馈: oa_tester_1 (RD 角色, 有 view_ddlghosttask perm) 访问
`/gh_ost/admin_list/` 能看到**全部 46 条** gh-ost 任务, 跟 DBA 看到的一样。

期望: RD 视角应该**只看到自己提交的** task, 不能看全量 (涉及其他人提交的 SQL 工单 db 名/表名/进度)。

**根因**: 8/12 切的 C 方案 (commit `c80c1ad`) 只加了 perm 守卫, 进了页面后
所有有 perm 的用户都看全量, 没区分"运维视角"vs"提交人视角"。

## 修法 (C 方案延伸, 0 DB 改动)

**核心思路**: 复用现有 perm 守卫, 加一层"角色判定" — 是运维角色就全量, 是提交人就过滤。

### 角色判定 helper

文件: `sql/extensions/ddl_gh_ost/views.py` (新增)

```python
def _is_admin_or_dba(user) -> bool:
    """判定用户是否"运维视角" — 看 gh-ost 任务全量。

    True:  superuser 或属于 ``DBA`` / ``DBA组长`` 组 → 看全量
    False: 其他用户 → 只看自己提交的 task (workflow.engineer == user.username)
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=("DBA", "DBA组长")).exists()
```

**为什么用 group name 白名单 (DBA/DBA组长) 而不是 `is_staff` 或其他标识**:
- Archery 上游没有统一的 `is_dba` 字段
- workflow_audit_setting 审批组用 group.id 配, 这里 group.name 简单白名单足够
- 跟 v0.2.0 OA 框架的"审计 user 配置"命名保持一致 (memory: auth_group 1 默认组 / 2 RD / 3 DBA / 4 PM / 5 QA / 13 研发 / 14 研发组长 / 15 DBA组长 / 16 副总)

### 视图加 engineer 过滤

文件: `sql/extensions/ddl_gh_ost/views.py` (admin_list 视图)

```python
# 0.5 角色判定
is_admin_or_dba = _is_admin_or_dba(request.user)

# 2.5 提交人过滤 (非 DBA 视角只看自己)
if not is_admin_or_dba:
    qs = qs.filter(workflow__engineer=request.user.username)

# 4. 状态统计 (跟随列表范围)
stat_qs = DdlGhostTask.objects.all()
if not is_admin_or_dba:
    stat_qs = stat_qs.filter(workflow__engineer=request.user.username)
all_count = stat_qs.count()
active_count = stat_qs.filter(...).count()
...
```

**为什么 stat_qs 独立从 DdlGhostTask.objects.all() 起, 不复用 qs**:
qs 已经应用了 task_type / status / filter_q 筛选, 统计卡要的是"全量筛选后
但不考虑提交人过滤"的状态分布, 不能跟筛选混。stat_qs 只跟 engineer 过滤走。

### 模板加"提交人"列 + 头部提示

文件: `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/task_list.html`

- 表头加"提交人"列 (在"工单 / DB.表"之后), 显示 `workflow.engineer_display` (中文名) + `@engineer` (username)
- 副标题根据 is_admin_or_dba 切换:
  - DBA: "DBA 运维入口 · 取消/重试/回滚无锁 DDL 任务 · 共 46 条 (全量)"
  - RD: 橙色 "您当前以'提交人'视角查看 · 仅显示您自己提交的 gh-ost 任务 · 共 N 条" + "为什么?" 可展开详细说明
- rebuild 任务 (workflow=NULL) 提交人列显示 "DBA 手动" — 因为 rebuild 是 DBA 手动选表, 跟 SQL 工单无关

## 验证

### 134 dev 真表演练 4 Case

| Case | 用户 | 角色 | 期望 | 实测 |
|------|------|------|------|------|
| A | archery (superuser) | 全权限 | 200 + 46 条全量 + "全量" 文案 | ✓ |
| B | mkq (DBA 组) | DBA 视角 | 200 + 46 条全量 + "全量" 文案 | ✓ |
| C | oa_tester_1 (研发组) | 提交人视角 | 200 + 只看自己提交的 N 条 + 橙色提示 | ✓ |
| D | gyf (DBA组长组) | DBA 视角 | 200 + 46 条全量 | ✓ |

### 134 dev 演练脚本

`scripts/drill_admin_list_scope.py`:
- 登录 mkq → 访问 /gh_ost/admin_list/ → 列表数 == 46
- 登录 oa_tester_1 → 访问 /gh_ost/admin_list/ → 列表数 == oa_tester_1 提的 task 数
- 列表里每条都验证 `t.workflow.engineer == "oa_tester_1"`
- 头部出现"提交人视角"提示 (橙色 + "为什么?" 链接)
- superuser 验证 46 条 + 头部无橙色提示

## 影响

- **正面**: RD 提交人隐私保护, 不会意外看到别人提交的 SQL 工单 db.表
- **正面**: DBA 运维视角完整, 不变
- **零 DB 改动**: 0 migration, 纯代码
- **零 settings 改动**: 不需新增 env var
- **跟 perm 守卫兼容**: view_ddlghosttask perm 仍是大门 (无 perm → 403),
  engineer 过滤是门内的精细分层
- **DBA 自由分配**: 想让某 RD 看全量 → 把他加到 "DBA" 组, 不用改代码

## 边界情况处理

- **rebuild 任务 (workflow=NULL)**: RD 视角走 `workflow__engineer=user.username` 过滤,
  rebuild 不挂工单, 所以 RD 看不到任何 rebuild task。这是预期的: rebuild 是 DBA 工具
- **OA 审批组 (audit_auth_groups) 跟这里的 group 白名单不是同一回事**:
  - OA 审批组: 走 `ext_approval_flow.audit_auth_groups` (审批触发谁)
  - 这里: `request.user.groups.filter(name__in=(...))` (用户能看全量)
  - 命名上保持 "DBA / DBA组长" 一致, 避免产品混淆
- **超级管理员**: 仍走 is_superuser, 不受 group 影响

## 相关 commits / changelogs

- 前置: `c80c1ad` gh-ost 任务列表页 perm 守卫 (C 方案基础)
- 前置: `47728bb` gh-ost 任务管理列表页 (引入 admin_list 视图)
- 本次 commit: 列表页可见性细分 (DBA 全量 / RD 自己)

## 产品决策记录

- **决策**: gh-ost 任务列表页对 RD 提交人视角做 engineer 过滤, DBA / 超级管理员不受影响
- **决策时间**: 2026-08-13 09:13 (用户截图反馈 RD 能看全量)
- **决策人**: 阿达叔叔 (产品) + mavis (执行)
- **替代方案 A** (否决): 让所有用户都看全量, 隐私放一边
  → 用户明确反馈 "提交者是否只能看到自己提交的单子", 期望是按 engineer 隔离
- **替代方案 B** (否决): 改 perm 模型, 加 "engineer_only" 标记
  → perm 已经是粗粒度, 再加细粒度就重了, 不如代码里按 group 判定
- **替代方案 C** (否决): 用 `user.is_staff` 区分
  → Archery 没统一 is_dba 标识, is_staff 在 OA 框架里是别的用途
- **选定 D**: group 白名单 (DBA / DBA组长) + engineer 过滤
