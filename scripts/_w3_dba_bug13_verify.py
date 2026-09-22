"""
DBA-bug-13 演练: 镜像工单 gh-ost 启用按钮无限循环
- 静态: 后端 has_native_alter + can_enable_ghost 守卫
- 静态: 前端 3 处 elif 状态显示 (进度 / 启用按钮 / 已加入小表原生 ALTER)
- 静态: 启用按钮 JS alert summary
"""
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.getcwd())
VIEWS = REPO_ROOT / "sql" / "views.py"
DETAIL = REPO_ROOT / "sql" / "templates" / "detail.html"


def check_backend():
    print("=" * 70)
    print("静态用例: 后端 has_native_alter + can_enable_ghost 守卫 (DBA-bug-13)")
    print("=" * 70)
    src = VIEWS.read_text(encoding="utf-8")
    cases = []

    # Case 1: has_native_alter 变量初始化
    cases.append(("Case 1: views.py 有 'has_native_alter = False' 初始化",
                  "has_native_alter = False" in src))

    # Case 2: has_native_alter 从 wf.native_alter_results 计算
    cases.append(("Case 2: views.py 有 'has_native_alter = bool(workflow_detail.native_alter_results)'",
                  "has_native_alter = bool(workflow_detail.native_alter_results)" in src))

    # Case 3: can_enable_ghost 加 not has_native_alter 守卫
    has_guard = "and not has_native_alter" in src
    cases.append(("Case 3: can_enable_ghost 加 'and not has_native_alter' 守卫", has_guard))

    # Case 4: context 加 has_native_alter 变量
    in_context = '"has_native_alter": has_native_alter,' in src
    cases.append(("Case 4: context 加 'has_native_alter' 字段传给模板", in_context))

    # Case 5: 加 CUSTOM-MODIFIED 注释 (含 DBA-bug-13 引用)
    has_comment = "DBA-bug-13" in src and "has_native_alter" in src
    cases.append(("Case 5: 加 CUSTOM-MODIFIED 注释引用 DBA-bug-13", has_comment))

    passed = 0
    for name, ok in cases:
        marker = "[PASS]" if ok else "[FAIL]"
        print(f"  {marker} {name}")
        if ok:
            passed += 1
    print(f"\nPASS {passed}/{len(cases)}")
    return passed == len(cases)


def check_frontend():
    print()
    print("=" * 70)
    print("静态用例: 前端 detail.html 3 处状态 + alert summary")
    print("=" * 70)
    src = DETAIL.read_text(encoding="utf-8")
    cases = []

    # Case 1: has_ghost_task 分支 (不变)
    cases.append(("Case 1: '{% if has_ghost_task %}' 进度面板分支保留",
                  "{% if has_ghost_task %}" in src))

    # Case 2: can_enable_ghost 分支 (启用按钮, 条件块)
    cases.append(("Case 2: '{% elif can_enable_ghost %}' 启用按钮分支保留",
                  "{% elif can_enable_ghost %}" in src))

    # Case 3: 新增 has_native_alter 分支 (已加入小表原生 ALTER 队列)
    has_new_branch = "{% elif has_native_alter %}" in src
    cases.append(("Case 3: 新增 '{% elif has_native_alter %}' 已加入小表原生 ALTER 队列分支", has_new_branch))

    # Case 4: 新分支文案含 "已加入小表原生 ALTER 队列"
    has_msg = "已加入小表原生 ALTER 队列" in src
    cases.append(("Case 4: 新分支文案含 '已加入小表原生 ALTER 队列'", has_msg))

    # Case 5: 启用按钮 JS alert 显示 summary (主按钮)
    has_summary_alert_1 = "j.summary" in src and "smart 模式小表已加入原生 ALTER 队列" in src
    cases.append(("Case 5: 启用按钮 JS alert summary (smart 模式小表分支)", has_summary_alert_1))

    # Case 6: 启用按钮 JS alert 显示 summary (DBA 兜底按钮)
    # 文本内容可能不完全一致, 简化判断: 出现 "DBA 兜底" 按钮 + 2 处 alert(msg)
    has_summary_alert_2 = (
        "DBA 兜底" in src
        and src.count("alert(msg)") >= 2  # 主按钮 + DBA 兜底按钮
    )
    cases.append(("Case 6: 启用按钮 JS alert summary (DBA 兜底按钮)", has_summary_alert_2))

    # Case 7: 大表 alert 内 '启用 gh-ost（DBA 兜底）' 按钮条件保留
    cases.append(("Case 7: '启用 gh-ost（DBA 兜底）' 按钮条件 can_enable_ghost 保留",
                  "{% if can_enable_ghost %}" in src and "启用 gh-ost（DBA 兜底）" in src))

    # Case 8: 大表 alert 内 '启用 gh-ost（DBA 兜底）' JS handler 保留
    cases.append(("Case 8: 'btn-big-table-enable-ghost' JS handler 保留 (DBA 兜底按钮)",
                  '$("#btn-big-table-enable-ghost").click' in src))

    passed = 0
    for name, ok in cases:
        marker = "[PASS]" if ok else "[FAIL]"
        print(f"  {marker} {name}")
        if ok:
            passed += 1
    print(f"\nPASS {passed}/{len(cases)}")
    return passed == len(cases)


def check_logical():
    """验证 can_enable_ghost 条件: wf#4873 (镜像工单, has_native_alter=True) 不应显示启用按钮"""
    print()
    print("=" * 70)
    print("逻辑验证: can_enable_ghost 守卫 (wf#4873 镜像工单场景)")
    print("=" * 70)
    views_src = VIEWS.read_text(encoding="utf-8")
    cases = []

    # 全文搜索 can_enable_ghost 后续 50 行的关键守卫
    match = re.search(
        r"can_enable_ghost\s*=\s*\([^;]+\)",
        views_src, re.DOTALL,
    )
    if not match:
        print("  [FAIL] 找不到 can_enable_ghost 赋值")
        return False

    body = match.group(0)  # 整个匹配段 (含 can_enable_ghost = ...)
    print(f"\n  can_enable_ghost body (前 300 字符):\n    {body.strip()[:300]}")

    # 验证 4 个 AND 条件 (perm 4 选 1 + status + not has_ghost_task + not has_native_alter)
    cases.append(("条件包含 'and not has_ghost_task'",
                  "and not has_ghost_task" in body))
    cases.append(("条件包含 'and not has_native_alter' (DBA-bug-13 守卫)",
                  "and not has_native_alter" in body))
    cases.append(("条件包含 status 检查 (workflow_review_pass / workflow_timingtask)",
                  "workflow_review_pass" in body and "workflow_timingtask" in body))
    cases.append(("条件包含 4 选 1 perm 检查 (is_superuser / has_perm / is_dba_group / is_submitter)",
                  all(s in body for s in ["user.is_superuser", "user.has_perm", "is_dba_group", "is_submitter"])))

    passed = 0
    for name, ok in cases:
        marker = "[PASS]" if ok else "[FAIL]"
        print(f"  {marker} {name}")
        if ok:
            passed += 1
    print(f"\nPASS {passed}/{len(cases)}")
    return passed == len(cases)


if __name__ == "__main__":
    print(f"Repo: {REPO_ROOT}")
    print(f"views.py: {VIEWS}")
    print(f"detail.html: {DETAIL}")
    print()
    ok1 = check_backend()
    ok2 = check_frontend()
    ok3 = check_logical()
    if ok1 and ok2 and ok3:
        print("\n[ALL PASS] 5 后端 + 8 前端 + 4 逻辑 = 17/17")
        print("下一步: 134 dev + 110 prod 部署 + 演练")
        sys.exit(0)
    else:
        print("\n[FAIL] 有用例失败")
        sys.exit(1)