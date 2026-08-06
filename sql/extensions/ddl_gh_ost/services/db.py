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
        2. ``instance.get_username_password()``
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
    return user, password, (instance.host, instance.port)


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

