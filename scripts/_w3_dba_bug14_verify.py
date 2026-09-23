#!/usr/bin/env python3
"""9/23 DBA-bug-14 演练: 删除 detail.html renderColumnDialog JS 拼的大表 alert (重复块)

业务: 9/23 13:50 阿达叔叔反馈 wf#4885 大表工单详情页显示两个相同 alert 块 (UX 重复)
根因: 后端模板 line 557-614 `{% if big_table_alert %}` 已稳定渲染 (含字段 diff 按钮 + DBA 兜底),
      8/26 JS 拼 bigTableAlertHtml 只是补文案, 重复且没按钮 (纯噪音)
修法: 删除 detail.html JS line 1878-1894 整段 bigTableAlertHtml 拼装 + var html 不再拼它
保留: 后端模板 line 557-614 块 (字段 diff 按钮 + DBA 兜底启用 gh-ost + 立即执行双层 confirm 全在这)

实战新发现 (跨项目可复用):
  "页面有两块静态 + JS 拼同一 UI 内容时, 优先保留功能完整的后端模板块, 删 JS 拼的纯文案块"

演练: 静态 + JS 拼装对齐
"""
import os
import sys
from pathlib import Path

REPO = Path(r"G:\MiniMax工作空间\archery_dev")
DETAIL = REPO / "sql" / "templates" / "detail.html"


def assert_in(needle, haystack, label):
    if needle in haystack:
        print(f"  ✅ {label}")
        return True
    print(f"  ❌ {label}: 未找到 '{needle}'")
    return False


def assert_not_in(needle, haystack, label):
    if needle not in haystack:
        print(f"  ✅ {label}")
        return True
    print(f"  ❌ {label}: 不应有 '{needle}'")
    return False


def main():
    if not DETAIL.exists():
        print(f"❌ 找不到 {DETAIL}")
        sys.exit(1)
    text = DETAIL.read_text(encoding="utf-8")

    passed = 0
    total = 0

    print("\n[1] 后端模板大表 alert 块 (DBA 兜底 + 字段 diff 按钮) 还在")
    for needle, label in [
        ('{% if big_table_alert %}', "    模板条件还在 (line 557)"),
        ('id="big-table-alert"', "    容器 id 还在"),
        ('id="btn-big-table-column-diff"', "    字段 diff 按钮还在"),
        ('id="btn-big-table-execute"', "    立即执行按钮还在 (DBA 兜底双层 confirm)"),
        ('id="btn-big-table-enable-ghost"', "    启用 gh-ost 按钮还在 (DBA 兜底)"),
        ('{% if can_enable_ghost %}', "    can_enable_ghost 守卫还在 (DBA-bug-13 第一波)"),
    ]:
        total += 1
        if assert_in(needle, text, label):
            passed += 1

    print("\n[2] 9/23 DBA-bug-14: JS 拼的重复大表 alert 块已删除")
    # 检测删除: 注释说 "JS 拼 bigTableAlertHtml 已删" + var html 直接拼 div
    for needle, label in [
        ('var html =\n', "    var html 直接拼 div (无 bigTableAlertHtml 前缀)"),
    ]:
        total += 1
        if assert_in(needle, text, label):
            passed += 1

    # 检测删除: 整段 bigTableAlertHtml 变量声明 + if 块不应存在
    total += 1
    if assert_not_in(
        'var bigTableAlertHtml = "";',
        text,
        "    bigTableAlertHtml 变量声明已删除 (原 line 1878)",
    ):
        passed += 1

    total += 1
    if assert_not_in(
        "bigTableAlertHtml +",
        text,
        "    bigTableAlertHtml 字符串拼接已删除 (原 line 1881 / 2008)",
    ):
        passed += 1

    # 注释里允许提到 (留作根因记录)
    total += 1
    if assert_in(
        "// 9/23 DBA-bug-14 删除 JS 拼装的大表 alert",
        text,
        "    留有删除说明注释 (跨项目复用 + 实战新发现)",
    ):
        passed += 1

    print("\n[3] 字段 diff inline 区域 (#column-diff-result) 还在")
    for needle, label in [
        ('<div id="column-diff-result"', "    容器 div 还在 (line 908)"),
        ('fetchColumnDiff(sqlContent, instanceId, dbName)', "    detail 页加载时自动触发 fetchColumnDiff"),
    ]:
        total += 1
        if assert_in(needle, text, label):
            passed += 1

    print("\n[4] 改动的代码位置 line 范围")
    # 查 line 1997 (新 var html 起始) + 1877 (注释起始位置)
    code_lines = text.splitlines()
    if len(code_lines) >= 1997:
        target = code_lines[1996]
        total += 1
        if "var html =" in target and "bigTableAlertHtml" not in target:
            print(f"  ✅ line 1997 var html = (不含 bigTableAlertHtml): {target.strip()}")
            passed += 1
        else:
            print(f"  ❌ line 1997 异常: {target.strip()}")

    print(f"\n{'='*60}")
    print(f"DBA-bug-14 静态演练结果: {passed}/{total} PASS")
    print(f"{'='*60}")
    if passed == total:
        print("✅ 全部通过，可以部署双端")
        sys.exit(0)
    else:
        print("❌ 失败，需要排查")
        sys.exit(1)


if __name__ == "__main__":
    main()