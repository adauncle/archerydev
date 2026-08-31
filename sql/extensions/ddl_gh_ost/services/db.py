"""
gh-ost 预检查数据库辅助：连目标实例（短连接，复用 PyMySQL）。

为什么不直接用 Django connection：那是 Archery 元库连接，
预检查要查的是用户 SQL 涉及的业务实例，必须另开连接。

兼容 134 dev（PyMySQL 0.9.3）/ 110 prod（mysql-connector-python）。
PyMySQL 是两者都装了的库，所以选它。

历史凭据 fallback：
    134 dev 上 archery instance 的 user/password 是历史 mirage 加密密文，
    当前 SECRET_KEY 解不出来 → ``instance.get_username_password()`` 返回密文，
    MySQL 报 1045。开发者设置 ``CUSTOM_GH_OST_PRECHECK_*`` 后会优先用这套凭据直连，
    跳过 instance 解密（仅 dev/演练用，prod 不应启用）。

## CUSTOM-MODIFIED: 探测 MySQL 真实 listen 端口 (8/31 @ mavis)
8/31 17:53 业务 RD 冉升成 110 prod 提 gh-ost 工单 #7 (instance 5 prod core for etc 变更
172.20.2.9:6446 cluster1), 报 "unexpected database port reported: 3306" 死掉。
根因: instance 配置 host:port 跟 MySQL 实际 listen 端口不一致 (6446 是 SSH tunnel /
端口转发, MySQL 真 listen 3306). gh-ost 1.1.10 严格检查 @@port == connection port,
不一致 FATAL. 134 dev instance 全是 3306 端口演练没暴露, 110 prod 6 个 6446 instance
中 3 个 (5/26/31 cluster1/bg-replica1/logisticsdbm) 配错.

修法: gh-ost 启动前用 instance 配置的 host:port 查 @@port, 不一致就用真实端口
启动 gh-ost (host 保留 archery 配置的, port 改). archery instance 配置不动
(172.20.2.9:6446 保留 = cluster1 写入节点约定值).
"""

import logging
from contextlib import contextmanager
from typing import Optional, Tuple

import pymysql
from django.conf import settings
from pymysql.cursors import DictCursor

logger = logging.getLogger("default")


class DbConnectError(Exception):
    """数据库连接失败。"""


def _get_creds(instance) -> Tuple[str, str, int]:
    """拿 (user, password, host_port) 凭据。

    优先级：
        1. ``CUSTOM_GH_OST_PRECHECK_HOST`` 显式设置 → 走 .env 兜底
        2. ``instance.get_username_password()`` + 探测真实 MySQL 端口

    ## CUSTOM-MODIFIED: 探测真实端口 (8/31)
    archery instance 配的 port 不一定是 MySQL 真实 listen 端口 (e.g. SSH tunnel/
    端口转发), gh-ost 1.1.10 严格检查 @@port == connection port, 不一致 FATAL.
    修法: 用 instance 配置的 host:port 短连接查 @@port, 不一致就用真实端口
    启动 gh-ost (host 保留 archery 配置的, port 改). 探测失败时 fallback 用
    instance 配置的 port (不破坏现有功能).
    """
    fallback_host = getattr(settings, "CUSTOM_GH_OST_PRECHECK_HOST", "")
    if fallback_host:
        user = getattr(settings, "CUSTOM_GH_OST_PRECHECK_USER", "")
        password = getattr(settings, "CUSTOM_GH_OST_PRECHECK_PASSWORD", "")
        port = int(getattr(settings, "CUSTOM_GH_OST_PRECHECK_PORT", 3306))
        logger.info(
            "gh-ost precheck using fallback creds (host=%s, user=%s) — dev-only hotfix",
            fallback_host, user,
        )
        return user, password, (fallback_host, port)
    user, password = instance.get_username_password()
    host, port = instance.host, instance.port

    # CUSTOM-MODIFIED: 探测 MySQL 真实 listen 端口, 避免 gh-ost port check 报错
    actual_port = _detect_actual_mysql_port(host, port, user, password)
    if actual_port is not None and actual_port != port:
        logger.info(
            "instance %s (host=%s) 配置 port=%d 但 MySQL 实际 listen %d, "
            "改用真实端口启动 gh-ost (host 保留)",
            instance.instance_name, host, port, actual_port,
        )
        port = actual_port
    elif actual_port is None:
        logger.warning(
            "instance %s (host=%s:%d) 探测 MySQL 真实端口失败, "
            "fallback 用 instance 配置 port=%d",
            instance.instance_name, host, port, port,
        )

    return user, password, (host, port)


def _detect_actual_mysql_port(host: str, port: int, user: str, password: str) -> Optional[int]:
    """探测 MySQL 真实 listen 端口（短连接 + SELECT @@port）。

    Returns:
        真实端口 (int) / 探测失败返回 None (fallback 用 instance 配置 port).
    """
    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            connect_timeout=3,
            autocommit=True,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT @@port")
                row = cur.fetchone()
            if row:
                return int(row[0])
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("探测 MySQL 真实端口失败 %s:%d: %s", host, port, exc)
    return None


def _connect_instance(instance, database: Optional[str] = None):
    """连目标 MySQL 实例（短连接，调用方负责关闭）。"""
    user, password, (host, port) = _get_creds(instance)
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database or instance.db_name or None,
        connect_timeout=5,
        autocommit=True,
        charset="utf8mb4",
        cursorclass=DictCursor,
    )


@contextmanager
def instance_cursor(instance, database: Optional[str] = None):
    """目标实例的 cursor 上下文管理器。失败时抛 DbConnectError。"""
    conn = None
    try:
        conn = _connect_instance(instance, database)
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()
    except pymysql.MySQLError as exc:
        logger.warning(
            "gh-ost precheck connect failed: instance=%s err=%s",
            instance.instance_name, exc,
        )
        raise DbConnectError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "gh-ost precheck unexpected: instance=%s err=%s",
            instance.instance_name, exc,
        )
        raise DbConnectError(str(exc)) from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def fetch_one(cur, sql: str, params: Optional[Tuple] = None) -> Optional[dict]:
    cur.execute(sql, params or ())
    row = cur.fetchone()
    return row


def fetch_all(cur, sql: str, params: Optional[Tuple] = None) -> list:
    cur.execute(sql, params or ())
    return list(cur.fetchall())

