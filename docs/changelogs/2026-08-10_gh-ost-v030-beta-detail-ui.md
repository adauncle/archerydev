# v0.3.0-beta —— gh-ost 详情页前端 UI 集成

**日期**: 2026-08-10
**作者**: mavis
**类型**: feat（前端 UI 集成，关闭 v0.3.0-alpha "beta 再接前端 Vue" 的 TODO）

## 背景

v0.3.0-alpha (`4f34a81`) 当时 commit message 明确说 "Django template 进度面板（admin 内部可访问，**beta 再接前端 Vue**）"。
v0.3.0-beta 真跑 8 件 (`2c5a0b7`) 跟 v0.4.5-alpha 6 commit 都只到后端 runner/parser/poller + admin 后台增强，**没接 detail.html 详情页"启用 gh-ost"按钮**。

8/10 DBA 浏览器走 SQL 上线 → 提交工单 → 详情页 → **找不到"启用 gh-ost"入口**，
只能进 admin 后台 `DdlGhostTask` 列表手动建 task —— 跟 product 设计稿"用户视角"不一致。

## 修复

### 1. views.py `detail` 加 4 个 context 字段

```python
## CUSTOM-MODIFIED: v0.3.0-beta 接前端 UI —— 详情页展示 gh-ost 启用按钮 / 进度面板
has_ghost_task = False
can_enable_ghost = False
ghost_task = None
if getattr(settings, "CUSTOM_GH_OST_ENABLED", False):
    from sql.extensions.ddl_gh_ost.models import DdlGhostTask
    try:
        ghost_task = DdlGhostTask.objects.get(workflow=workflow_detail)
        if not ghost_task.is_terminal:
            has_ghost_task = True
    except DdlGhostTask.DoesNotExist:
        ghost_task = None
    user = request.user
    is_submitter = (user.username == workflow_detail.engineer)
    is_dba_group = user.groups.filter(name__in=["DBA", "DBA组长"]).exists()
    can_enable_ghost = (
        (user.is_superuser or is_dba_group or is_submitter)
        and workflow_detail.status in ("workflow_manreviewing", "workflow_review_pass", "workflow_timingtask")
        and not has_ghost_task
    )
```

**4 个 context 字段**：
- `has_ghost_task`: 当前是否有 active DdlGhostTask
- `can_enable_ghost`: 当前用户是否能启用
- `ghost_task`: active task 实例（用于 iframe 进度面板）

**启用权限**：superuser / DBA 组 / 工单 submitter

### 2. detail.html 加 UI 组件

在 nav-tabs 上方 (line 119 之后) 加：

```html
{% if has_ghost_task %}
<div class="panel panel-primary" id="gh-ost-panel">
    <iframe src="/gh_ost/progress/{{ workflow_detail.id }}/"
            style="width:100%;height:600px;border:0;" id="gh-ost-iframe"></iframe>
</div>
{% elif can_enable_ghost %}
<div class="alert alert-info" id="gh-ost-enable-block">
    <i class="fa fa-rocket"></i>
    <strong>启用 gh-ost 无锁变更</strong> · 大表 DDL 不锁表
    <button id="btn-enable-ghost" data-wf-id="{{ workflow_detail.id }}">启用 gh-ost</button>
</div>
<script>
function getCookie(name) { /* 标准 Django CSRF 助手 */ }
(function() {
    var btn = document.getElementById('btn-enable-ghost');
    btn.onclick = function() {
        // 1. POST /gh_ost/precheck/<wf_id>/
        // 2. POST /gh_ost/enable/<wf_id>/
        // 3. location.reload()  → 显示进度面板 iframe
    };
})();
</script>
{% endif %}
```

**UI 状态机**：
- 无 active task + 用户能启用 → 显示"启用 gh-ost"按钮
- 有 active task → 显示进度面板 iframe (`/gh_ost/progress/<wf_id>/`)
- 其他情况 → 不显示

**进度面板内的"开始/cancel/retry"按钮**：沿用 `progress.html` 已有的 `startBtn` / `cancelBtn` / `retryBtn` 等，
不重复实现。

## 验证（134 dev 真实演练）

### UI 渲染矩阵

| wf_id | status | ghost_task | 启用按钮 | 进度iframe | 预期 |
|-------|--------|------------|----------|------------|------|
| 10 (老, manreviewing) | manreviewing | 无 | ✅ | ❌ | 启用按钮 ✅ |
| 14 (演练 finish) | finish | id=1 cancelled (terminal) | ❌ | ❌ | 都不显示 ✅ |
| 19 (演练 finish) | finish | id=9 failed (terminal) | ❌ | ❌ | 都不显示 ✅ |
| 20 (新提交) | manreviewing | 无 | ✅ | ❌ | 启用按钮 ✅ |

### 端到端流程（点 wf=20 "启用 gh-ost"）

```
1. POST /gh_ost/precheck/20/  → 200, 5/5 通过 (binlog=ROW, 磁盘 1.16TB, 权限, SQL, 表类型)
2. POST /gh_ost/enable/20/    → 200, task_id=26, status=queued
3. 详情页 reload                → has_进度iframe=True, has_启用按钮=False ✅
4. DdlGhostTask id=26          → task_type=ghost, status=queued, enabled=True, precheck_passed=True
5. (清理)                      → task id=26 改 status=cancelled (不真启 gh-ost 演练)
```

**完整流程**：
```
SQL 上线 → 提交工单
     ↓
详情页 /detail/<wf_id>/
     ↓ (页面渲染 has_ghost_task=False, can_enable_ghost=True)
显示"启用 gh-ost"按钮
     ↓ (用户点按钮 → precheck → enable)
刷新页面，iframe 显示进度面板
     ↓ (用户点进度面板里的"开始"按钮)
POST /gh_ost/start/<wf_id>/  → 启 gh-ost 子进程
     ↓ (poller 3s 轮询进度)
iframe 实时显示 stage / 进度条 / 耗时
```

## 110 PROD 影响

| 修复 | 推 110？ | 说明 |
|------|----------|------|
| views.py 4 个 context 字段 | ✅ 推 | 推 v0.3.0 时一起 |
| detail.html UI 组件 | ✅ 推 | 推 v0.3.0 时一起 |

推 110 时直接 tarball 同步 `sql/views.py` + `sql/templates/detail.html` 即可。

## v0.3.0-alpha / v0.4.5-alpha 当时的"beta 再接前端 Vue" TODO 关闭

- ✅ 详情页 UI 集成（v0.3.0-beta）
- ⏸ sqlsubmit.html 提交页"启用 gh-ost"勾选（v0.3.0 GA 或 v0.4.0）

**剩余工作**：
- sqlsubmit.html 提交页"启用 gh-ost"勾选 + 提交时自动 enable
- gh-ost 完成 / 失败后钉钉通知集成（OA 通知）

## 相关 commit

- `4f34a81` feat(gh-ost): v0.3.0-alpha 骨架（"beta 再接前端 Vue" TODO）
- `2c5a0b7` feat(gh-ost): v0.3.0-beta 真跑 8 件（后端）
- `e4a3707` feat(gh-ost): v0.4.5-alpha admin + UI（admin 后台）
- **本轮** — v0.3.0-beta detail.html 详情页前端 UI 集成
