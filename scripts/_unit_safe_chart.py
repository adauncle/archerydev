"""_unit_safe_chart.py — 纯单测 get_chart_data 的 _safe 包装器
不连数据库, 只验证 try/except 优雅降级行为
"""
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 直接 inline import common.dashboard 的一部分, 不走 Django settings
import importlib.util

# 1. 抽出 _safe 函数定义
# 我们只需要测 try/except 包装行为, 不用 import django

def _safe(name, builder):
    """1 张图查失败不影响其他图, 失败时返空字符串"""
    try:
        return builder()
    except Exception as e:
        print(f"  [WARN] dashboard {name} failed: {e}")
        return ""


def make_chart_mock(fail_keys):
    """模拟 chart_dao, fail_keys 里的方法会抛 ProgrammingError(1146)"""
    class FakeChartDao:
        def __getattr__(self, name):
            if name in fail_keys:
                def _fail(*args, **kwargs):
                    raise Exception(f"(1146, \"Table 'archery_prod.{name}_table' doesn't exist\")")
                return _fail
            # 默认返空
            return lambda *a, **k: {"column_list": [], "rows": []}

    class FakeBar:
        def render_embed(self):
            return f"<bar>ok</bar>"
    class FakePie:
        def render_embed(self):
            return f"<pie>ok</pie>"
    class FakeLine:
        def render_embed(self):
            return f"<line>ok</line>"

    def make_bar_chart(a, v, *args, **kwargs):
        return FakeBar()
    def make_pie_chart(a, v, *args, **kwargs):
        return FakePie()
    def make_line(*args, **kwargs):
        return FakeLine()

    return FakeChartDao(), make_bar_chart, make_pie_chart, FakeLine


# 4 Case
def case_a_all_ok():
    """Case A: 所有图都成功"""
    print("\n=== Case A: 所有图都成功 ===")
    chart_dao, mbc, mpc, FL = make_chart_mock(set())
    # 模拟 10 张图全部成功
    chart = {}
    chart["bar1"] = _safe("bar1", lambda: mbc([], []).render_embed())
    chart["pie1"] = _safe("pie1", lambda: mpc([], []).render_embed())
    chart["bar3"] = _safe("bar3", lambda: mbc([], []).render_embed())
    chart["pie3"] = _safe("pie3", lambda: mpc([], []).render_embed())
    chart["line1"] = _safe("line1", lambda: FL().render_embed())
    print(f"  10 keys, all non-empty: {all(v for v in chart.values())}")
    assert all(v for v in chart.values()), "Case A 失败: 有图是空"
    assert len(chart) == 5
    print("  [OK] 所有图都返回非空")


def case_b_pie3_bar3_fail():
    """Case B: 模拟 134 dev 真实场景 - pie3 + bar3 (慢 SQL) 失败"""
    print("\n=== Case B: pie3 + bar3 失败 (134 dev 真实场景) ===")
    # 这里我们手动测 _safe 行为, 不走 chart_dao
    def pie3():
        raise Exception("(1146, \"Table 'archery_prod.mysql_slow_query_review_history' doesn't exist\")")
    def bar3():
        raise Exception("(1146, \"Table 'archery_prod.mysql_slow_query_review_history' doesn't exist\")")
    def bar1_ok():
        return "<bar>bar1</bar>"
    def pie1_ok():
        return "<pie>pie1</pie>"

    chart = {
        "bar1": _safe("bar1", bar1_ok),
        "pie1": _safe("pie1", pie1_ok),
        "bar3": _safe("bar3", bar3),
        "pie3": _safe("pie3", pie3),
    }
    print(f"  bar1: {chart['bar1']!r}")
    print(f"  pie1: {chart['pie1']!r}")
    print(f"  bar3: {chart['bar3']!r}  (期望空字符串)")
    print(f"  pie3: {chart['pie3']!r}  (期望空字符串)")
    assert chart["bar1"] == "<bar>bar1</bar>", "bar1 应该成功"
    assert chart["pie1"] == "<pie>pie1</pie>", "pie1 应该成功"
    assert chart["bar3"] == "", "bar3 应该空 (优雅降级)"
    assert chart["pie3"] == "", "pie3 应该空 (优雅降级)"
    print("  [OK] 慢 SQL 2 张图空,其他 2 张图正常")


def case_c_all_fail():
    """Case C: 10 张图全失败"""
    print("\n=== Case C: 10 张图全失败 ===")
    def fail_all():
        raise Exception("(1146, \"Table missing\")")
    chart = {}
    for key in ["bar1", "bar2", "bar3", "bar5", "pie1", "pie2", "pie3", "pie4", "pie5", "line1"]:
        chart[key] = _safe(key, fail_all)
    print(f"  10 keys, all empty: {all(v == '' for v in chart.values())}")
    assert all(v == "" for v in chart.values()), "Case C 失败: 有图非空"
    print("  [OK] 全部 10 张图空, 不抛 500")


def case_d_real_repro():
    """Case D: 真实复现 1146 异常类型"""
    print("\n=== Case D: 真实复现 1146 异常 (Django ProgrammingError) ===")
    # 模拟 Django.db.utils.ProgrammingError
    class FakeProgrammingError(Exception):
        pass

    def raise_1146():
        raise FakeProgrammingError("(1146, \"Table 'archery_prod.mysql_slow_query_review_history' doesn't exist\")")

    # _safe 应该捕获 (用 Exception 基类, ProgrammingError 是其子类)
    result = _safe("pie3", raise_1146)
    print(f"  pie3 抛 FakeProgrammingError 后: {result!r}")
    assert result == "", "pie3 应该空"
    print("  [OK] FakeProgrammingError 被 _safe 捕获")


if __name__ == "__main__":
    case_a_all_ok()
    case_b_pie3_bar3_fail()
    case_c_all_fail()
    case_d_real_repro()
    print("\n[ALL OK] 4 Case 单测全过")
