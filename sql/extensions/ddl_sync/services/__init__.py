"""DDL 跨库同步 services —— 核心业务逻辑

## CUSTOM-MODIFIED: v0.5.0-alpha DDL 跨库同步 services @ 2026-09-01 @ mavis
设计参考: docs/designs/2026-09-01_ddl-sync-implementation-design.md §1.2

4 个核心 service:
- compute_diff: R2 一键配差集计算 (扫源库 + 目标库, 算 3 集合)
- one_click_setup: R2 一键配事务 (delete + bulk_create)
- bulk_import: R1 批量导入事务 (delete + bulk_create)
- table_service: 单张加 + 单张删同步表
"""
