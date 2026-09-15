# 镜像工单 (及所有工单) 终止流程按钮 终态隐藏修复

> **DBA 实战**: 阿达叔叔 9/15 16:24 在 110 prod 反馈 "镜像工单逻辑有问题: archery 和 dba 角色无法终止工单"。
> 截图显示 `prodarchery.ahggwl.com:9123/cancel/` 弹窗 "你无权操作当前工单!"。
>
> 9/15 16:30-16:43 排查 `_mirror_wf4830_check_110.py` 推 110 prod 跑 + access.log 实证 + `Audit.can_review` / `can_cancel` 链路分析。

## 现象

- **触发工单**: 业务方实战 wf#4830 (DDL 跨库同步镜像工单, 目标 = history 变更 / hly_accesscard)
- **现状**:
  - 登录用户 archery (is_superuser=True, 所有 sql.* 权限都有, 在 'DBA' 组但不在 'DBA组长' 组)
  - wf#4830 status = workflow_abort (**终态**, 业务方 gcl 9/15 自己 abort 的)
  - wf#4830 engineer = gcl, group_id = 22 (历史库组), audit_auth_groups = '3'
  - access.log 16:23:07 archery 50.10.1.68 `POST /cancel/` 200 5697 from detail/4830 → 返"无权操作当前工单"
  - 业务方 wf#4828 也是同款 (workflow_abort + access.log 16:27:21 dba 50.10.1.215 POST /cancel/ 302)

## 根因 (UI 误导, 不是权限错配)

### 1. wf 终态后 `can_cancel()` 返 False (设计正确)

```python
# sql/utils/sql_review.py:88-112
def can_cancel(user, workflow_id):
    workflow_detail = SqlWorkflow.objects.get(id=workflow_id)
    result = False  # ← 默认 False
    if workflow_detail.status == "workflow_manreviewing":
        return any([Audit.can_review(...), user.username == workflow_detail.engineer])
    elif workflow_detail.status in ["workflow_review_pass", "workflow_timingtask"]:
        return any([can_execute(...), user.username == workflow_detail.engineer])
    return result  # ← workflow_abort/finish/exception/reject 不命中, 返 False
```

### 2. `is_can_review` 对终态可能仍返 True (关键矛盾)

```python
# sql/utils/workflow_audit.py:746 Audit.can_review
if audit_info.current_status == WorkflowStatus.WAITING:  # ← 只看 audit 表 current_status
    ...
    if user.is_superuser or auth_group_users([audit_auth_group], group_id).filter(id=user.id).exists():
        if user.has_perm("sql.sql_review"):
            result = True
```

wf#4830 的 `audit.current_status = 0` (WAITING), archery 是 superuser + 有 sql.sql_review
→ `Audit.can_review(archery, 4830, 2) = True`
→ **`is_can_review = True`** 即使 `wf.status = workflow_abort`!

### 3. detail.html 渲染按钮的条件只看 `is_can_review or is_can_cancel`

```html
<!-- sql/templates/detail.html:456 (大表 alert 内 DBA 兜底取消) -->
{% if is_can_cancel %}
<form action="/cancel/" ...>
    <button type="submit" class="btn btn-warning" id="btn-big-table-cancel">
        <i class="fa fa-ban"></i> 终止工单（让 RD 重提）
    </button>
</form>
{% endif %}

<!-- sql/templates/detail.html:524 (主流程底部 "终止流程" 按钮) -->
{% if is_can_review or is_can_cancel %}
<form id="form-cancel" action="/cancel/" ...>
    ...
    <input type="button" id="btnCancel" class="btn btn-default" value="终止流程"/>
</form>
{% endif %}
```

**问题**: `is_can_review=True` (superuser 走了 can_review 例外) → 按钮显示 → 用户点 → 后端 `can_cancel()` 返 False → 报 "无权操作当前工单"

**这是 UX bug**: 用户看到按钮以为能取消, 但点了没用, **功能上的 cancel 是按 wf.status 判的**, 不是按 is_can_review 判。

## 修法 (改 detail.html 加 wf.status 守卫)

**改 2 处**, 加 wf.status 守卫, 终态 (workflow_finish / workflow_abort / workflow_exception / workflow_reject) 时隐藏按钮:

### 改 1: detail.html:456 (大表 alert 内"DBA 兜底"取消按钮)

```html
<!-- 修前 -->
{% if is_can_cancel %}
<form action="/cancel/" method="post" style="display:inline-block;margin:0;">
    ...
    <button type="submit" class="btn btn-warning" id="btn-big-table-cancel">
        <i class="fa fa-ban"></i> 终止工单（让 RD 重提）
    </button>
</form>
{% endif %}

<!-- 修后 (加 wf.status 守卫, 终态隐藏) -->
{% if is_can_cancel and workflow_detail.status in 'workflow_manreviewing,workflow_review_pass,workflow_timingtask' %}
... (同前)
{% endif %}
```

### 改 2: detail.html:524 (主流程底部"终止流程"按钮)

```html
<!-- 修前 -->
{% if is_can_review or is_can_cancel %}
<form id="form-cancel" action="/cancel/" method="post" style="display:inline-block;">
    ...
    <input type="button" id="btnCancel" class="btn btn-default" value="终止流程"/>
</form>
{% endif %}

<!-- 修后 (加 wf.status 守卫, 终态隐藏) -->
{% if workflow_detail.status in 'workflow_manreviewing,workflow_review_pass,workflow_timingtask' %}
    {% if is_can_review or is_can_cancel %}
    ... (同前)
    {% endif %}
{% endif %}
```

**关键**: 加 `workflow_detail.status in 'workflow_manreviewing,workflow_review_pass,workflow_timingtask'` 守卫, 终态 (workflow_finish/abort/exception/reject) 直接隐藏按钮, 用户看不到就不会去点。

## 验证

### 134 dev

- 演练脚本 (scripts/_dba_bug6_drill_134.sh): 造一个 workflow_abort 终态 wf + archery 登录看 detail 页
- 验证 detail 页 HTML 不含 "终止流程" / "btnCancel" / "btn-big-table-cancel"
- 回归验证 workflow_manreviewing 状态 wf 按钮**正常显示**

### 110 prod

- 推完 detail.html + kill -TERM 5 workers reload (9/11 实战法)
- 演练: wf#4830 终态 → 访问 detail 页 → 验证 cancel 按钮**隐藏**
- 业务方回归: wf#4821 等活跃工单 (workflow_manreviewing) 验证 cancel 按钮**正常显示**

## 实战新发现 (跨项目可复用)

- **UI 跟后端判断逻辑必须对齐, 别让用户看到点了没用的按钮** (9/15 实战新发现) - 跨项目模板层写按钮显示条件时, 必跟后端**真正执行的判断逻辑**保持一致, 别只看 is_can_review / is_can_cancel 这种"权限层"变量, 必同时考虑 wf.status 这种"业务状态层"变量. 实战踩坑: 9/15 wf#4830 wf.status=workflow_abort 终态, archery 是 superuser 让 is_can_review=True, detail.html:524 `{% if is_can_review or is_can_cancel %}` 误以为按钮可点, 但后端 can_cancel 返 False → 用户点了报"无权操作". 跨项目模板层写按钮守卫 checklist 必加 1 条: 显示条件 = 权限变量 && 业务状态变量, **两个都要判**, 别只看权限层
- **superuser 例外在 can_review 和 can_cancel 之间不对齐** (9/15 实战新发现) - Archery 上游 `Audit.can_review` 在 audit.current_status=WAITING + is_superuser=True 时返 True (superuser 例外), 但 `can_cancel` 默认 result=False 不走 superuser 例外, **两个权限判断逻辑不对齐**导致 UI 显示"能审"但实际"不能终止". 跨项目**权限判断对齐 checklist**必加 1 条: can_view/can_review/can_cancel/can_execute/can_rollback 等权限判断函数, 必保持 superuser 例外的一致性, 别某个加某个不加

## 同源 entry

- 9/11 17:55 DBA-bug-1 (大表 DDL alert 解析 drop index 失败)
- 9/11 18:50 DBA-bug-2 (反引号 schema 解析 + 主页面 banner)
- 9/11 19:30 DBA-bug-3 (ADD/DROP INDEX 大表 alert 丢失)
- 9/11 20:10 DBA-bug-3 hotfix (Django 跨行 {# #} 注释)
- 9/12 10:50 DBA-bug-4 (DDL 跨库业务方选错库大表 alert 不触发)
- 9/12 10:55 DBA-bug-5 (DDL 跨库镜像工单 + 历史库表不存在)
- 9/12 11:35 DBA-bug-5a (sync_trigger.py regex 漏反引号 schema)
- 9/14 10:11 archery 账号密码被改 (DBA 一条龙全包实战)
- **9/15 16:43 镜像工单取消按钮终态隐藏 (本次修)**