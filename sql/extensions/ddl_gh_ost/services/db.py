"""
gh-ost 预检查数据库辅助：连目标实例（短连接，复用 PyMySQL）。

为什么不直接用 Django connection：那是 Archery 元库连接，
预检查要查的是用户 SQL 涉及的业务实例，必须另开连接。

兼容 134 dev（PyMySQL 0.9.3）/ 110 prod（mysql-connector-python）。
PyMySQL 是两者都装了的库，所以选它。
"""

import logging
from contextlib import contextmanager
from typing import Optional, Tuple

import pymysql
from pymysql.cursors import DictCursor

logger = logging.getLogger("default")


class DbConnectError(Exception):
    """数据库连接失败。"""


def _connect_instance(instance, database: Optional[str] = None):
    """连目标 MySQL 实例（短连接，调用方负责关闭）。"""
    user, password = instance.get_username_password()
    return pymysql.connect(
        host=instance.host,
        port=instance.port,
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
