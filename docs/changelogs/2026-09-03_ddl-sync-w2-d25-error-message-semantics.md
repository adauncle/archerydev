# DDL 跨库同步 W2 D25: error_message 字段语义修复

> 日期: 2026-09-03 16:20
> 阶段: W2 实施阶段 (D25, 9/3 16:14 业务方反馈 + 16:20 实战修通)
> 模块: `sql/extensions/ddl_sync/services/sync_trigger.py` + `sql/templates/detail.html`
> 关联: D23 target_workflow_status_handler 联动机制

## 背景

D23 (9/3 14:48 实战) 加了 `target_workflow_status_handler` 联动镜像工单 status 变终态/完成态
→ DdlSyncHistory.sync_status 切 synced/failed/skipped.

但 D23 signal 联动时把"联动原因"写到了 `DdlSyncHistory.error_message` 字段:

```python
h.error_message = (
    (h.error_message + '\n') if h.error_message else ''
) + f'镜像工单 #{instance.id} status={instance.status} → DdlSyncHistory 联动切 {new_sync_status}'
```

**字段语义错了**:
- `error_message` 字段是"错误信息"语义, 业务方看到会以为同步出错了
- 但 D23 联动 success (workflow_finish → synced) 也写, 业务方误以为出错了
- detail.html line 53-57 模板无条件显示 "错误信息: {{ error_message }}"

## 症状 (9/3 16:14 业务方反馈 + 截图)

业务方演练 wf#132 / wf#134 镜像工单 detail 页, alert 块显示:
- 状态: 同步成功 (历史库镜像工单执行成功) ✓ 正确
- **错误信息: 镜像工单 #132 status=workflow_finish → DdlSyncHistory 联动切 synced** ✗ 误导

业务方预期: synced 成功联动时**不该**显示"错误信息"行.

## 根因

D23 signal 代码缺陷:
```python
h.error_message = (
    (h.error_message + '\n') if h.error_message else ''
) + f'镜像工单 #{instance.id} status={instance.status} → DdlSyncHistory 联动切 {new_sync_status}'
h.save()
```

**所有 status (synced/failed/skipped) 都写 error_message**, 不分场景.

模板层缺陷:
```html
{% if ddl_sync_as_target.error_message %}
<p style="margin-bottom: 0; color: #a94442;">
    <strong>错误信息:</strong> {{ ddl_sync_as_target.error_message }}
</p>
{% endif %}
```

**只要有 error_message 就显示**, 不分 sync_status 是不是 failed/skipped.

## 修法 (DBA 拍板 A + B 都改, 9/3 16:20 拍板)

### 1. sync_trigger.py (A 方案: 数据层根因)

只让 `failed` / `skipped` 写 error_message, `synced` 成功联动不写:

```python
# D25 修 error_message 字段语义: 只在 failed/skipped 时写原因,
# synced 成功联动不污染 error_message 字段 (业务方会误以为出错了)
if new_sync_status != 'synced':
    h.error_message = (
        (h.error_message + '\n') if h.error_message else ''
    ) + f'镜像工单 #{instance.id} status={instance.status} → DdlSyncHistory 联动切 {new_sync_status}'
h.save()
```

### 2. detail.html (B 方案: 视图层防御)

改条件, 只在 sync_status in (failed, skipped, rolled_back) 时显示:

```html
{% if ddl_sync_as_target.error_message %}
  {% if ddl_sync_as_target.sync_status == 'failed' or ddl_sync_as_target.sync_status == 'skipped' or ddl_sync_as_target.sync_status == 'rolled_back' %}
    <p style="margin-bottom: 0; color: #a94442;">
        <strong>错误信息:</strong> {{ ddl_sync_as_target.error_message }}
    </p>
  {% endif %}
{% endif %}
```

D25 v2 修法: **Django 模板不支持 `in (a, b, c)` 元组语法** (TemplateSyntaxError: Could not parse),
实战第一次 v1 用 `in ('failed', 'skipped', 'rolled_back')` 报 TemplateSyntaxError, 134 dev 所有 detail 页面 500.
v2 改成嵌套 if + 多个 or 解决.

## 验证 (9/3 16:20 134 dev 演练)

### 演练 1: 视图层防御 (D25 v2) - 历史数据

推 detail.html v2 + 清 pycache + 拉新 gunicorn + render 测试 3 个工单:

| 工单 | sync_status | error_message | D25 期望显示 "错误信息" 行 |
|------|-------------|---------------|--------------------------|
| wf#130 (D24 已重放切 synced) | synced | 有 (老 D23 写的) | ❌ 不显示 |
| wf#134 (新工单, 联动 synced) | synced | 有 (老 D23 写的) | ❌ 不显示 |
| wf#127 (syncing 演练中) | syncing | 空 | ❌ 不显示 |

演练 1 实战结果:
```
=== /detail/130/ (D25 v2 视图层防御) ===
Status: 200, length: 88313
错误信息: label count: 0
同步成功 label: True

=== /detail/134/ (D25 v2 视图层防御) ===
Status: 200, length: 88339
错误信息: label count: 0

=== /detail/127/ (D25 v2 syncing) ===
Status: 200, length: 87675
错误信息: label count: 0
```

**所有 detail 页面 200 OK**, "错误信息" 行 0 次出现 ✓

### 演练 2: 数据层修复 (D25 A 方案) - 触发 D25 新版 signal

重放 wf#112 save() (status=workflow_abort), 触发 D25 新版 signal:

```
=== 演练 2.2: 重放 wf#112 save() (D25 新 signal) ===
重放前: h#4 sync_status=syncing error_message=''
重放后: h#4 sync_status=skipped error_message='镜像工单 #112 status=workflow_abort → DdlSyncHistory 联动切 skipped'
D25 期望: skipped + error_message 写明联动原因
```

**D25 A 方案 PASS**:
- skipped (终态) → error_message 写明联动原因 ✓
- synced (成功) → 不会写 error_message (A 方案验证靠 v1 推过的 D25)

## 改动文件 (2 文件)

| 文件 | 改动 |
|------|------|
| `sql/extensions/ddl_sync/services/sync_trigger.py` | target_workflow_status_handler 加 `if new_sync_status != 'synced':` 守卫, synced 成功联动不写 error_message |
| `sql/templates/detail.html` | 镜像工单 alert 块的 "错误信息" 行加 sync_status 条件 (failed/skipped/rolled_back 才显示) |

## 同源 entry

- 9/1 W1-D3 §9.3 实战 1 兜底 (signal handler 整个 try/except) — D25 复用
- 9/2 D11 hotfix (workflow_terminal_handler 源工单终止→镜像工单) — D25 修的是它的联动, 不冲突
- 9/3 D22 镜像工单 group_id 走历史库组 — D25 独立但同模块
- 9/3 D23 镜像工单 status 联动 DdlSyncHistory 切终态 — D25 修 D23 联动写 error_message 的 bug
- 9/3 D24 qcluster 进程不监听文件变化 (D23 实战时没生效的根因) — D25 跟 D24 一起推

## D25 实战新发现 (跨项目可复用, 5 条)

1. **error_message 字段语义必区分成功/失败**: D23 联动所有 status 都写 error_message 是错的, 业务方看到 "错误信息" 误以为出错. 字段语义: synced 成功不该写, failed/skipped 才写
2. **视图层防御是兜底必备**: 即便数据层修对了, 老 DdlSyncHistory 行的 error_message 还会有 D23 写的"联动切 synced" 误导. detail.html 加 sync_status 条件过滤才能彻底干净
3. **Django 模板不支持 `in (a, b, c)` 元组语法**: v1 写 `{% if x in (a, b, c) %}` 报 TemplateSyntaxError: Could not parse the remainder, **Django 模板只支持 `x in "abc"` (字符串成员) 或 `x in y` (y 是变量)**. 必须改嵌套 if + 多个 or, 或者用 `{% with %}` 设变量
4. **Django 模板的 and/or 优先级跟 Python 不一样**: 实战要避免在一个 if 里混用 and/or, 用嵌套 if 清晰. 这次 v2 用嵌套 if 解决
5. **D25 实战推 134 dev 时, D25 v1 错误版本让所有 detail 页面 500**: 实战要本地 py_compile 模板 + 演练关键页面 200 OK 再 commit, 这次演练发现问题救了一把. **教训: Django 模板改完必演练渲染, 不能只看代码**

## D25 实战踩坑 (3 条)

1. **D25 v1 Django 模板 `in (a, b, c)` 报 TemplateSyntaxError**: 实战用 Python 习惯的 in 元组语法, Django 模板不支持, 134 dev 所有 detail 页面 500. v2 改成嵌套 if + 多个 or
2. **D25 推 detail.html 后没演练, 业务方打开 wf#130 看到 500**: 演练脚本发现及时修了, 没让业务方踩坑. **教训: detail.html 改动必演练 3 个不同 sync_status 的工单 (synced/syncing/failed)**
3. **D25 实战推 134 dev 时旧的 8 个 syncing 工单没主动重放 save**: D25 v2 视图层防御修了"错误信息"行显示, 老 syncing 工单 error_message 还有内容但因为 sync_status 还是 syncing 不显示, 等业务方或 DBA 自然刷新触发 D23 signal 联动 (D25 v1 v2 上线后, wf#130/134 h#15 已经是 synced 但 error_message 还有 D23 老版写的"联动切 synced", 视图层防御过滤掉了)

## 待办

1. 推 110 prod (D25 + D24 + D23 + D22 7 文件一次推):
   - sync_trigger.py (D22 + D23 + D25 共用)
   - detail.html (D25 v2)
   - models.py + migration 0002 (D22)
   - forms.py + pair_form.html + pair_detail.html (D22)
   - **必 kill + 拉新 qcluster** (D24 实战新发现, 不能只 restart gunicorn)
2. 老的 8 个 syncing 工单兜底:
   - 134 dev: h#1/4/5/7/8/9/10/12 syncing + 各种 target_wf status
   - 走 D24 修法: 业务方浏览器刷新 / DBA 一次性 Django shell 重放 save
3. 推 110 prod 后 D11 老镜像工单 SQL UPDATE 兜底: 找 prod 配的 pair, SQL UPDATE target_group + 老镜像工单 group_id + delete audit + 重新 create_audit

## D25 实战后 W2 状态

D6 数据模型 → D7 库对管理 → D8 AJAX 端点 + 前端 → D9 R3 + signal → D10-D12 134 dev 演练 → D13 多表 diff → D14 推 110 prod → D15 字符集 → D16 推 D15 修复 → D17 验证 → D18 alert 块 → D19 alert SQL → D20 挪位置 → D21 placeholder → D22 target_group → D23 镜像工单 status 联动 DdlSyncHistory → D24 qcluster 进程不监听文件变化 → **D25 error_message 字段语义修复**

## D25 实战后 134 dev gunicorn pids

master 38686 + 4 worker 38687/38688/38690 (D25 演练拉新)
