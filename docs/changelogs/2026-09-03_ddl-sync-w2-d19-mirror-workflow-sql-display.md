# W2 D19 — 镜像工单 alert 块加 SQL 直接显示 (9/3 10:15)

## 背景

9/3 10:00 业务 RD (马克群) 在 134 dev `/detail/121/` (新镜像工单, status=
`workflow_manreviewing` 等审批) 反馈 "镜像工单还是看不到提交的 SQL"。

9/2 22:30 D18 推了 alert 块 (🤖 镜像工单 + 源工单 link), 但 SQL 内容没显示。
用户视角: 拿到镜像工单想知道 "这工单到底要执行什么 SQL"。

## 根因分析

- `sql/templates/detail.html` "工单详情" tab 主表是 `workflow_log` (审核日志) 表格
- `detailView: true` (line 1116) + `detailFormatter` (line 1118-1138) 在子表
  展开时渲染完整 SQL
- 但 wf#121 状态 `workflow_manreviewing` (等审批), **没有审核日志行**
  → 主表空 ("没有找到匹配的记录") → 用户点不开 + 展开看不到 SQL
- 镜像工单 `sql_content` 109 字符完整存进 `SqlWorkflowContent` 表 (D9 阶段 1
  `sync_trigger.py` 实战正确建 OneToOne 关联), 但 `detail.html` 模板没暴露

## 修法 (2 文件)

### sql/views.py

1. 顶部 `from .models import` 加 `SqlWorkflowContent` (D9 实战踩坑, views.py 之前没 import)
2. `detail()` 函数 D18 alert 块查询逻辑里加 `mirror_sql_content` 变量:

```python
if ddl_sync_as_target and ddl_sync_as_target.target_workflow_id:
    sql_content_obj = SqlWorkflowContent.objects.filter(
        workflow_id=ddl_sync_as_target.target_workflow_id
    ).first()
    if sql_content_obj:
        mirror_sql_content = sql_content_obj.sql_content
```

3. `context` dict 加 `"mirror_sql_content": mirror_sql_content`

### sql/templates/detail.html

镜像工单 alert 块 (line 49 "表:" 之后, `</p>` 关闭之后) 插 SQL 块:

```html
{% if mirror_sql_content %}
<div style="margin-top: 8px; margin-bottom: 0;">
    <strong>📝 自动生成的 SQL (镜像工单实际内容):</strong>
    <pre style="background: #f5f5f5; padding: 10px 12px; border-radius: 4px;
                margin-top: 4px; margin-bottom: 0;
                font-family: 'Courier New', monospace; font-size: 13px;
                white-space: pre-wrap; word-wrap: break-word;
                max-height: 240px; overflow-y: auto;">{{ mirror_sql_content }}</pre>
</div>
{% endif %}
```

样式要点:
- `Courier New monospace` + 灰底 + `pre-wrap` (避免长 SQL 撑爆页面)
- `max-height: 240px; overflow-y: auto` (超过 240px 可滚动)
- 跟 8/26 21:57 JS ReferenceError 教训: SQL 内容用 view 端查询 + template
  `<pre>` 渲染, 不用 `escapejs` filter (Django 4.0+ 已移除), 不用 JS 变量拼

## 134 dev 演练 (Django test client + force_login archery)

`/detail/121/` (新镜像工单, status=`workflow_manreviewing` 等审批):

| 验证项 | 期望 | 实际 |
|------|------|------|
| HTTP Status | 200 | 200 ✓ |
| Content length | 增长 (SQL 块 + 容器) | 95512 (比 D18 93059 多 2453) ✓ |
| 🤖 镜像工单 alert | 出现 | 1 次 ✓ |
| "自动生成的 SQL" 标题 | 出现 | 1 次 ✓ |
| 完整 SQL pre 块 | 出现 | pre 长度 129 ✓ |
| SQL 内容 | `ALTER TABLE accesscard_black_detail add COLUMN test2 VARCHAR(256) not null DEFAULT 'test2' COMMENT 'test2';` | ✓ |
| 源工单 wf#120 link | 1 个 | 1 次 ✓ |
| 库对 "accesscard 库对 (134 dev 演练)" | 显示 | 1 次 ✓ |
| 同步状态 蓝色徽章 | syncing → info | 1 次 ✓ |

## 134 dev 部署

- 备份 `/backup/d19_20260903_1005/` (views.py.bak 42369 bytes + detail.html.bak 98716 bytes)
- SFTP 推 `views.py` (md5 `95147d47...` = local) + `detail.html` (md5 `036fd3aa...` = local)
- gunicorn pids: 32395 (master) + 32398/32403/32419/32420 (4 worker, 10:11 拉新)
- 9003 端口 LISTEN ✓

## 实战踩坑 (D19 实战总结)

1. **SqlWorkflowContent 没 import views.py 顶部** (D9 实战踩坑复用):
   第一次 push 后演练 500 (NameError), 修法 views.py 顶部 `from .models import`
   加 SqlWorkflowContent. D9 `sync_trigger.py` 用过 OK, 但 views.py `detail()`
   实战时忘 import, 实战必查 imports
2. **演练必查 gunicorn error log**: 第一次演练 Status: 200 但 view 内部 500
   (镜像 SQL 块没渲染), 实战查 `gunicorn_d19.log` 看到 "ddl_sync history
   lookup failed" + NameError 才定位 (D14 D12 实战复用)
3. **SQL 块 `<pre>` 样式**: 实战必 `pre-wrap` + Courier New + max-height 240,
   避免长 SQL 撑爆页面 (D18 alert 块实战发现 60 行已经够宽, 实战更长)

## 110 prod 状态 (待推)

- 110 prod `detail.html` 仍是 7/19 上游版 (md5 `82198afe...`), 没 SQL 块
- 110 prod `views.py` 顶部也没 `SqlWorkflowContent` import (跟 134 dev D19 实战前一致)
- 推 110 时机: 等用户拍板 (跟 D18 实战一致), 推 110 必带 detail.html + views.py
  2 文件, 含:
  - 8/26 21:34 字段 diff inline 区域 (commit 0a04775)
  - 9/2 17:30 JS ReferenceError 修复 (commit 2a04a12)
  - 9/2 22:30 DDL 跨库同步镜像/源工单 alert 块 (commit 55ec7fa)
  - 9/3 10:15 镜像工单 alert 块 SQL 直接显示 (本次)

## 推 110 prod 时机 (D19 实战新发现)

- 推 2 文件: `views.py` + `detail.html` (跟 134 dev 实战一致)
- 8/26 + 9/2 + 9/3 共 4 个功能一起推 (字段 diff + alert 块 + JS fix + SQL 块)
- 推前必查 views.py 顶部 `from .models import` 是否含 SqlWorkflowContent
  (D9 实战发现 views.py 缺, 实战必加)

## 同源 entry

- D18 9/2 22:30 alert 块基础 (commit `55ec7fa`)
- D9 9/1 18:00 `sync_trigger.py` 创建 `SqlWorkflowContent` OneToOne 必建 (commit `5420c81`)
- 8/26 21:57 JS ReferenceError 修复 (commit `2a04a12`, escapejs filter 移除)
- 8/13 AJAX 守卫教训 (try/except 兜底)
- 134 dev 演练查 gunicorn error log 套路 (D14 D12 实战复用)

## W2 进度 (9/3 上午新增 D19)

- D6 ✓ (9/1 14:45): 3 张表 migration
- D7 ✓ (9/1 16:15): 库对管理 CRUD + admin + 2 template + base.html
- D8 ✓ (9/1 17:45): 5 AJAX 端点 + 4 service + pair_detail + 5 modal + JS
- D9 ✓ (9/1 18:15): R3 走当前配置 + signal + 8/13 教训应用
- D10 ✓ (9/2 10:30): 134 dev 端到端演练 5 Case
- D11 ✓ (9/2 11-15): 134 dev 6 hotfix
- D12 ✓ (9/2 17:30): 134 dev detail/119 JS ReferenceError 修复
- D13 ✓ (9/2 18:30): 多表 DDL 字段 diff bug 修复
- D14 ✓ (9/2 19:40): 推 110 prod 修复汪银和工单 (commit ed1c20c)
- D15 ✓ (9/2 20:30): 字符集 implicit/explicit 区分 (commit e939ffe)
- D16 ✓ (9/2 21:10): 推 D15 修复实战 110 prod c9236a0 (commit 289adc7)
- D17 ✓ (9/2 21:43): 验证 110 prod D15 修复实战生效
- D18 ✓ (9/2 22:30): DDL 跨库同步 镜像/源工单 alert 块 (commit 55ec7fa)
- **D19 ✓ (9/3 10:15): 镜像工单 alert 块加 SQL 直接显示 (本次)**

## 下次推 prod checklist 必加 (D19 实战新发现)

1. **镜像工单 UX 必走 2 文件 3 块**: `detail.html` (alert 块 + SQL pre 块) +
   `views.py` (DdlSyncHistory 双向查询 + SqlWorkflowContent SQL 提取 + 顶部
   `import SqlWorkflowContent`). 任何镜像工单相关 UX 改动必走 3 块完整
2. **views.py 实战必查 imports**: 任何新加的 ORM 用法, 实战前 grep
   `views.py` 顶部 `from .models import` 看是否需要加新 model. D9
   `sync_trigger.py` 用 SqlWorkflowContent OK, views.py `detail()` 实战时
   忘 import, 实战必查 (跟 D12 实战 detail.html 忘推 js 引用 SQL 教训同套路)
3. **演练必查 gunicorn error log**: 第一次演练 Status: 200 但 view 内部 500
   实战 `gunicorn_d19.log` 看到 `ddl_sync history lookup failed` + NameError
   才定位. 实战前后必查 gunicorn error log (D14 D12 实战复用)
4. **SQL 显示必走 `<pre>` + Courier New + pre-wrap + max-height 240 + overflow-y auto**:
   实战任何 SQL 内容显示块必走这套样式, 避免长 SQL 撑爆页面
