# 2026-09-22 DBA-bug-13 第二波: DDL-Sync 镜像工单继承源工单 enable_gh_ost + gh_ost_mode

> 9/22 16:29 阿达叔叔截 wf#4877 详情页 + wf#4878 (新镜像工单) 反馈: "源工单已经走完 gh-ost 流程, 镜像工单还要再点'启用 gh-ost'按钮"
> 根因: DDL-Sync 创建镜像工单时没复制源工单的 `enable_gh_ost` + `gh_ost_mode` 字段 (默认值 enable_gh_ost=0)
> 配合 views.py:640-660 已有的 lazy auto-enable 逻辑, 业务方下次打开详情页就能自动启用, 不需要再点按钮

## 背景

### wf#4877 (源工单) 已走完 gh-ost 流程

```
当前状态: 已正常结束
gh-ost 进度面板: 1 个 task / 全部已结束 / 模式: 智能（默认: 大表 gh-ost + 小表原生 ALTER）
task #33 / hly_lockwait_monitor.test / alter table test add column test5 varchar(128) not null default '历史库同步' / 成功 / 100% / 16:09:17 / 16:09:42
DDL 跨库同步 - 已配置 (黄色, 联动中), 镜像工单 wf#4878 已生成 待执行
```

### wf#4878 (镜像工单, 由 wf#4877 触发) 仍有"启用 gh-ost"按钮

```
当前状态: 审核通过
enable_gh_ost: 0  ← 默认值 (DDL-Sync 没复制源工单的 True)
gh_ost_mode: smart
native_alter_results: [] (没启用过)
DdlGhostTask: 0 条
```

### 完整因果链

```
业务方 wf#4877 (源工单 prod core for etc)
  enable_gh_ost=True, gh_ost_mode=smart
  → 启用 gh-ost → DdlGhostTask #33 success
  → wf#4877 状态 workflow_finish

DDL-Sync 触发 → 创建 wf#4878 镜像工单 (历史库, prod core for history 变更)
  SqlWorkflow.objects.create(...)  ← sync_trigger.py:218 没复制 enable_gh_ost + gh_ost_mode
  enable_gh_ost=0, gh_ost_mode='smart' (默认值)
  
业务方/管理员 (mkq) 详情页 wf#4878 点"启用 gh-ost"按钮
  → enable 端点 _get_table_size_info 查 test 表 (0 行 0.2 MB)
  → smart 模式 fallback 小表 → 加入 small_alters → 返 ok=True 但 0 task
  → 前端 UI 显示"已加入小表原生 ALTER 队列" ✅ (DBA-bug-13 第一波修复)
  → 但业务方/管理员要再点一次"启用 gh-ost" (跟源工单重复)
```

## 根因

`sql/extensions/ddl_sync/services/sync_trigger.py:218` `create_target_workflow` 函数:

```python
target_workflow = SqlWorkflow.objects.create(
    workflow_name=f"[镜像] {source_workflow.workflow_name}",
    group_id=target_group.group_id,
    group_name=target_group.group_name,
    engineer=source_workflow.engineer,
    ...
    syntax_type=source_workflow.syntax_type,
    is_backup=source_workflow.is_backup,
    instance=pair.target_instance,
    db_name=pair.target_db,
    # ← 缺少 enable_gh_ost + gh_ost_mode 复制
)
```

## 修复 (1 文件, 2 字段)

文件: `sql/extensions/ddl_sync/services/sync_trigger.py` (line 246-258)

加 2 个字段复制:

```python
target_workflow = SqlWorkflow.objects.create(
    ...
    instance=pair.target_instance,
    db_name=pair.target_db,
    ## CUSTOM-MODIFIED: DBA-bug-13 镜像工单继承源工单 enable_gh_ost + gh_ost_mode
    ## 关联: docs/changelogs/2026-09-22_dba-bug-13-mirror-ef-loop-button.md
    ## 根因: 镜像工单 enable_gh_ost=0 (默认值), 业务方/管理员需要再次点 "启用 gh-ost" 按钮
    ##       才能触发 gh-ost 流程 (跟源工单已经走完的流程重复)
    ## 业务 (9/22 wf#4877→wf#4878): 业务方源工单走完 gh-ost (task #33 success),
    ##       DDL-Sync 触发镜像工单 wf#4878, 但 enable_gh_ost=0 → 镜像工单详情页显示"启用 gh-ost"按钮
    ## 修法: 复制 enable_gh_ost + gh_ost_mode 字段
    ##       配合 views.py:640-660 lazy auto-enable 逻辑 (enable_gh_ost=True + review_pass + 无 task → 自动 _enable_ghost_for_workflow)
    ##       下次业务方打开镜像工单详情页时自动创建 DdlGhostTask, detail.html 显示进度面板, 不再显示"启用 gh-ost"按钮
    enable_gh_ost=getattr(source_workflow, "enable_gh_ost", False),
    gh_ost_mode=getattr(source_workflow, "gh_ost_mode", "smart") or "smart",
)
```

### 配合 views.py:640-660 已有的 lazy auto-enable 逻辑

```python
# views.py:640-660 (已有, 9/22 阿达叔叔拍的 5A 设计之一)
if (
    getattr(workflow_detail, "enable_gh_ost", False)
    and workflow_detail.status == "workflow_review_pass"
):
    try:
        existing = DdlGhostTask.objects.filter(workflow=workflow_detail).first()
        if existing is None:
            # 审批通过且没 task → 自动启用
            from sql.extensions.ddl_gh_ost.views import _enable_ghost_for_workflow
            auto_result = _enable_ghost_for_workflow(
                workflow_detail, created_by=f"lazy-auto(提交人={workflow_detail.engineer})"
            )
```

## 验证

### 演练 `scripts/_w3_dba_bug13_mirror_sync_verify.py` (13/13 PASS)

- 4 sync_trigger 静态 (有 enable_gh_ost / gh_ost_mode 复制 / 注释 / pair.target_instance)
- 4 views.py lazy auto-enable 静态 (含 lazy auto-enable 逻辑 / 守卫 / 自动调 _enable_ghost_for_workflow / existing is None)
- 5 逻辑验证 (sync_trigger + views.py + DBA-bug-13 守卫联动)

### 部署 (DBA 一条龙)

1. **134 dev (9/22 17:00)**: scp sync_trigger.py + `systemctl restart archery-prod-gunicorn.service` + HTTP 200
2. **110 prod (9/22 17:05)**: scp + reload script + HTTP 200 + grep `enable_gh_ost=getattr` 验证 ✅

### 实战测 (阿达叔叔)

- **wf#4878 镜像工单详情页硬刷新** (Ctrl+Shift+R):
  - 旧 (DDL-Sync 修前): 显示"启用 gh-ost"按钮 (业务方/管理员要再点)
  - 新 (DDL-Sync 修后): 仍然显示 (因为现有 wf#4878 的 enable_gh_ost=0, **DDL-Sync 修法只对**未来**触发的新镜像工单生效**)
  - 历史镜像工单 (如 wf#4878): 需手动 UPDATE `enable_gh_ost=1` 走 lazy auto-enable (一次性数据修复)

## 已知未修 (历史镜像工单)

DDL-Sync 修法只对**未来触发**的新镜像工单生效。**历史**已存在的镜像工单 (如 wf#4878) 仍 `enable_gh_ost=0`, 业务方/管理员下次打开详情页不会触发 lazy auto-enable。

**修法**: 一次性 UPDATE SQL (DBA 一条龙手工):
```sql
UPDATE sql_workflow 
SET enable_gh_ost=1, gh_ost_mode='smart' 
WHERE id=4878 AND status='workflow_review_pass' 
  AND enable_gh_ost=0;
```
然后业务方下次打开 wf#4878 详情页就 lazy auto-enable 自动启用。

## 实战新发现 (1 条入 MEMORY, 跨项目可复用)

**DDL-Sync 镜像工单应继承源工单 enable_gh_ost + gh_ost_mode (跨项目 DDL-Sync 设计, 9/22 实战新发现)**:
- 跨项目写 DDL-Sync / 镜像工单 / 数据同步 / 多环境工单复制逻辑时, **必须复制源工单的所有关键状态字段** (gh-ost 状态/审批状态/审计配置), 不能只复制 instance/db_name/sql
- 实战踩坑: 9/22 wf#4877 源工单走完 gh-ost (task #33 success), DDL-Sync 触发镜像工单 wf#4878, 但 sync_trigger.py:218 只复制 group/engineer/syntax_type/instance/db_name, **没复制 enable_gh_ost + gh_ost_mode** → 镜像工单默认值 enable_gh_ost=0 → 业务方/管理员要再点"启用 gh-ost"按钮
- 修法: create_target_workflow 时复制源工单所有关键状态字段:
  1. **业务状态字段**: enable_gh_ost, gh_ost_mode, native_alter_results (如果适用)
  2. **审批字段**: audit_auth_groups, group_id (已有 pair.target_group 修过)
  3. **执行字段**: syntax_type, is_backup (已有)
- 配合 lazy auto-enable 逻辑 (views.py:640-660), 镜像工单创建后**业务方下次打开详情页就自动启用**, 不需要再点按钮
- 跨项目通用: 任何"自动生成的派生工单"都应该继承源工单的关键状态字段, 不能让业务方/管理员重复操作

## 关联

- 9/22 DBA-bug-13 第一波 (commit `02d7b2c`): 详情页 UI 反馈缺失修复 (has_native_alter elif + alert summary)
- 9/22 DBA-bug-13 第二波 (本 commit): DDL-Sync 镜像工单继承源工单 enable_gh_ost + gh_ost_mode
- 9/22 wf#4877 (源工单, gh-ost task #33 success) → wf#4878 (镜像工单, 待修复 enable_gh_ost=1)
- `sql/extensions/ddl_sync/services/sync_trigger.py:218` (create_target_workflow)
- `sql/views.py:640-660` (lazy auto-enable 逻辑, 已有)
- `sql/models.py:405-409` (`enable_gh_ost` BooleanField) + `models.py:419-422` (`gh_ost_mode` CharField)