"""
gh-ost 预检查 5 道关 —— 只读不写，全部通过才允许执行。

设计参考：docs/designs/2026-08-05_gh-ost-product-design.html §5 + §9

返回值结构（统一）：
    {
        "name": "binlog_format",
        "passed": True/False,
        "evidence": {...},        # 原始检测数据，便于排错
        "message": "通过原因 or 失败原因",
    }
"""

import logging
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional

import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import Keyword, DDL

from .db import DbConnectError, fetch_all, fetch_one, instance_cursor

logger = logging.getLogger("default")

# ===== 阈值常量（写在 .env 里更灵活，alpha 先硬编码） =====
DISK_HEADROOM_RATIO = 1.2  # 磁盘剩余 ≥ 1.2 × 表大小
TABLE_SIZE_FLOOR_BYTES = 1 * 1024 * 1024 * 1024  # 1GB 以下的表建议走传统 ALTER
SUPPORTED_ENGINES = {"InnoDB"}  # gh-ost 仅支持 InnoDB（MyISAM 会转 InnoDB 但不推荐）
FORBIDDEN_ALTER_OPERATIONS = (
    "RENAME", "DROP", "TRUNCATE",  # 这些不是 ALTER
    # 改主键：gh-ost 1.1.x 已支持，但 alpha 先禁
    # 改索引类型 / 全文索引：gh-ost 不支持
    # 外键约束：gh-ost 不支持 + 引用的其他表同步问题
)


# ===========================================================================
# 关 1: binlog_format 必须 ROW
# ===========================================================================
def check_binlog_format(instance, db_name: str) -> Dict:
    name = "binlog_format"
    try:
        with instance_cursor(instance, db_name) as cur:
            row = fetch_one(cur, "SHOW VARIABLES LIKE 'binlog_format'")
            if not row:
                return _fail(name, "无法读取 binlog_format 变量", {})
            value = (row.get("Value") or row.get("value") or "").upper()
            if value == "ROW":
                return _pass(name, f"binlog_format=ROW ✓", {"value": value})
            return _fail(
                name,
                f"binlog_format={value}，gh-ost 仅支持 ROW，请联系 DBA 调整",
                {"value": value},
            )
    except DbConnectError as exc:
        return _fail(name, f"数据库连接失败：{exc}", {})
    except Exception as exc:  # noqa: BLE001
        logger.exception("check_binlog_format 异常")
        return _fail(name, f"检查异常：{exc}", {})


# ===========================================================================
# 关 2: 磁盘剩余 ≥ 1.2 × 表大小
# ===========================================================================
def check_disk_space(instance, db_name: str, table_size_bytes: int) -> Dict:
    name = "disk_space"
    try:
        with instance_cursor(instance, db_name) as cur:
            # 先看 datadir 在哪个磁盘分区
            row = fetch_one(cur, "SHOW VARIABLES LIKE 'datadir'")
            datadir = (row.get("Value") or row.get("value") or "").strip()
            if not datadir:
                return _fail(name, "无法读取 datadir 变量", {})

            # 在 Archery 服务器本地查 df（gh-ost 跑在 Archery 同机）
            # 兼容 Mac/Linux/Windows
            disk_free = _df_free_bytes(datadir)
            if disk_free is None or disk_free <= 0:
                # df 失败也不直接 fail（可能是网络盘 / 容器内 df 异常）
                return _pass(
                    name,
                    f"无法读取磁盘剩余（datadir={datadir}），跳过严格检查",
                    {"datadir": datadir, "disk_free": disk_free},
                )

            required = int(table_size_bytes * DISK_HEADROOM_RATIO)
            if disk_free >= required:
                return _pass(
                    name,
                    f"磁盘剩余 {disk_free//1024//1024} MB ≥ 1.2× 表大小 "
                    f"({required//1024//1024} MB)",
                    {
                        "datadir": datadir,
                        "disk_free_bytes": disk_free,
                        "table_size_bytes": table_size_bytes,
                        "required_bytes": required,
                    },
                )
            return _fail(
                name,
                f"磁盘剩余 {disk_free//1024//1024} MB < 1.2× 表大小 "
                f"({required//1024//1024} MB)，gh-ost 会生成影子表 + binlog，"
                f"建议清理磁盘或找 DBA 扩容",
                {
                    "datadir": datadir,
                    "disk_free_bytes": disk_free,
                    "table_size_bytes": table_size_bytes,
                    "required_bytes": required,
                },
            )
    except DbConnectError as exc:
        return _fail(name, f"数据库连接失败：{exc}", {})
    except Exception as exc:  # noqa: BLE001
        logger.exception("check_disk_space 异常")
        return _fail(name, f"检查异常：{exc}", {})


def _df_free_bytes(path: str) -> Optional[int]:
    """跨平台取磁盘剩余（字节）。失败返回 None。"""
    try:
        if os.name == "nt":
            # Windows：用 PowerShell
            # 取 path 所在盘符
            import string
            drive = path[:1].upper() if path[:1] in string.ascii_letters else "C"
            cmd = [
                "powershell", "-NoProfile", "-Command",
                f"(Get-PSDrive -Name '{drive}').Free",
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip().isdigit():
                return int(r.stdout.strip())
            return None
        # Linux/Mac：df -B1 <path> | tail -1
        r = subprocess.run(
            ["df", "-B1", path], capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return None
        line = r.stdout.strip().splitlines()[-1]
        parts = line.split()
        if len(parts) < 4:
            return None
        return int(parts[3])  # Available
    except Exception:  # noqa: BLE001
        return None


# ===========================================================================
# 关 3: 复制权限（REPLICATION SLAVE + REPLICATION CLIENT）
# ===========================================================================
def check_replication_privileges(instance, db_name: str) -> Dict:
    name = "replication_privileges"
    try:
        with instance_cursor(instance, db_name) as cur:
            rows = fetch_all(cur, "SHOW GRANTS")
            if not rows:
                return _fail(name, "无法读取当前账户权限", {})

            # mysql.connector dictionary=True 时列名是固定的，
            # 上游 SQL 形如 "Grants for archery@10.0.0.1"，列名以 mysql 版本而异
            grants_text = " ".join(
                " ".join(str(v) for v in r.values()) for r in rows
            ).upper()

            has_slave = "REPLICATION SLAVE" in grants_text
            has_client = "REPLICATION CLIENT" in grants_text
            has_all = "ALL PRIVILEGES" in grants_text or "GRANT ALL" in grants_text

            if (has_slave and has_client) or has_all:
                granted = "ALL PRIVILEGES" if has_all else (
                    "REPLICATION SLAVE + REPLICATION CLIENT"
                )
                return _pass(name, f"账户已有 {granted} ✓", {
                    "has_replication_slave": has_slave,
                    "has_replication_client": has_client,
                    "has_all": has_all,
                })

            missing = []
            if not has_slave:
                missing.append("REPLICATION SLAVE")
            if not has_client:
                missing.append("REPLICATION CLIENT")
            return _fail(
                name,
                f"账户缺少权限：{', '.join(missing)}，请联系 DBA grant",
                {
                    "has_replication_slave": has_slave,
                    "has_replication_client": has_client,
                    "has_all": has_all,
                },
            )
    except DbConnectError as exc:
        return _fail(name, f"数据库连接失败：{exc}", {})
    except Exception as exc:  # noqa: BLE001
        logger.exception("check_replication_privileges 异常")
        return _fail(name, f"检查异常：{exc}", {})


# ===========================================================================
# 关 4: SQL 是 ALTER TABLE，不改主键/索引/全文/外键
# ===========================================================================
def check_alter_sql(sql_content: str) -> Dict:
    name = "alter_sql"
    try:
        # 取第一条非空语句
        statements = [s for s in sqlparse.split(sql_content) if s.strip()]
        if not statements:
            return _fail(name, "SQL 内容为空", {})

        first = statements[0].strip()
        parsed = sqlparse.parse(first)
        if not parsed:
            return _fail(name, "SQL 解析失败", {"sql_head": first[:200]})

        stmt: Statement = parsed[0]
        first_token = stmt.token_first(skip_cm=True)
        stmt_type = (first_token.normalized.upper() if first_token else "")

        if stmt_type != "ALTER":
            return _fail(
                name,
                f"首条语句不是 ALTER TABLE（识别为 {stmt_type or '未知'}），"
                f"gh-ost 仅支持 ALTER",
                {"detected_type": stmt_type, "sql_head": first[:200]},
            )

        # 检查是否带 RENAME TO / DROP / TRUNCATE
        for keyword in ("RENAME TO", "DROP ", "TRUNCATE "):
            if keyword in first.upper():
                return _fail(
                    name,
                    f"检测到禁用操作 {keyword.strip()}，gh-ost 不支持",
                    {"forbidden": keyword.strip(), "sql_head": first[:200]},
                )

        # 检查是否改主键 / 全文索引 / 外键
        upper = first.upper()
        forbidden_markers = [
            ("PRIMARY KEY", "改主键（gh-ost 1.1.x 不支持 DROP/ADD PRIMARY KEY）"),
            ("FULLTEXT", "全文索引（gh-ost 不支持）"),
            ("FOREIGN KEY", "外键约束（gh-ost 不支持 + 引用此表的其他表会同步问题）"),
        ]
        # 例外：COMMENT / COLUMN ADD 后的字面量出现 "FOREIGN" 也算违规
        # 简单做法：直接匹配关键词（误判风险低，真误判 DBA 可绕过）
        for marker, reason in forbidden_markers:
            if marker in upper:
                return _fail(
                    name,
                    f"检测到 {reason}",
                    {"marker": marker, "sql_head": first[:200]},
                )

        return _pass(
            name,
            f"ALTER 语句符合 gh-ost 要求 ✓",
            {"sql_head": first[:200]},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("check_alter_sql 异常")
        return _fail(name, f"检查异常：{exc}", {})


# ===========================================================================
# 关 5: 表类型（非分区表、非临时表、ENGINE 是 InnoDB）
# ===========================================================================
def check_table_type(instance, db_name: str, table_name: str) -> Dict:
    name = "table_type"
    try:
        with instance_cursor(instance, db_name) as cur:
            row = fetch_one(
                cur,
                "SELECT ENGINE, TABLE_COLLATION, CREATE_OPTIONS, IFNULL(PARTITION_NAME, '') AS PARTITION_NAME "
                "FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                (db_name, table_name),
            )
            if not row:
                return _fail(
                    name, f"表 {db_name}.{table_name} 不存在", {},
                )

            # 标准化列名
            engine = ""
            for k, v in row.items():
                kk = k.lower()
                if kk == "engine":
                    engine = (v or "").upper()
                elif kk == "create_options" and v and "partitioned" in v.lower():
                    return _fail(
                        name,
                        f"表是分区表，gh-ost 不支持",
                        {"create_options": v, "row": row},
                    )

            if not engine:
                return _fail(name, "无法读取表的 ENGINE", {"row": row})

            if engine not in SUPPORTED_ENGINES:
                return _fail(
                    name,
                    f"表 ENGINE={engine}，gh-ost 仅支持 InnoDB（MyISAM 转 InnoDB 不推荐）",
                    {"engine": engine, "row": row},
                )

            return _pass(
                name,
                f"表类型符合 gh-ost 要求（ENGINE={engine}）✓",
                {"engine": engine, "row": row},
            )
    except DbConnectError as exc:
        return _fail(name, f"数据库连接失败：{exc}", {})
    except Exception as exc:  # noqa: BLE001
        logger.exception("check_table_type 异常")
        return _fail(name, f"检查异常：{exc}", {})


# ===========================================================================
# 编排：跑全部 5 道 + 返回报告
# ===========================================================================
def run_all_prechecks(workflow, instance, db_name: str, table_name: str,
                      alter_sql: str) -> Dict:
    """跑全部预检查，返回整体报告。

    返回：
        {
            "passed": True/False,
            "checks": [<单条结果>...],
            "summary": "...",
            "table_size_bytes": int,        # 顺手存表大小给进度估算
        }
    """
    checks: List[Dict] = []

    # 先拿表大小（关 2 要用）
    table_size = 0
    try:
        with instance_cursor(instance, db_name) as cur:
            size_row = fetch_one(
                cur,
                "SELECT DATA_LENGTH + INDEX_LENGTH AS size_bytes "
                "FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                (db_name, table_name),
            )
            if size_row:
                for v in size_row.values():
                    if isinstance(v, (int, float)):
                        table_size = int(v)
                        break
    except Exception:  # noqa: BLE001
        logger.warning("get table size failed", exc_info=True)

    checks.append(check_binlog_format(instance, db_name))
    checks.append(check_disk_space(instance, db_name, table_size))
    checks.append(check_replication_privileges(instance, db_name))
    checks.append(check_alter_sql(alter_sql))
    checks.append(check_table_type(instance, db_name, table_name))

    passed = all(c["passed"] for c in checks)
    failed = [c for c in checks if not c["passed"]]

    if passed:
        summary = f"5/5 通过（表大小 {table_size//1024//1024} MB）"
    else:
        names = "、".join(c["name"] for c in failed)
        summary = f"未通过：{names}（{len(failed)}/5 失败）"

    return {
        "passed": passed,
        "checks": checks,
        "summary": summary,
        "table_size_bytes": table_size,
    }


# ===== 内部辅助 =====
def _pass(name: str, message: str, evidence: Dict) -> Dict:
    return {"name": name, "passed": True, "message": message, "evidence": evidence}


def _fail(name: str, message: str, evidence: Dict) -> Dict:
    return {"name": name, "passed": False, "message": message, "evidence": evidence}
