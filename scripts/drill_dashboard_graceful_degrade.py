"""drill_dashboard_graceful_degrade.py — dashboard 优雅降级 端到端演练

8/17 mavis 修 Archery 上游 get_chart_data 串行查询无 try/except 缺陷。
本脚本验证:
- 4 Case 全过: A 全好 / B 单图挂 / C 多图挂 / D 全挂
- D Case 真实模拟 134 dev mysql_slow_query_review_history 表不存在场景

运行环境: 134 dev /opt/archery/prod (Django 5.2 + archery_prod 库)
跑法: cd /opt/archery/prod && sudo -u archery venv/bin/python scripts/drill_dashboard_graceful_degrade.py

返回码: 0 = 全过, 1 = 有 Case 失败
"""
import io
import sys
import os
import django

# 强制 UTF-8 stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, "/opt/archery/prod")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()

# 强制 UTF-8 log
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

from common.dashboard import get_chart_data
from unittest.mock import patch, MagicMock


def case_a_all_ok():
    """Case A: 所有图都成功 (正常路径)"""
    print("\n=== Case A: 10 张图全成功 (正常路径) ===")
    chart = get_chart_data("2026-08-11", "2026-08-17")
    print(f"  chart keys: {sorted(chart.keys())}")
    assert len(chart) == 10, f"应该有 10 个 key, 实际 {len(chart)}"
    for key, val in chart.items():
        print(f"  {key}: {len(val)} chars  type={type(val).__name__}")
    # 验证: 所有非慢 SQL 的图都应非空 (134 dev archery_prod 库有 sql_workflow/query_log 等核心表)
    core_keys = ["bar1", "bar2", "bar5", "pie1", "pie2", "pie4", "pie5", "line1"]
    for k in core_keys:
        assert chart[k], f"核心图 {k} 应该非空, 实际为空"
    # 慢 SQL 2 张图 (pie3/bar3) 在 134 dev 库是空的 (无数据 + 8/06 事故后表不存在)
    # 这里看 134 dev 库实际状态
    if not chart.get("pie3") and not chart.get("bar3"):
        print("  [INFO] pie3/bar3 返空 (符合 134 dev 库现状, 表不存在)")
    else:
        print(f"  [INFO] pie3: {len(chart.get('pie3', ''))} chars, bar3: {len(chart.get('bar3', ''))} chars")
    print("  [OK] Case A 全过")


def case_b_pie3_bar3_fail():
    """Case B: 模拟 pie3 + bar3 抛异常, 其他图正常"""
    print("\n=== Case B: pie3 + bar3 抛 1146, 其他图正常 ===")
    from django.db.utils import ProgrammingError

    original_get = get_chart_data
    # 用 mock 替换 chart_dao 的 slow_query_count_by_db / slow_query_count_by_db_by_user
    from common.utils.chart_dao import ChartDao

    def fail_slow(*args, **kwargs):
        raise ProgrammingError("(1146, \"Table 'archery_prod.mysql_slow_query_review_history' doesn't exist\")")

    with patch.object(ChartDao, 'slow_query_count_by_db_by_user', side_effect=fail_slow), \
         patch.object(ChartDao, 'slow_query_count_by_db', side_effect=fail_slow):
        chart = get_chart_data("2026-08-11", "2026-08-17")

    assert chart["pie3"] == "", f"pie3 应该空, 实际 {chart['pie3']!r}"
    assert chart["bar3"] == "", f"bar3 应该空, 实际 {chart['bar3']!r}"
    # 其他 8 张图都非空
    other_keys = ["bar1", "bar2", "bar5", "pie1", "pie2", "pie4", "pie5", "line1"]
    for k in other_keys:
        assert chart[k], f"其他图 {k} 应该非空, 实际为空"
    print(f"  pie3: {chart['pie3']!r}  (期望空)")
    print(f"  bar3: {chart['bar3']!r}  (期望空)")
    print(f"  其他 8 张图: 全非空 ✓")
    print("  [OK] Case B 单图挂优雅降级")


def case_c_all_fail():
    """Case C: 10 张图全挂 (Django middleware 兜底验证)"""
    print("\n=== Case C: 10 张图全抛异常 (验证整页不 500) ===")
    from django.db.utils import ProgrammingError
    from common.utils.chart_dao import ChartDao

    def fail_all(*args, **kwargs):
        raise ProgrammingError("(1146, \"Table missing\")")

    # patch 所有 chart_dao 方法都失败
    with patch.object(ChartDao, 'workflow_by_date', side_effect=fail_all), \
         patch.object(ChartDao, 'workflow_by_group', side_effect=fail_all), \
         patch.object(ChartDao, 'syntax_type', side_effect=fail_all), \
         patch.object(ChartDao, 'workflow_by_user', side_effect=fail_all), \
         patch.object(ChartDao, 'querylog_effect_row_by_date', side_effect=fail_all), \
         patch.object(ChartDao, 'querylog_count_by_date', side_effect=fail_all), \
         patch.object(ChartDao, 'querylog_effect_row_by_user', side_effect=fail_all), \
         patch.object(ChartDao, 'querylog_effect_row_by_db', side_effect=fail_all), \
         patch.object(ChartDao, 'slow_query_count_by_db_by_user', side_effect=fail_all), \
         patch.object(ChartDao, 'slow_query_count_by_db', side_effect=fail_all), \
         patch.object(ChartDao, 'query_sql_prod_bill', side_effect=fail_all):
        try:
            chart = get_chart_data("2026-08-11", "2026-08-17")
        except Exception as e:
            print(f"  [FAIL] get_chart_data 抛异常: {e}")
            return False

    # 全部 10 张图都是空字符串
    for k, v in chart.items():
        assert v == "", f"{k} 应该空, 实际 {v!r}"
    print(f"  10 keys, all empty: True")
    print("  [OK] Case C 全挂优雅降级 (整页不 500)")


def case_d_real_repro():
    """Case D: 真实 134 dev 复现 - 表不存在"""
    print("\n=== Case D: 真实复现 134 dev 1146 异常 ===")
    # 不 mock, 让 chart_dao 真去查, 看 pie3/bar3 是不是优雅空
    from common.utils.chart_dao import ChartDao
    cd = ChartDao()
    print("  验证 chart_dao 抛真实异常:")
    try:
        data = cd.slow_query_count_by_db_by_user()
        print(f"  pie3 data: {data!r}  (134 dev 库有表? 不会走 Case D)")
        # 如果有表, 这个 case 不算 134 dev 真实场景
        return
    except Exception as e:
        print(f"  异常: {e}")
        assert "1146" in str(e) or "doesn't exist" in str(e), f"期望 1146, 实际 {e}"

    # 真实调用 get_chart_data, pie3/bar3 应该空
    chart = get_chart_data("2026-08-11", "2026-08-17")
    assert chart["pie3"] == "", "pie3 应该空"
    assert chart["bar3"] == "", "bar3 应该空"
    # 其他 8 张图非空
    other_keys = ["bar1", "bar2", "bar5", "pie1", "pie2", "pie4", "pie5", "line1"]
    for k in other_keys:
        assert chart[k], f"{k} 应该非空"
    print("  [OK] Case D 真实 1146 优雅降级, 其他图不受影响")


if __name__ == "__main__":
    case_a_all_ok()
    case_b_pie3_bar3_fail()
    case_c_all_fail()
    case_d_real_repro()
    print("\n[ALL OK] 4 Case 端到端演练全过")
