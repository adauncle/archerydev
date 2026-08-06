# v0.4.5-alpha skeleton —— gh-ost 任务表支持碎片回收

**日期**: 2026-08-06
**作者**: mavis
**类型**: refactor + feat（schema 改造 + 灰度开关）

## 背景

v0.3.0 设计的 `DdlGhostTask` 表只能挂 SQL 工单（OneToOneField），用于 gh-ost 改造
工单。v0.4.0 归档专题要求支持"碎片回收"——DBA 手动选表跑 gh-ost 触发空 alter，
**不依赖 SQL 工单**。所以模型需要改造。

## 改动内容

### 1. 数据模型改造（`sql/extensions/ddl_gh_ost/models.py`）

| 字段 | 旧 | 新 |
|------|----|----|
| `workflow` | `OneToOneField` | **`ForeignKey(null=True, blank=True)`** |
| `task_type` | (无) | **`CharField(ghost/rebuild, default="ghost", db_index=True)`** |
| `target_table` | (无) | **`CharField(128, db_index=True, default="")`** |
| `related_task_id` | (无) | **`BigIntegerField(null=True, blank=True)`** |
| Meta 约束 | (无) | **`UniqueConstraint(task_type, workflow)`** |

- **ghost 场景**（v0.3.0 沿用）：每个工单一条 task，`task_type="ghost"`, `workflow=工单`
- **rebuild 场景**（v0.4.5 新增）：每个表一条 task，`task_type="rebuild"`, `workflow=NULL`, `target_table="db.table"`
- `unique_together(task_type, workflow)`：同类型同工单唯一（rebuild 的 NULL workflow 视为不同，允许多条）
- `task_type` 默认 `"ghost"` —— 存量数据全是 ghost，零迁移成本

### 2. 灰度开关（`archery/settings.py`）

3 个新环境变量：

| 变量 | 默认 | 含义 |
|------|------|------|
| `CUSTOM_GH_OST_REBUILD_ENABLED` | `True` | DBA 手动 + 一键批量触发 rebuild 的总开关 |
| `CUSTOM_GH_OST_REBUILD_AUTO_LINK_ARCHIVE` | `False` | 归档完成后自动触发碎片回收（v0.4.2 联动） |
| `CUSTOM_GH_OST_REBUILD_CRON_ENABLED` | `False` | cron 自动调度碎片回收（v0.4.4 接入） |

- 触发默认开启（DBA 手动 + 一键批量）：**`REBUILD_ENABLED=True`**
- 归档联动 + cron：**默认关**（安全优先，要用显式开）

### 3. Migration

`sql/extensions/ddl_gh_ost/migrations/0002_v045alpha_model.py`

5 个 operation：
1. AlterField workflow: OneToOne → ForeignKey(null=True)
2. AddField task_type
3. AddField target_table
4. AddField related_task_id
5. AddConstraint UniqueConstraint(task_type, workflow)

## 兼容性

- 存量数据零迁移：所有现有 task 的 task_type 默认 "ghost"
- OneToOne → ForeignKey 不会破坏现有 unique 索引（Django 自动 DROP）
- 不会影响 v0.3.0 已发布功能

## 验证

- 134 dev `python manage.py makemigrations ddl_gh_ost --check --dry-run`：待跑
- 134 dev `python manage.py migrate ddl_gh_ost --check`：待跑
- 134 dev `python manage.py showmigrations ddl_gh_ost`：待跑

## 下一步

- [ ] commit 2: `services/rebuild.py` —— build_rebuild_command（rebuild 场景拼 gh-ost CLI）
- [ ] commit 3: views + urls —— `/gh_ost/rebuild/<table_id>/` 端点
- [ ] commit 4: admin + UI —— list_filter 加 task_type、批量 action
- [ ] commit 5: `services/queue.py` —— 同表冲突排队 + 关联归档
- [ ] commit 6: 134 dev 演练 —— accesscard_black_detail 造碎片 → 重建

## 关联

- 设计稿: `docs/designs/2026-08-05_gh-ost-product-design.html` v0.4.5 §2/§3
- 规划: `docs/reports/2026-08-06_功能开发计划_v3.xlsx` row 42-47
- 上游变更: `sql/extensions/ddl_gh_ost/models.py` 头部加 `## CUSTOM-MODIFIED` 注释
