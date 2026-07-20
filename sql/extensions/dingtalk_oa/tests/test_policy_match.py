"""路由引擎测试。

覆盖：
    * ``extract_sql_types``          SQL 类型集合提取
    * ``extract_affected_rows``     影响行数聚合
    * ``extract_affected_tables``   影响表提取
    * ``match_policy``              三维 AND 路由
    * ``_match_sql_types`` / ``_has_core_table`` / ``_match_affected_rows``
"""

import json

import pytest

from sql.extensions.dingtalk_oa.models import (
    ApprovalFlow,
    ApprovalPolicy,
    CoreBusinessTable,
    SqlTypeRegistry,
)
from sql.extensions.dingtalk_oa.services.policy import (
    _has_core_table,
    _match_affected_rows,
    _match_sql_types,
    match_policy,
)
from sql.extensions.dingtalk_oa.services.sql_type_detect import (
    extract_affected_rows,
    extract_affected_tables,
    extract_sql_types,
    reset_registry_cache,
)


# ============================== fixtures ==============================


@pytest.fixture
def reset_sql_type_cache():
    """每个用例前后清空缓存。"""
    reset_registry_cache()
    yield
    reset_registry_cache()


@pytest.fixture
def seed_registry():
    """灌入 5 个 SQL 类型。"""
    SqlTypeRegistry.objects.create(
        code="INSERT_T", category="DML", description="i",
        pattern=r"^\s*INSERT\b", default_severity="low",
    )
    SqlTypeRegistry.objects.create(
        code="UPDATE_T", category="DML", description="u",
        pattern=r"^\s*UPDATE\b", default_severity="medium",
    )
    SqlTypeRegistry.objects.create(
        code="DELETE_T", category="DML", description="d",
        pattern=r"^\s*DELETE\b", default_severity="high", is_critical=True,
    )
    SqlTypeRegistry.objects.create(
        code="DROP_T", category="DDL", description="x",
        pattern=r"^\s*DROP\b", default_severity="high", is_critical=True,
        has_affected_rows=False,
    )
    SqlTypeRegistry.objects.create(
        code="SELECT_T", category="DQL", description="s",
        pattern=r"^\s*SELECT\b", default_severity="low",
        has_affected_rows=False,
    )
    reset_registry_cache()
    return SqlTypeRegistry


# ============================== extract_sql_types ==============================


@pytest.mark.django_db
def test_extract_sql_types_empty(reset_sql_type_cache):
    assert extract_sql_types("") == set()


@pytest.mark.django_db
def test_extract_sql_types_skips_comments(reset_sql_type_cache, seed_registry):
    sql = "-- this is a comment\n-- another"
    assert extract_sql_types(sql) == set()


@pytest.mark.django_db
def test_extract_sql_types_single(reset_sql_type_cache, seed_registry):
    assert extract_sql_types("INSERT INTO t VALUES (1)") == {"INSERT_T"}


@pytest.mark.django_db
def test_extract_sql_types_multi_stmt(reset_sql_type_cache, seed_registry):
    sql = "INSERT INTO t VALUES (1); DELETE FROM t WHERE id=1"
    assert extract_sql_types(sql) == {"INSERT_T", "DELETE_T"}


@pytest.mark.django_db
def test_extract_sql_types_drop_and_insert(reset_sql_type_cache, seed_registry):
    sql = "DROP TABLE t; INSERT INTO t VALUES (1)"
    assert extract_sql_types(sql) == {"INSERT_T", "DROP_T"}


@pytest.mark.django_db
def test_extract_sql_types_case_insensitive(reset_sql_type_cache, seed_registry):
    assert extract_sql_types("insert into t values (1)") == {"INSERT_T"}


@pytest.mark.django_db
def test_extract_sql_types_no_match(reset_sql_type_cache, seed_registry):
    assert extract_sql_types("BEGIN; COMMIT;") == set()


# ============================== extract_affected_rows ==============================


@pytest.mark.django_db
def test_extract_affected_rows_empty(sql_workflow):
    wf, _ = sql_workflow
    wf.sqlworkflowcontent.review_content = "[]"
    assert extract_affected_rows(wf) == 0


@pytest.mark.django_db
def test_extract_affected_rows_total(sql_workflow):
    wf, _ = sql_workflow
    wf.sqlworkflowcontent.review_content = json.dumps([
        {"affected_rows": 10},
        {"affected_rows": 5},
        {"affected_rows": 3},
    ])
    assert extract_affected_rows(wf, mode="total") == 18


@pytest.mark.django_db
def test_extract_affected_rows_max(sql_workflow):
    wf, _ = sql_workflow
    wf.sqlworkflowcontent.review_content = json.dumps([
        {"affected_rows": 10},
        {"affected_rows": 5},
        {"affected_rows": 3},
    ])
    assert extract_affected_rows(wf, mode="max") == 10


@pytest.mark.django_db
def test_extract_affected_rows_invalid_json(sql_workflow):
    wf, _ = sql_workflow
    wf.sqlworkflowcontent.review_content = "not-json"
    assert extract_affected_rows(wf) == 0


@pytest.mark.django_db
def test_extract_affected_rows_mixed_invalid(sql_workflow):
    wf, _ = sql_workflow
    wf.sqlworkflowcontent.review_content = json.dumps([
        {"affected_rows": "abc"},  # 无效
        {"affected_rows": 5},
        "not a dict",                # 类型错
    ])
    assert extract_affected_rows(wf) == 5


# ============================== extract_affected_tables ==============================


@pytest.mark.django_db
def test_extract_affected_tables_empty(sql_workflow):
    wf, _ = sql_workflow
    wf.sqlworkflowcontent.sql_content = ""
    assert extract_affected_tables(wf) == []


@pytest.mark.django_db
def test_extract_affected_tables_simple(sql_workflow):
    wf, _ = sql_workflow
    wf.sqlworkflowcontent.sql_content = "SELECT * FROM hly_accesscard.user WHERE id=1"
    tables = extract_affected_tables(wf)
    assert len(tables) >= 1
    # 至少有一项带 db/table
    assert any(t.get("db") and t.get("table") for t in tables)


# ============================== _match_sql_types ==============================


@pytest.mark.django_db
def test_match_sql_types_any_mode(seed_registry):
    flow = ApprovalFlow.objects.create(
        code="f", name="F", audit_driver="archery", audit_auth_groups="1",
    )
    policy = ApprovalPolicy.objects.create(
        name="p", priority=10, is_enabled=True, flow=flow,
        sql_type_match_mode="any",
    )
    policy.sql_types.set(SqlTypeRegistry.objects.filter(code__in=["INSERT_T", "DROP_T"]))

    assert _match_sql_types(policy, {"INSERT_T"}) is True
    assert _match_sql_types(policy, {"DROP_T"}) is True
    assert _match_sql_types(policy, {"SELECT_T"}) is False


@pytest.mark.django_db
def test_match_sql_types_all_mode(seed_registry):
    flow = ApprovalFlow.objects.create(
        code="f", name="F", audit_driver="archery", audit_auth_groups="1",
    )
    policy = ApprovalPolicy.objects.create(
        name="p", priority=10, is_enabled=True, flow=flow,
        sql_type_match_mode="all",
    )
    policy.sql_types.set(SqlTypeRegistry.objects.filter(code__in=["INSERT_T", "DROP_T"]))

    assert _match_sql_types(policy, {"INSERT_T"}) is False
    assert _match_sql_types(policy, {"INSERT_T", "DROP_T"}) is True


@pytest.mark.django_db
def test_match_sql_types_empty_policy_never_hits(seed_registry):
    flow = ApprovalFlow.objects.create(
        code="f", name="F", audit_driver="archery", audit_auth_groups="1",
    )
    policy = ApprovalPolicy.objects.create(
        name="p", priority=10, is_enabled=True, flow=flow,
    )
    # 没绑 sql_types
    assert _match_sql_types(policy, {"INSERT_T"}) is False


# ============================== _has_core_table ==============================


@pytest.mark.django_db
def test_has_core_table_hit(db_instance):
    CoreBusinessTable.objects.create(
        instance=db_instance, db_name="d1", table_name="t1",
        level="L1", created_by="t",
    )
    assert _has_core_table([{"db": "d1", "table": "t1"}], "") is True


@pytest.mark.django_db
def test_has_core_table_miss(db_instance):
    CoreBusinessTable.objects.create(
        instance=db_instance, db_name="d1", table_name="t1",
        level="L1", created_by="t",
    )
    assert _has_core_table([{"db": "d1", "table": "t2"}], "") is False


@pytest.mark.django_db
def test_has_core_table_level_filter(db_instance):
    CoreBusinessTable.objects.create(
        instance=db_instance, db_name="d1", table_name="t1",
        level="L1", created_by="t",
    )
    assert _has_core_table([{"db": "d1", "table": "t1"}], "L2,L3") is False
    assert _has_core_table([{"db": "d1", "table": "t1"}], "L1,L2") is True


@pytest.mark.django_db
def test_has_core_table_empty_list(db_instance):
    assert _has_core_table([], "") is False


# ============================== _match_affected_rows ==============================


@pytest.mark.django_db
def test_match_affected_rows_no_limit():
    flow = ApprovalFlow.objects.create(
        code="f", name="F", audit_driver="archery", audit_auth_groups="1",
    )
    policy = ApprovalPolicy.objects.create(
        name="p", priority=10, is_enabled=True, flow=flow,
    )
    # 字段都为 None 时，恒通过
    assert _match_affected_rows(policy, 0) is True
    assert _match_affected_rows(policy, 10000) is True


@pytest.mark.django_db
def test_match_affected_rows_min_only():
    flow = ApprovalFlow.objects.create(
        code="f", name="F", audit_driver="archery", audit_auth_groups="1",
    )
    policy = ApprovalPolicy.objects.create(
        name="p", priority=10, is_enabled=True, flow=flow,
        min_affected_rows=10,
    )
    assert _match_affected_rows(policy, 5) is False
    assert _match_affected_rows(policy, 10) is True
    assert _match_affected_rows(policy, 100) is True


@pytest.mark.django_db
def test_match_affected_rows_max_only():
    flow = ApprovalFlow.objects.create(
        code="f", name="F", audit_driver="archery", audit_auth_groups="1",
    )
    policy = ApprovalPolicy.objects.create(
        name="p", priority=10, is_enabled=True, flow=flow,
        max_affected_rows=10,
    )
    assert _match_affected_rows(policy, 5) is True
    assert _match_affected_rows(policy, 10) is True
    assert _match_affected_rows(policy, 11) is False


@pytest.mark.django_db
def test_match_affected_rows_range():
    flow = ApprovalFlow.objects.create(
        code="f", name="F", audit_driver="archery", audit_auth_groups="1",
    )
    policy = ApprovalPolicy.objects.create(
        name="p", priority=10, is_enabled=True, flow=flow,
        min_affected_rows=2, max_affected_rows=10,
    )
    assert _match_affected_rows(policy, 1) is False
    assert _match_affected_rows(policy, 2) is True
    assert _match_affected_rows(policy, 10) is True
    assert _match_affected_rows(policy, 11) is False


# ============================== match_policy 顶层路由 ==============================


@pytest.mark.django_db
def test_match_policy_no_policy_returns_none(sql_workflow, seed_registry, reset_sql_type_cache):
    wf, _ = sql_workflow
    wf.sqlworkflowcontent.sql_content = "INSERT INTO t VALUES (1)"
    wf.sqlworkflowcontent.review_content = json.dumps([{"affected_rows": 5}])
    assert match_policy(workflow=wf) is None


@pytest.mark.django_db
def test_match_policy_priority_order(sql_workflow, seed_registry, reset_sql_type_cache):
    flow_low = ApprovalFlow.objects.create(
        code="low", name="Low", audit_driver="archery", audit_auth_groups="1",
    )
    flow_high = ApprovalFlow.objects.create(
        code="high", name="High", audit_driver="archery", audit_auth_groups="1,2",
    )
    insert_t = SqlTypeRegistry.objects.get(code="INSERT_T")

    ApprovalPolicy.objects.create(
        name="low_priority", priority=1, is_enabled=True, flow=flow_low,
    ).sql_types.set([insert_t])
    ApprovalPolicy.objects.create(
        name="high_priority", priority=99, is_enabled=True, flow=flow_high,
    ).sql_types.set([insert_t])

    wf, _ = sql_workflow
    wf.sqlworkflowcontent.sql_content = "INSERT INTO t VALUES (1)"
    wf.sqlworkflowcontent.review_content = json.dumps([{"affected_rows": 1}])

    policy = match_policy(workflow=wf)
    assert policy is not None
    assert policy.name == "high_priority"
    assert policy.flow.code == "high"


@pytest.mark.django_db
def test_match_policy_disabled_skipped(sql_workflow, seed_registry, reset_sql_type_cache):
    flow = ApprovalFlow.objects.create(
        code="f", name="F", audit_driver="archery", audit_auth_groups="1",
    )
    insert_t = SqlTypeRegistry.objects.get(code="INSERT_T")
    ApprovalPolicy.objects.create(
        name="disabled", priority=99, is_enabled=False, flow=flow,
    ).sql_types.set([insert_t])

    wf, _ = sql_workflow
    wf.sqlworkflowcontent.sql_content = "INSERT INTO t VALUES (1)"
    wf.sqlworkflowcontent.review_content = json.dumps([{"affected_rows": 1}])
    assert match_policy(workflow=wf) is None


@pytest.mark.django_db
def test_match_policy_affected_rows_filter(sql_workflow, seed_registry, reset_sql_type_cache):
    flow = ApprovalFlow.objects.create(
        code="f", name="F", audit_driver="archery", audit_auth_groups="1",
    )
    insert_t = SqlTypeRegistry.objects.get(code="INSERT_T")
    ApprovalPolicy.objects.create(
        name="big_update", priority=10, is_enabled=True, flow=flow,
        min_affected_rows=11,
    ).sql_types.set([insert_t])

    wf, _ = sql_workflow
    wf.sqlworkflowcontent.sql_content = "INSERT INTO t VALUES (1)"
    # 5 行不命中
    wf.sqlworkflowcontent.review_content = json.dumps([{"affected_rows": 5}])
    assert match_policy(workflow=wf) is None

    # 11 行命中
    wf.sqlworkflowcontent.review_content = json.dumps([{"affected_rows": 11}])
    policy = match_policy(workflow=wf)
    assert policy is not None
    assert policy.name == "big_update"


@pytest.mark.django_db
def test_match_policy_require_core_table(db_instance, sql_workflow, seed_registry, reset_sql_type_cache):
    flow = ApprovalFlow.objects.create(
        code="f", name="F", audit_driver="archery", audit_auth_groups="1",
    )
    drop_t = SqlTypeRegistry.objects.get(code="DROP_T")
    ApprovalPolicy.objects.create(
        name="core_drop", priority=10, is_enabled=True, flow=flow,
        require_core_table=True, table_levels="L1,L2",
    ).sql_types.set([drop_t])

    wf, _ = sql_workflow
    wf.sqlworkflowcontent.sql_content = "DROP TABLE t"
    wf.sqlworkflowcontent.review_content = json.dumps([{"affected_rows": 0}])
    # 没有任何核心表 -> 不命中
    assert match_policy(workflow=wf) is None

    # 灌入核心表
    CoreBusinessTable.objects.create(
        instance=db_instance, db_name=wf.db_name, table_name="t",
        level="L1", created_by="t",
    )
    policy = match_policy(workflow=wf)
    assert policy is not None
    assert policy.name == "core_drop"
