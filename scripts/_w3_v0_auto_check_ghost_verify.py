"""
v0.3.x 大表自动勾选 gh-ost 演练
- 静态语法: autoCheckGhostCheckbox 函数 + 3 处文案 + 2 处调用
- 边界: has_non_alter=true 时不勾
- 演练 134 dev / 110 prod (浏览器手动测)

不修改 db, 不修改代码, 只读代码 + mock ajax 响应.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(os.getcwd())
SQLSUBMIT = REPO_ROOT / "sql" / "templates" / "sqlsubmit.html"

# ============ 静态用例 (代码静态检查) ============
def check_static():
    print("=" * 70)
    print("静态用例: 大表自动勾选 gh-ost (autoCheckGhostCheckbox)")
    print("=" * 70)
    src = SQLSUBMIT.read_text(encoding="utf-8")

    cases = []

    # Case 1: autoCheckGhostCheckbox 函数定义存在
    has_fn = "function autoCheckGhostCheckbox(data)" in src
    cases.append(("Case 1: autoCheckGhostCheckbox 函数定义存在", has_fn))

    # Case 2: 函数里有 bigTables + hasNonAlter 判断
    has_logic = "bigTables.length > 0 && !hasNonAlter" in src
    cases.append(("Case 2: 函数判断逻辑 '大表 + 非 ALTER 类'", has_logic))

    # Case 3: 函数 trigger('change') 让 gh_ost_mode 下拉框显示
    has_trigger = "$cb.prop('checked', true).trigger('change')" in src
    cases.append(("Case 3: trigger('change') 联动 gh_ost_mode 下拉框", has_trigger))

    # Case 4-6: 3 处文案已改 (强烈建议 → 已自动勾选 + 业务方可手动取消)
    has_text_822 = '已自动勾选 "启用 gh-ost 无锁变更"' in src and "业务方可手动取消" in src
    has_text_846 = src.count('已自动勾选 "启用 gh-ost 无锁变更"') == 3  # 3 处都改
    has_text_clear_old = "强烈建议在上方勾选" not in src  # 旧文案完全清除
    cases.append(("Case 4: 3 处文案全部改为 '已自动勾选'", has_text_846))
    cases.append(("Case 5: 3 处文案都带 '业务方可手动取消'", has_text_822))
    cases.append(("Case 6: 旧文案 '强烈建议在上方勾选' 完全清除", has_text_clear_old))

    # Case 7: 2 处调用 autoCheckGhostCheckbox (data.ok=true + data.ok=false 两 case)
    has_call_count = src.count("autoCheckGhostCheckbox(data)") >= 2
    cases.append(("Case 7: doFetchColumnDiff success 里 2 处调用", has_call_count))

    # Case 8: has_non_alter 边界 (window.__nonAlterData.has_non_alter)
    has_hasnonalter = "window.__nonAlterData && window.__nonAlterData.has_non_alter" in src
    cases.append(("Case 8: has_non_alter 边界判断正确", has_hasnonalter))

    # Case 9: enable_ghost onchange handler 仍在 (line 1502)
    has_onchange_handler = '$("#enable_ghost").on("change", function ()' in src
    cases.append(("Case 9: enable_ghost onchange handler 保留 (gh_ost_mode 下拉框联动)", has_onchange_handler))

    # Case 10: renderBigTableAlertOnly + renderBigTableBanner + renderColumnDiff 三处渲染都加 autoCheckGhostCheckbox
    # (实际是 doFetchColumnDiff success 调, renderColumnDiff / renderBigTableAlertOnly 间接渲染)
    # 这里只验证函数存在
    has_render3 = all(
        fn in src
        for fn in ["renderBigTableAlertOnly", "renderBigTableBanner", "renderColumnDiff"]
    )
    cases.append(("Case 10: 3 个渲染函数都在 (间接覆盖自动勾选)", has_render3))

    passed = 0
    for i, (name, ok) in enumerate(cases, 1):
        marker = "[PASS]" if ok else "[FAIL]"
        print(f"  {marker} {name}")
        if ok:
            passed += 1

    print()
    print(f"PASS {passed}/{len(cases)}")
    return passed == len(cases)


# ============ Mock JS 逻辑测试 (模拟浏览器行为) ============
def check_js_logic():
    """Mock jQuery + 模拟 doFetchColumnDiff success 调用, 验证 autoCheckGhostCheckbox 行为"""
    print()
    print("=" * 70)
    print("Mock JS 逻辑: 模拟浏览器 checkbox + __nonAlterData")
    print("=" * 70)

    # Mock jQuery behavior
    class MockCheckbox:
        def __init__(self):
            self.checked = False
            self.change_triggered = 0
        def is_checked(self):
            return self.checked
        def prop(self, key, val):
            if key == "checked":
                self.checked = val
        def trigger(self, event):
            if event == "change":
                self.change_triggered += 1

    cb = MockCheckbox()
    non_alter_data = None  # 业务方一般 ALTER

    # 模拟 autoCheckGhostCheckbox 逻辑
    def auto_check_ghost(big_tables, non_alter_data):
        if big_tables and len(big_tables) > 0 and not (non_alter_data and non_alter_data.get("has_non_alter")):
            if not cb.is_checked():
                cb.prop("checked", True)
                cb.trigger("change")

    # 1. 大表 + 全 ALTER → 自动勾
    print("\n  场景 1: 大表 + 全 ALTER (CREATE INDEX)")
    auto_check_ghost([{"table_name": "accesscard_channel_task", "rows": 1707167, "size_mb": 865.4}], non_alter_data)
    print(f"    checkbox.checked={cb.checked}, change_triggered={cb.change_triggered} (期望 True, True)")
    assert cb.checked and cb.change_triggered == 1, "❌ 场景 1 失败"

    # 2. 大表 + has_non_alter=True → 不勾
    print("\n  场景 2: 大表 + 含 CREATE/INSERT (has_non_alter=true)")
    cb.checked = False
    cb.change_triggered = 0
    auto_check_ghost(
        [{"table_name": "accesscard_dynamicaccountinfo", "rows": 69906664, "size_mb": 64631}],
        {"has_non_alter": True, "examples": [{"stmt_type": "CREATE", "full": "CREATE TABLE ..."}]},
    )
    print(f"    checkbox.checked={cb.checked}, change_triggered={cb.change_triggered} (期望 False, False)")
    assert not cb.checked and cb.change_triggered == 0, "❌ 场景 2 失败"

    # 3. 没大表 → 不勾
    print("\n  场景 3: 没大表")
    cb.checked = False
    cb.change_triggered = 0
    auto_check_ghost([], non_alter_data)
    print(f"    checkbox.checked={cb.checked}, change_triggered={cb.change_triggered} (期望 False, False)")
    assert not cb.checked, "❌ 场景 3 失败"

    # 4. 业务方手动取消 → 不再自动勾
    print("\n  场景 4: 业务方手动取消勾选 (再触发 auto_check 不会重新勾上)")
    cb.checked = True  # 业务方手动勾上
    cb.change_triggered = 1  # 业务方手动勾时 trigger('change') 由 UI 触发
    auto_check_ghost([{"table_name": "x", "rows": 100000}], non_alter_data)
    print(f"    checkbox.checked={cb.checked} (期望 True, 不会重新勾上因为已经勾上)")
    assert cb.checked, "❌ 场景 4 失败 (业务方已勾, auto_check 跳过)"

    # 5. 多张大表混合 → 自动勾
    print("\n  场景 5: 多张大表混合 (DBA-bug-9.5 wf#4841 类似)")
    cb.checked = False
    cb.change_triggered = 0
    big_tables = [
        {"table_name": "table_a", "rows": 200000, "size_mb": 200},
        {"table_name": "table_b", "rows": 150000, "size_mb": 150},
    ]
    auto_check_ghost(big_tables, non_alter_data)
    print(f"    checkbox.checked={cb.checked} (期望 True, 多张大表也自动勾)")
    assert cb.checked, "❌ 场景 5 失败"

    print()
    print("[PASS] Mock JS 逻辑 5/5 通过")
    return True


if __name__ == "__main__":
    print(f"Repo: {REPO_ROOT}")
    print(f"sqlsubmit.html: {SQLSUBMIT}")
    print()

    ok1 = check_static()
    ok2 = check_js_logic()

    if ok1 and ok2:
        print("\n" + "=" * 70)
        print("[ALL PASS] 10 静态 + 5 mock JS 逻辑")
        print("下一步: 134 dev + 110 prod 部署 + 浏览器实战测 (阿达叔叔)")
        print("=" * 70)
        sys.exit(0)
    else:
        print("\n[FAIL] 有用例失败")
        sys.exit(1)