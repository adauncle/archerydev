"""DDL 跨库同步 单张加同步表 (R1 兜底)

## CUSTOM-MODIFIED: v0.5.0-alpha 单张加同步表 @ 2026-09-01 @ mavis
设计参考: docs/designs/2026-09-01_ddl-sync-implementation-design.md §1.2
"""

import logging

from django.db import IntegrityError, transaction

from ..models import DdlSyncPair, DdlSyncTable

logger = logging.getLogger("default")


class TableServiceError(Exception):
    """单张加同步表失败"""
    pass


def add_sync_table(
    pair: DdlSyncPair,
    table_name: str,
    sync_type: str = "whitelist",
    transform_rule: dict = None,
) -> DdlSyncTable:
    """
    单张加同步表 (兜底场景, 实际 99% 用 R2 一键配)

    :param pair: 库对
    :param table_name: 表名
    :param sync_type: "whitelist" / "blacklist"
    :param transform_rule: 字段级调整规则 (Phase 3 用, 默认空)
    :return: 创建的 DdlSyncTable 对象
    :raise: TableServiceError (已存在 / 同步类型错)
    """
    if sync_type not in ("whitelist", "blacklist"):
        raise TableServiceError(f"sync_type 必须是 whitelist 或 blacklist, 当前: {sync_type}")
    if not table_name or not table_name.strip():
        raise TableServiceError("table_name 不能为空")

    table_name = table_name.strip()

    try:
        with transaction.atomic():
            obj = DdlSyncTable.objects.create(
                pair=pair,
                table_name=table_name,
                sync_type=sync_type,
                transform_rule=transform_rule or {},
            )
        logger.info(f"add_sync_table pair={pair.id} table={table_name} sync_type={sync_type} OK")
        return obj
    except IntegrityError as e:
        # unique_together (pair, table_name, sync_type) 冲突
        logger.warning(f"add_sync_table pair={pair.id} table={table_name} 已存在: {e}")
        raise TableServiceError(f"同步表 '{table_name}' (sync_type={sync_type}) 已存在")


def delete_sync_table(table_id: int) -> bool:
    """
    单张删同步表 (DBA 操作)

    :param table_id: DdlSyncTable id
    :return: True 删除成功, False 找不到
    """
    deleted_count, _ = DdlSyncTable.objects.filter(id=table_id).delete()
    return deleted_count > 0
