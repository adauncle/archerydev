"""DDL 跨库同步 R2 一键配差集计算

## CUSTOM-MODIFIED: v0.5.0-alpha R2 一键配 compute_diff @ 2026-09-01 @ mavis
设计参考: docs/designs/2026-09-01_ddl-sync-implementation-design.md §1.2
"""

import logging
import pymysql
from typing import List

from ..models import DdlSyncPair

logger = logging.getLogger("default")


class ComputeDiffError(Exception):
    """差集计算失败"""
    pass


def _fetch_tables(instance, db_name: str) -> List[str]:
    """
    一次 SQL 拿所有表名, 性能预算 1589 张表 < 5s
    复用 8/12 实战 (information_schema.TABLES 一次 fetchall)
    """
    creds = instance.get_username_password()
    conn = pymysql.connect(
        host=instance.host,
        port=instance.port,
        user=creds[0],
        password=creds[1],
        db=db_name,
        charset="utf8mb4",
        connect_timeout=5,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT TABLE_NAME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'",
                (db_name,),
            )
            tables = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
    return tables


def compute_diff(pair: DdlSyncPair) -> dict:
    """
    R2 一键配差集计算 - 扫业务库 + 历史库, 算 3 集合
    :return: {
        "whitelist": [str],  # 业务库 ∩ 历史库, 建议白名单 (要同步)
        "blacklist": [str],  # 业务库 - 历史库, 建议黑名单 (不同步)
        "orphans": [str],    # 历史库 - 业务库, 提示 DBA
    }
    :raise: ComputeDiffError (库连接失败 / 权限不足 / 库为空)
    """
    try:
        # 1. 扫源库 (业务库) + 目标库 (历史库)
        source_tables = _fetch_tables(pair.source_instance, pair.source_db)
        target_tables = _fetch_tables(pair.target_instance, pair.target_db)
    except Exception as e:
        raise ComputeDiffError(f"扫源/目标库失败: {e}")

    # 2. 算 3 集合 (Python set 运算, O(N))
    source_set = set(source_tables)
    target_set = set(target_tables)

    whitelist = sorted(source_set & target_set)  # 业务库 ∩ 历史库
    blacklist = sorted(source_set - target_set)  # 业务库 - 历史库
    orphans = sorted(target_set - source_set)    # 历史库 - 业务库

    logger.info(
        f"compute_diff pair={pair.id} ({pair.name}): "
        f"source={len(source_tables)} target={len(target_tables)} "
        f"whitelist={len(whitelist)} blacklist={len(blacklist)} orphans={len(orphans)}"
    )

    return {
        "whitelist": whitelist,
        "blacklist": blacklist,
        "orphans": orphans,
    }
