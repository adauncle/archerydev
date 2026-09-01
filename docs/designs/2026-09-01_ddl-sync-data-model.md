# 9/1 数据模型设计 (DdlSyncPair + DdlSyncTable + DdlSyncHistory) (9/1 09:30)

> **W1 设计阶段 D2 (9/1 周二)**: 3 张表 migration 设计
>
> 来源: R 之前原版 8/21 设计稿 §5 数据模型 (3 张表) + R1/R2/R3 增量改动

---

## 1. 3 张表总览

| 表 | db_table | 用途 | 阶段 |
|---|---|---|---|
| **DdlSyncPair** | `ext_ddl_sync_pair` | 库对配置 (业务库 ↔ 历史库) | R 之前已规划 |
| **DdlSyncTable** | `ext_ddl_sync_table` | 同步表清单 (业务库表 → 历史库) | R 之前已规划 |
| **DdlSyncHistory** | `ext_ddl_sync_history` | 同步历史审计 (业务库 DDL → 历史库镜像工单) | R 之前已规划 |

**R1/R2/R3 增量改动**:
- DdlSyncPair: `sync_mode` 默认值 `whitelist` → `blacklist` (R1)
- DdlSyncTable: 加 `sync_type` 字段 (whitelist/blacklist, R2)
- DdlSyncPair: 加 `filter_rule` JSONField (Phase 3, R3)
- DdlSyncPair: 加 `pending_tables` JSONField (Phase 2, R3)

---

## 2. DdlSyncPair (ext_ddl_sync_pair) 完整字段

```python
class DdlSyncPair(models.Model):
    SYNC_MODE_CHOICES = [
        ("blacklist", "黑名单 (默认, 业务库全同步, 显式排除)"),  # R1 改默认
        ("whitelist", "白名单 (DBA 显式选要同步的)"),  # R 之前原版默认
    ]

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=128)  # 配对名, 如 "accesscard 库对"
    source_instance = models.ForeignKey(
        Instance, on_delete=models.CASCADE, related_name="sync_pair_source"
    )
    source_db = models.CharField(max_length=64)
    target_instance = models.ForeignKey(
        Instance, on_delete=models.CASCADE, related_name="sync_pair_target"
    )
    target_db = models.CharField(max_length=64)
    sync_mode = models.CharField(
        max_length=16, choices=SYNC_MODE_CHOICES, default="blacklist"  # R1 改
    )
    enabled = models.BooleanField(default=True)
    # R3 Phase 2 加: 业务库新增表"待确认" 暂存
    pending_tables = models.JSONField(default=dict, blank=True)
    # 格式: {
    #   "accesscard_v2": {
    #     "detected_at": "实战时",
    #     "first_workflow_id": 12345,
    #     "history_size_bytes": 254803968,
    #   }
    # }
    # R3 Phase 3 加: 过滤规则持久化
    filter_rule = models.JSONField(default=dict, blank=True)
    # 格式: {
    #   "exclude_prefix": ["_log", "_bak", "_tmp", "_test"],
    #   "exclude_suffix": ["_history", "_archive"],
    #   "exclude_engine": ["MEMORY", "BLACKHOLE"],
    #   "min_size_bytes": 0,
    # }
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ext_ddl_sync_pair"
        unique_together = [("source_instance", "source_db")]
```

**字段说明**:
- `name`: 配对名,DBA 自己起 (例如 "accesscard 库对" / "hly_doc_model 库对")
- `source_instance` + `source_db`: 业务库 instance + 库名 (联合唯一)
- `target_instance` + `target_db`: 历史库 instance + 库名
- `sync_mode`: 同步模式 (whitelist / blacklist),**R1 改默认 blacklist**
- `enabled`: 库对启用/禁用 (软删)
- `pending_tables`: 业务库新增表"待确认" 暂存 (R3 Phase 2 加, Phase 1 留空, 字段先建好)
- `filter_rule`: 过滤规则持久化 (R3 Phase 3 加, Phase 1 留空, 字段先建好)
- `created_by` + `created_at` + `updated_at`: 审计字段

---

## 3. DdlSyncTable (ext_ddl_sync_table) 完整字段

```python
class DdlSyncTable(models.Model):
    """同步表清单 - 跟 ddl_sync_pair 多对一, 一个库对可配多张同步表"""

    SYNC_TYPE_CHOICES = [
        ("whitelist", "白名单 (要同步)"),  # R2 加
        ("blacklist", "黑名单 (不同步)"),  # R2 加
    ]

    id = models.AutoField(primary_key=True)
    pair = models.ForeignKey(
        DdlSyncPair, on_delete=models.CASCADE, related_name="tables"
    )
    table_name = models.CharField(max_length=128)
    # R2 加: 区分白名单 / 黑名单 (跟 pair.sync_mode 配合)
    sync_type = models.CharField(
        max_length=16, choices=SYNC_TYPE_CHOICES, default="whitelist"
    )
    # R 之前原版已有: 字段级调整规则 (Phase 3 用)
    transform_rule = models.JSONField(default=dict)
    # 格式: {
    #   "skip_columns": ["create_time", "update_time"],
    #   "rename_columns": {"old_name": "new_name"},
    # }
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ext_ddl_sync_table"
        # R2 改: 唯一约束加 sync_type (同一对库, 同一表, 不能既在白名单又在黑名单)
        unique_together = [("pair", "table_name", "sync_type")]
        indexes = [
            models.Index(fields=["pair", "table_name"]),
        ]
```

**字段说明**:
- `pair`: FK 库对 (一对多, 一个库对多张表)
- `table_name`: 业务库表名 (不带 schema, 例如 `accesscard_black_detail`)
- `sync_type`: R2 新加, 区分白名单/黑名单 (跟 `pair.sync_mode` 配合)
  - 如果 `pair.sync_mode = "blacklist"`, `sync_type` 实际只存 "blacklist" 记录 (排除的表)
  - 如果 `pair.sync_mode = "whitelist"`, `sync_type` 实际只存 "whitelist" 记录 (要同步的表)
- `transform_rule`: 字段级调整规则 (R 之前原版已有, Phase 3 用)
- `created_at`: 审计字段

**为什么 unique_together 加 sync_type**:
- R 之前原版: `unique_together = [("pair", "table_name")]` — 同一对库同一表只能 1 条
- R2 改: `unique_together = [("pair", "table_name", "sync_type")]` — 同一对库同一表可以既在白名单又在黑名单 (虽然逻辑矛盾, 但允许 1-click 配时重复)
- **实际不会同时存** (业务逻辑校验), 但 unique_together 加 sync_type 防止 race condition

---

## 4. DdlSyncHistory (ext_ddl_sync_history) 完整字段

```python
class DdlSyncHistory(models.Model):
    """同步历史审计 - 业务库 DDL 触发后, 历史库镜像工单执行情况"""

    SYNC_STATUS_CHOICES = [
        ("pending", "待执行 (业务库 DDL 已过审, 镜像工单待生成)"),
        ("syncing", "同步中 (镜像工单已生成, 还没执行)"),
        ("synced", "同步成功 (历史库镜像工单执行成功)"),
        ("skipped", "跳过 (白名单不含/黑名单含, 不生成镜像工单)"),
        ("failed", "失败 (历史库镜像工单执行失败)"),
    ]

    id = models.AutoField(primary_key=True)
    pair = models.ForeignKey(
        DdlSyncPair, on_delete=models.CASCADE, related_name="history"
    )
    # 业务库工单 (来源)
    source_workflow = models.ForeignKey(
        SqlWorkflow, on_delete=models.PROTECT, related_name="sync_source"
    )
    # 历史库镜像工单 (目标, 可能还没生成或生成失败)
    target_workflow = models.ForeignKey(
        SqlWorkflow, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sync_target"
    )
    table_name = models.CharField(max_length=128)
    # 原始 DDL (业务库)
    ddl_text = models.TextField()
    # 历史库实际执行的 DDL (可能跟业务库不同, 因为 transform_rule) — D2 拍板 3A
    transformed_ddl_text = models.TextField(blank=True, default="")
    # 同步状态
    sync_status = models.CharField(
        max_length=16, choices=SYNC_STATUS_CHOICES, default="pending"
    )
    # 失败信息 (sync_status=failed 时填)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ext_ddl_sync_history"
        indexes = [
            # pending 状态优先展示 (业务 RD 实时跟踪)
            models.Index(fields=["sync_status", "-created_at"]),
            # 按库对查历史
            models.Index(fields=["pair", "-created_at"]),
        ]
```

**字段说明**:
- `pair`: FK 库对
- `source_workflow`: 业务库工单 (PROTECT, 防止误删源工单导致历史审计断链)
- `target_workflow`: 历史库镜像工单 (SET_NULL, 工单可删, 审计保留)
- `table_name`: 同步的表名
- `ddl_text`: 原始业务库 DDL (审计完整记录, 不依赖 source_workflow.sql_content 仍存在)
- `sync_status`: 同步状态 (pending/syncing/synced/skipped/failed)
- `error_message`: 失败信息 (sync_status=failed 时填)
- `created_at` + `finished_at`: 时间审计

**5 个 status 状态机**:
```
pending (业务库 DDL 已过审)
   ↓ _create_target_workflow
syncing (镜像工单已生成, 还没执行)
   ↓ target_workflow.finish
synced (历史库镜像工单执行成功)
   ↓ OR
skipped (白名单不含/黑名单含, 不生成镜像工单)
   ↓ OR
failed (历史库镜像工单执行失败, error_message 填失败原因)
```

---

## 5. 3 张表 migration 计划

### migration 文件顺序

```
0001_initial.py             # 创 3 张表
0002_ddlsynctable_sync_type.py  # R2 加 sync_type 字段 + 改 unique_together
0003_ddlsyncpair_blacklist_default.py  # R1 改 sync_mode default
0004_ddlsyncpair_pending_tables.py  # R3 Phase 2 加 pending_tables
0005_ddlsyncpair_filter_rule.py  # R3 Phase 3 加 filter_rule
```

**5.7/8.0 兼容**: 跟 ddl_gh_ost 4 个 migration 8/18 演练一致 (`MakeField` 模式 + `if connection.vendor == 'mysql'` 检测)

### 推 110 必做 (避坑 8/26 实战踩坑)

- **5 步必做**: 备份 / 比对 SECRET_KEY / .env 完整 review / 推 4 文件 / restart + smoke test
- **migration 单独建个 management command**: `python manage.py migrate_ext_ddl_sync` (跟 ddl_gh_ost 8/24 实战一致)
- **134 dev 端到端演练**: 配 1 个真实库对 (hly_accesscard) + 1 条真实 DDL 触发 + 验证 history 记录

### 老库对兼容 (避坑 6.3 风险)

- `sync_mode` 从 `whitelist` 改 `blacklist` 默认值, **老库对默认值不变** (新库对才生效)
- migration 用 `default=` 字段, 老库对需 DBA 手动改 `sync_mode` 才会变 (避坑 9.1 sync_mode 风险)

---

## 6. 数据模型 ER 图 (ASCII)

```
                            ext_ddl_sync_pair
                          ┌─────────────────────┐
                          │ id (PK)              │
                          │ name (UNIQUE)        │
                  ┌───────│ source_instance (FK) │──────┐
                  │       │ source_db            │      │
                  │       │ target_instance (FK) │──┐   │
                  │       │ target_db            │  │   │
                  │       │ sync_mode (default   │  │   │
                  │       │   'blacklist')       │  │   │
                  │       │ enabled              │  │   │
                  │       │ pending_tables (JSON)│  │   │
                  │       │ filter_rule (JSON)   │  │   │
                  │       │ created_by/at        │  │   │
                  │       └─────────────────────┘  │   │
                  │                                  │   │
                  │ unique (source_instance,        │   │
                  │         source_db)              │   │
                  │                                  │   │
                  │ 1:N                              │   │
                  ▼                                  ▼   ▼
       ext_ddl_sync_table                   sql_instance (复用)
     ┌─────────────────────┐             ┌─────────────────┐
     │ id (PK)              │             │ id (PK)         │
     │ pair_id (FK)         │──┐          │ host, port,     │
     │ table_name           │  │          │ user, password  │
     │ sync_type (R2 加)   │  │          │ ...             │
     │   'whitelist'        │  │          └─────────────────┘
     │   'blacklist'        │  │
     │ transform_rule (JSON)│  │
     │ created_at           │  │
     └─────────────────────┘  │
                               │
                               │ 1:N
                               ▼
                    ext_ddl_sync_history
                  ┌─────────────────────────┐
                  │ id (PK)                  │
                  │ pair_id (FK)             │──┐
                  │ source_workflow_id (FK)  │  │  (复用 sql_workflow)
                  │ target_workflow_id (FK)  │  │  (复用 sql_workflow)
                  │ table_name               │  │
                  │ ddl_text                 │  │
                  │ sync_status (5 选 1)     │  │
                  │ error_message            │  │
                  │ created_at               │  │
                  │ finished_at              │  │
                  └─────────────────────────┘  │
                                              │
                                              │
                       1:N (sync_history) ─────┘
```

---

## 7. 最终决策 (4 个细节拍板 9/1 09:15)

DBA 拍板 4 个细节全部按建议落地:

1. ✅ **`DdlSyncTable.sync_type` 字段加** (1A) — R2 拍板过, 业务逻辑清晰
2. ✅ **`DdlSyncPair.source_db_size_gb` 字段不加** (2B) — 实时算, 不存冗余
3. ✅ **`DdlSyncHistory.transformed_ddl_text` 字段加** (3A) — 审计完整记录, target_workflow 可删
4. ✅ **`DdlSyncPair.enabled=False` 软删时, 已有 DdlSyncTable + DdlSyncHistory 保留** (4A) — 软删不影响历史数据

落地后字段定义 (3 张表 + 22 个字段):

**DdlSyncPair (9 字段 + 1 关联)**:
- name / source_instance / source_db / target_instance / target_db
- sync_mode (default blacklist) / enabled
- pending_tables (JSONField) / filter_rule (JSONField) (R3 加)
- created_by / created_at / updated_at

**DdlSyncTable (5 字段 + 1 关联)**:
- pair (FK) / table_name
- sync_type (whitelist/blacklist, R2 加)
- transform_rule (JSONField) / created_at

**DdlSyncHistory (7 字段 + 3 关联)**:
- pair (FK) / source_workflow (FK PROTECT) / target_workflow (FK SET_NULL)
- table_name / ddl_text / transformed_ddl_text (D2 拍板 3A 加)
- sync_status (5 选 1) / error_message
- created_at / finished_at
