"""DDL 跨库同步 R1 批量导入事务

## CUSTOM-MODIFIED: v0.5.0-alpha R1 批量导入 bulk_import @ 2026-09-01 @ mavis
设计参考: docs/designs/2026-09-01_ddl-sync-implementation-design.md §1.2
"""

import logging
import time

from django.db import transaction

from ..models import DdlSyncPair, DdlSyncTable

logger = logging.getLogger("default")


class BulkImportError(Exception):
    """批量导入事务失败"""
    pass


def bulk_import_tables(
    pair: DdlSyncPair,
    table_names: list,
    sync_type: str = "whitelist",
) -> dict:
    """
    R1 批量导入 - 事务内 DELETE (已存在) + bulk_create
    性能预算 200 张表 bulk_create < 2s (W1-D3 §4 性能预算)

    :param pair: 库对
    :param table_names: DBA 勾选的表 (1-200 张)
    :param sync_type: "whitelist" / "blacklist"
    :return: {
        "imported_count": int,  # 实际新增
        "skipped_count": int,   # 已存在跳过
        "duration_ms": int,
    }
    :raise: BulkImportError (事务失败回滚)
    """
    if sync_type not in ("whitelist", "blacklist"):
        raise BulkImportError(f"sync_type 必须是 whitelist 或 blacklist, 当前: {sync_type}")
    if not table_names:
        raise BulkImportError("table_names 不能为空")
    if len(table_names) > 200:
        raise BulkImportError(f"批量导入单次最多 200 张, 当前: {len(table_names)} 张")

    start_ts = time.time()

    try:
        with transaction.atomic():
            # 1. 查已存在 (DBA 看到的 "已存在" 提示)
            existing = set(
                DdlSyncTable.objects.filter(
                    pair=pair, table_name__in=table_names, sync_type=sync_type
                ).values_list("table_name", flat=True)
            )
            skipped_count = len(existing)

            # 2. 过滤掉已存在, 只 insert 新的
            new_tables = [t for t in table_names if t not in existing]
            if new_tables:
                bulk_objs = [
                    DdlSyncTable(pair=pair, table_name=t, sync_type=sync_type)
                    for t in new_tables
                ]
                DdlSyncTable.objects.bulk_create(bulk_objs, batch_size=500)

            imported_count = len(new_tables)

        duration_ms = int((time.time() - start_ts) * 1000)

        logger.info(
            f"bulk_import pair={pair.id} sync_type={sync_type} DONE: "
            f"imported={imported_count} skipped={skipped_count} duration={duration_ms}ms"
        )

        return {
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "duration_ms": duration_ms,
        }
    except Exception as e:
        logger.exception(f"bulk_import pair={pair.id} 失败, 事务回滚")
        raise BulkImportError(f"批量导入失败, 事务已回滚: {e}")
