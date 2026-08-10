"""审批策略路由引擎。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §7

核心算法：``match_policy``

    1. 从工单提取三个特征：SQL 类型集合、影响行数、涉及表集合。
    2. 按 ``priority`` 倒序遍历启用的 ``ApprovalPolicy``。
    3. 三维 AND 匹配：SQL 类型 ∩ 业务表 ∩ 影响行数。
    4. 第一条命中即返回。
    5. 全部不命中 -> ``None``（调用方走默认 flow）。
"""

from typing import Iterable, Optional, Sequence

from ..models import ApprovalPolicy, CoreBusinessTable
from .sql_type_detect import extract_affected_rows, extract_affected_tables, extract_sql_types


def match_policy(
    workflow,
    affected_tables: Optional[Sequence[dict]] = None,
) -> Optional[ApprovalPolicy]:
    """根据工单特征匹配一条 ``ApprovalPolicy``。

    Args:
        workflow: ``sql.models.SqlWorkflow`` 实例。
        affected_tables: 可选，影响表列表。格式 ``[{"db": ..., "table": ...}, ...]``。
            传 ``None`` 时由本函数内部自动从 ``workflow.sqlworkflowcontent.sql_content``
            调用上游 ``sql.utils.extract_tables.extract_tables`` 解析。

    Returns:
        命中的 ``ApprovalPolicy``；未命中返回 ``None``。
    """
    ## CUSTOM-MODIFIED: 历史工单没 SqlWorkflowContent 时兜底返回空串。@ 2026-08-10 @ mavis
    _content = getattr(workflow, "sqlworkflowcontent", None)
    sql_content = (_content.sql_content if _content else "") or ""
    sql_types = extract_sql_types(sql_content)
    if affected_tables is None:
        affected_tables = extract_affected_tables(workflow)
    affected_rows = extract_affected_rows(workflow, mode="total")

    policies: Iterable[ApprovalPolicy] = (
        ApprovalPolicy.objects.filter(is_enabled=True)
        .select_related("flow")
        .prefetch_related("sql_types")
        .order_by("-priority")
    )

    for policy in policies:
        if not _match_sql_types(policy, sql_types):
            continue
        if policy.require_core_table and not _has_core_table(affected_tables, policy.table_levels):
            continue
        if not _match_affected_rows(policy, affected_rows):
            continue
        return policy
    return None


# ============================== 维度判定 ==============================


def _match_sql_types(policy: ApprovalPolicy, sql_types: set) -> bool:
    """维度 1：SQL 类型集合。

    策略为空集合时永远不命中（防御性）。
    """
    policy_types: set = set(policy.sql_types.values_list("code", flat=True))
    if not policy_types:
        return False
    if policy.sql_type_match_mode == "all":
        return policy_types.issubset(sql_types)
    # default: any
    return bool(policy_types & sql_types)


def _has_core_table(affected_tables: Sequence[dict], levels: str) -> bool:
    """维度 2：业务表清单中存在受影响的表。

    ``levels`` 形如 ``"L1,L2"``；空表示任意等级。
    """
    if not affected_tables:
        return False
    db_names = {t["db"] for t in affected_tables if t.get("db")}
    table_names = {t["table"] for t in affected_tables if t.get("table")}
    if not db_names or not table_names:
        return False
    qs = CoreBusinessTable.objects.filter(
        db_name__in=db_names,
        table_name__in=table_names,
        is_active=True,
    )
    if levels:
        qs = qs.filter(level__in=[lv.strip() for lv in levels.split(",") if lv.strip()])
    return qs.exists()


def _match_affected_rows(policy: ApprovalPolicy, rows: int) -> bool:
    """维度 3：影响行数区间。

    同时为 ``None`` 时不参与判定（总通过）。
    """
    min_r = policy.min_affected_rows
    max_r = policy.max_affected_rows
    if min_r is None and max_r is None:
        return True
    if min_r is not None and rows < min_r:
        return False
    if max_r is not None and rows > max_r:
        return False
    return True
