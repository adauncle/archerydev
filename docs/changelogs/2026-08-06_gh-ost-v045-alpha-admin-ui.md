# v0.4.5-alpha commit 4 —— admin + UI（task_type 筛选 + 批量 action + rebuild 进度面板）

**日期**: 2026-08-06
**作者**: mavis
**类型**: feat + refactor（admin 改造 + 新模板 + 2 个新 view）

## 背景

v0.4.5-alpha commit 3（`52b875b`）建好了 rebuild 端点。DBA 通过端点能触发 rebuild，
但 admin 列表没法区分 ghost / rebuild，也没专门的 rebuild 进度面板。这次补全。

## 改动内容

### 1. `admin.py` 改造

| 改动 | 说明 |
|------|------|
| `list_display` 加 `task_type_badge` + `source_link` | 列表行首列展示 task_type 颜色徽章（ghost=蓝/rebuild=绿） |
| `list_filter` 加 `task_type` | admin 右侧筛选器按任务类型过滤 |
| `search_fields` 加 `target_table` | 搜索支持 rebuild 任务的 db.table |
| `readonly_fields` 加 `task_type` / `target_table` / `related_task_id` | 详情页不可改 |
| 加 `admin_batch_rebuild` action | 批量引导 DBA 走端点（alpha 阶段 admin 不直接触发） |
| 改 `admin_retry` | rebuild task 暂不支持 admin retry（要 instance 入参） |
| 改 `admin_rollback` | rebuild task 直接标 rolled_back（无影子表可 drop） |

**列表视图**（DBA 看）：
```
id | task_type | 来源              | 状态徽章 | 当前阶段 | 进度条 | ...
 5 | gh-ost    | 工单 #123 改列宽   | 成功     | done     | 100%   |
 6 | 碎片回收  | archery_dev.x      | 执行中   | copying  | 87%    |
```

**rebuild 任务的 admin_retry 行为**：
- task_type=rebuild + status in (failed/cancelled) → 跳过 + 提示"DBA 通过 /gh_ost/rebuild/start/ 重新触发"
- task_type=ghost 行为不变

### 2. 新建 `templates/ddl_gh_ost/progress_rebuild.html`

从 `progress.html` fork 出来，差异：
- 顶部标题改 "碎片回收进度" + v0.4.5 badge
- sub 段不显示工单，改显示 `db.table` + 发起人 + task_id
- 去掉 "启动 gh-ost" 按钮（rebuild 启动走端点）
- JS 端点改 `/gh_ost/rebuild/status/<task_id>/`
- 适配 rebuild 任务无 `workflow` 字段

### 3. `views.py` 加 2 个 view

| 端点 | 视图函数 | 作用 |
|------|---------|------|
| `GET /gh_ost/rebuild/progress/<task_id>/` | `rebuild_progress_page` | 渲染 `progress_rebuild.html` 模板 |
| `GET /gh_ost/rebuild/status/<task_id>/` | `rebuild_status` | rebuild 任务进度 JSON（前端 polling） |

`rebuild_status` 字段跟 ghost `status` 端点一致（pct / rows / speed / eta / message / threads_running / stderr_tail / error_message），方便前端复用 render 函数。

### 4. `urls.py` 注册路由

```python
path("rebuild/status/<int:task_id>/", views.rebuild_status, name="rebuild_status"),
path("rebuild/progress/<int:task_id>/", views.rebuild_progress_page, name="rebuild_progress"),
```

## 兼容性

- ghost admin 端点全部保留（admin_cancel / admin_retry / admin_rollback 兼容 rebuild 但 ghost 行为不变）
- ghost 进度面板 `progress.html` 不动
- search_fields 加 `target_table` 不影响旧查询
- readonly_fields 加 3 字段不影响 admin 修改流程

## 验证

- `python -m py_compile` admin.py / views.py / urls.py：✅ 通过
- 134 dev 端到端验证：待 commit 6 演练时一起做

## 下一步

- [ ] commit 5: `services/queue.py` —— 同表冲突 FIFO 排队（替换 commit 3 的 409 拒绝）
- [ ] commit 6: 134 dev 演练（accesscard_black_detail 造碎片 → 重建）

## 关联

- 设计稿: `docs/designs/2026-08-05_gh-ost-product-design.html` v0.4.5 §6
- 规划: `docs/reports/2026-08-06_功能开发计划_v3.xlsx` row 45
- 共享: `services/poller.py`（3s 轮询）/ `services/notify.py`（钉钉群）
