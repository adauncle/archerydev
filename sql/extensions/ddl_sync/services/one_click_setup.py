"""DDL 跨库同步 R2 一键配事务

## CUSTOM-MODIFIED: v0.5.0-alpha R2 一键配 one_click_setup @ 2026-09-01 @ mavis
设计参考: docs/designs/2026-09-01_ddl-sync-implementation-design.md §1.2
"""

import logging
import time

from django.db import transaction

from ..models import DdlSyncPair, DdlSyncTable

logger = logging.getLogger("default")


class OneClickSetupError(Exception):
    """一键配事务失败"""
    pass


def one_click_setup(
    pair: DdlSyncPair,
    accept_whitelist: list,
    accept_blacklist: list,
) -> dict:
    """
    R2 一键配 - 事务内 DELETE + bulk_create
    性能预算 1589 张表 bulk_create < 15s (W1-D3 §4 性能预算)

    :param pair: 库对
    :param accept_whitelist: DBA 勾选的白名单表 (业务库 ∩ 历史库)
    :param accept_blacklist: DBA 勾选的黑名单表 (业务库 - 历史库)
    :return: {
        "whitelist_count": int,
        "blacklist_count": int,
        "duration_ms": int,
    }
    :raise: OneClickSetupError (事务失败回滚)
    """
    start_ts = time.time()

    try:
        with transaction.atomic():
            # 1. DELETE 现有 DdlSyncTable (覆盖模式, D8 阶段 2 modal UX 提示 "覆盖现有配置")
            deleted_count, _ = DdlSyncTable.objects.filter(pair=pair).delete()
            logger.info(f"one_click_setup pair={pair.id} DELETE {deleted_count} existing tables")

            # 2. bulk_create 白名单
            whitelist_objs = [
                DdlSyncTable(pair=pair, table_name=t, sync_type="whitelist")
                for t in accept_whitelist
            ]
            if whitelist_objs:
                DdlSyncTable.objects.bulk_create(whitelist_objs, batch_size=500)

            # 3. bulk_create 黑名单
            blacklist_objs = [
                DdlSyncTable(pair=pair, table_name=t, sync_type="blacklist")
                for t in accept_blacklist
            ]
            if blacklist_objs:
                DdlSyncTable.objects.bulk_create(blacklist_objs, batch_size=500)

        duration_ms = int((time.time() - start_ts) * 1000)

        logger.info(
            f"one_click_setup pair={pair.id} DONE: "
            f"whitelist={len(whitelist_objs)} blacklist={len(blacklist_objs)} "
            f"duration={duration_ms}ms"
        )

        return {
            "whitelist_count": len(whitelist_objs),
            "blacklist_count": len(blacklist_objs),
            "duration_ms": duration_ms,
        }
    except Exception as e:
        logger.exception(f"one_click_setup pair={pair.id} 失败, 事务回滚")
        raise OneClickSetupError(f"一键配失败, 事务已回滚: {e}")
