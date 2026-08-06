# v0.4.5-alpha commit 3 —— rebuild 端点（视图 + 路由）

**日期**: 2026-08-06
**作者**: mavis
**类型**: feat（新增 2 个端点 + 路由注册）

## 背景

v0.4.5-alpha commit 2（`e8b2cf3`）建好了 `services/rebuild.py` 跑 gh-ost 重建逻辑。
但没有端点让 DBA 触发。DBA 只能手动调 Python / SQL —— 不友好。

这次新增 2 个端点 + 路由注册，让 DBA 通过 admin / 前端就能触发。

## 改动内容

### 1. `views.py` 新增 2 个端点

#### `GET /gh_ost/rebuild/list/?instance_id=N`

查 instance 下所有 InnoDB 表，按碎片率倒序列出。

```json
{
  "ok": true,
  "instance_id": 1,
  "instance_name": "134-dev-archery",
  "tables": [
    {"db": "archery_dev", "table": "accesscard_black_detail",
     "data_free_mb": 1024, "size_mb": 4096, "data_free_pct": 25.0},
    ...
  ]
}
```

- 走 `_get_creds(instance)`（继承 v0.3.0 的 .env 兜底）
- 查 `INFORMATION_SCHEMA.TABLES`（不走 Django ORM）
- 排除 mysql / information_schema / performance_schema / sys
- 限 200 行（防大库爆掉）
- 错误处理：连 MySQL 失败 → 500 + hint 提示配置 .env

#### `POST /gh_ost/rebuild/start/`

DBA 选表触发 rebuild task。

入参（JSON 或 form-encoded）：
```json
{"instance_id": 1, "db": "archery_dev", "table": "accesscard_black_detail"}
```

流程：
1. 灰度开关校验 `CUSTOM_GH_OST_REBUILD_ENABLED`（默认 True）
2. 入参校验（instance_id / db / table 必填）
3. 同表冲突检查（已有 running/queued/cut_over → 409 拒绝，alpha 阶段）
4. 写 `DdlGhostTask`（`task_type="rebuild"`, `workflow=NULL`, `target_table="db.table"`）
5. `start_rebuild_process` Popen gh-ost
6. 写 PID + started_at + `status="running"`
7. 启动 poller 3s 轮询

返回：
```json
{"ok": true, "task_id": 42, "status": "running", "pid": 12345, "target_table": "archery_dev.accesscard_black_detail"}
```

错误：
- 403: 灰度开关关闭
- 400: 入参不全 / JSON 解析失败
- 404: instance 不存在
- 409: 同表已有 rebuild task 在执行
- 500: gh-ost 启动失败

### 2. `urls.py` 注册路由

```python
path("rebuild/list/", views.rebuild_list, name="rebuild_list"),
path("rebuild/start/", views.rebuild_start, name="rebuild_start"),
```

## 同表冲突处理（alpha 阶段）

commit 3 暂用 **拒绝**（409），完整 FIFO 排队见 commit 5（`services/queue.py`）。

```python
# 现有逻辑
conflicting = DdlGhostTask.objects.filter(
    task_type="rebuild", db_name=db, table_name=table,
    status__in=["queued", "running", "cut_over"],
).first()
if conflicting:
    return JsonResponse({"ok": False, "error": ...}, status=409)
```

## 兼容性

- ghost 端点（precheck / enable / start / cancel / retry / rollback / status / progress）零影响
- 不改 urlpatterns 已有 8 条
- 不改 views.py 已有 8 个函数
- 不改 services/ 已有文件

## 验证

- `python -m py_compile views.py urls.py`：✅ 通过
- 134 dev 端到端验证：待 commit 6 演练时一起做

## 下一步

- [ ] commit 4: admin + UI —— list_filter 加 task_type + 批量 action + progress.html 适配 rebuild
- [ ] commit 5: services/queue.py —— 同表冲突排队（替换 commit 3 的 409 拒绝）
- [ ] commit 6: 134 dev 演练

## 关联

- 设计稿: `docs/designs/2026-08-05_gh-ost-product-design.html` v0.4.5 §5
- 规划: `docs/reports/2026-08-06_功能开发计划_v3.xlsx` row 44
- 共享设施: `services/poller.py`（3s 轮询）/ `services/notify.py`（钉钉群）
