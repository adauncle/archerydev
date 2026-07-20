"""SQL 特征提取。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §7.3

三个公开函数：

* ``extract_sql_types(sql_content)``            -> ``set[str]``
* ``extract_affected_rows(workflow, mode)``      -> ``int``
* ``extract_affected_tables(workflow)``          -> ``list[dict]``

实现要点：
    * ``SqlTypeRegistry`` 的 pattern 编译结果做模块级缓存，命中失效由
      ``reset_registry_cache()`` 主动触发（admin 修改后调用）。
    * ``extract_affected_tables`` 复用上游 ``sql.utils.extract_tables``，
      自行格式化为 ``[{"db": ..., "table": ...}, ...]``。
"""

import json
import re
from threading import RLock
from typing import Dict, List, Optional, Set

import sqlparse

# 注意：``..models.SqlTypeRegistry`` 在函数内部 lazy import，
# 避免在 Django 配置未就绪时模块加载失败。


# 模块级缓存（线程安全）
_registry_cache: Optional[Dict[str, "re.Pattern[str]"]] = None
_registry_lock = RLock()


def _get_registry() -> Dict[str, "re.Pattern[str]"]:
    """懒加载并缓存 ``SqlTypeRegistry.pattern`` 编译结果。"""
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache
    with _registry_lock:
        if _registry_cache is not None:  # double-check
            return _registry_cache
        # lazy import 避免循环依赖 + settings 未就绪时启动失败
        from ..models import SqlTypeRegistry
        _registry_cache = {
            r.code: re.compile(r.pattern, re.IGNORECASE)
            for r in SqlTypeRegistry.objects.filter(is_active=True)
        }
        return _registry_cache


def reset_registry_cache() -> None:
    """清空 ``SqlTypeRegistry`` 缓存。

    在 admin 修改注册表后由调用方显式触发（信号 / 视图）。
    """
    global _registry_cache
    with _registry_lock:
        _registry_cache = None


# ============================== 公开 API ==============================


def extract_sql_types(sql_content: str) -> Set[str]:
    """从 SQL 文本中提取类型编码集合。

    解析规则：
        * ``sqlparse.split`` 按 ``;`` 切分（保留空字符串）。
        * 跳过空语句和纯注释语句。
        * 同一语句命中多个 pattern 时取第一个（"break" 保证单语句单类型）。
    """
    types: Set[str] = set()
    if not sql_content:
        return types
    registry = _get_registry()

    for stmt in sqlparse.split(sql_content):
        stmt = stmt.strip()
        if not stmt or stmt.startswith("--"):
            continue
        for code, pattern in registry.items():
            if pattern.search(stmt):
                types.add(code)
                break
    return types


def extract_affected_rows(workflow, mode: str = "total") -> int:
    """从 ``workflow.sqlworkflowcontent.review_content`` 汇总影响行数。

    ``mode``:
        * ``total`` -> 所有语句行数之和
        * ``max``   -> 单条语句最大行数

    ``review_content`` 是 JSON 字符串，元素形如 ``{"affected_rows": 0, ...}``。
    """
    review_content = getattr(
        getattr(workflow, "sqlworkflowcontent", None), "review_content", None
    ) or "[]"
    try:
        rows_data = json.loads(review_content)
    except (ValueError, TypeError):
        return 0
    if not isinstance(rows_data, list):
        return 0

    rows: List[int] = []
    for r in rows_data:
        if not isinstance(r, dict):
            continue
        try:
            rows.append(int(r.get("affected_rows", 0) or 0))
        except (ValueError, TypeError):
            rows.append(0)

    if not rows:
        return 0
    if mode == "max":
        return max(rows)
    return sum(rows)  # default: total


def extract_affected_tables(workflow) -> List[dict]:
    """从 SQL 文本中提取 ``[{"db": ..., "table": ...}, ...]``。

    实现：复用上游 ``sql.utils.extract_tables.extract_tables``。
    ``db`` 默认取 ``workflow.db_name``。
    """
    content_obj = getattr(workflow, "sqlworkflowcontent", None)
    sql_content = getattr(content_obj, "sql_content", "") or ""
    if not sql_content:
        return []

    # 延迟 import，避免 settings 未就绪时启动失败
    from sql.utils.extract_tables import extract_tables

    db_default = getattr(workflow, "db_name", "") or ""
    try:
        identifiers = extract_tables(sql_content) or []
    except Exception:  # noqa: BLE001
        return []

    result: List[dict] = []
    for ident in identifiers:
        # 上游 extract_tables 返回 ``TableReference`` namedtuple：
        #   ``TableReference(schema, name, alias, is_function)``
        # 也兼容 ``[schema, table]`` / ``[name]`` 两种旧返回。
        if hasattr(ident, "schema") and hasattr(ident, "name"):
            schema = getattr(ident, "schema", "") or ""
            name = getattr(ident, "name", "") or ""
            db_name, table_name = schema, name
        elif isinstance(ident, (list, tuple)) and len(ident) >= 2 and ident[0] and ident[1]:
            db_name, table_name = str(ident[0]), str(ident[1])
        elif ident:
            db_name, table_name = db_default, str(ident[0] if isinstance(ident, (list, tuple)) else ident)
        else:
            continue
        if not table_name:
            continue
        if not db_name:
            db_name = db_default
        result.append({"db": db_name, "table": table_name})
    return result
