"""DDL 跨库同步 - W2 实施 D6 数据模型

设计参考: docs/designs/2026-09-01_ddl-sync-data-model.md

3 张表 (跟 v0.4.0 ext_ddl_ghost_task 命名空间对齐):
- ext_ddl_sync_pair (库对配置)
- ext_ddl_sync_table (同步表清单)
- ext_ddl_sync_history (同步历史审计)

3 个核心功能 (跟 W1-D3 §3-§5):
- R1 批量导入 (DdlSyncTable 增删)
- R2 一键配 (DdlSyncPair + DdlSyncTable bulk_create)
- R3 走当前配置 (DdlSyncHistory 自动记录 + 镜像工单)
"""

default_app_config = "sql.extensions.ddl_sync.apps.DdlSyncConfig"
