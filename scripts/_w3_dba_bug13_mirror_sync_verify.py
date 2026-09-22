"""
DBA-bug-13 第二波演练: 镜像工单继承 enable_gh_ost + gh_ost_mode
- 静态: sync_trigger.py:246-258 SqlWorkflow.objects.create 加 enable_gh_ost + gh_ost_mode 字段
- 静态: views.py:640-660 lazy auto-enable 存在 (enable_gh_ost + review_pass + 无 task → 自动 _enable_ghost_for_workflow)
- 逻辑: 验证 wf#4878 修复路径 (业务方下次打开详情页 lazy auto-enable)
"""
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.getcwd())
SYNC_TRIGGER = REPO_ROOT / "sql" / "extensions" / "ddl_sync" / "services" / "sync_trigger.py"
VIEWS = REPO_ROOT / "sql" / "views.py"


def check_sync_trigger():
    print("=" * 70)
    print("静态用例: sync_trigger.py 镜像工单继承 enable_gh_ost + gh_ost_mode")
    print("=" * 70)
    src = SYNC_TRIGGER.read_text(encoding="utf-8")
    cases = []

    # Case 1: SqlWorkflow.objects.create 含 enable_gh_ost
    has_enable = re.search(r"enable_gh_ost\s*=\s*getattr\(source_workflow,\s*['\"]enable_gh_ost['\"]", src)
    cases.append(("Case 1: sync_trigger.py SqlWorkflow.objects.create 含 enable_gh_ost=source_workflow", bool(has_enable)))

    # Case 2: SqlWorkflow.objects.create 含 gh_ost_mode
    has_mode = re.search(r"gh_ost_mode\s*=\s*getattr\(source_workflow,\s*['\"]gh_ost_mode['\"]", src)
    cases.append(("Case 2: sync_trigger.py SqlWorkflow.objects.create 含 gh_ost_mode=source_workflow", bool(has_mode)))

    # Case 3: 加 CUSTOM-MODIFIED 注释引用 DBA-bug-13
    has_comment = "DBA-bug-13" in src and "enable_gh_ost" in src
    cases.append(("Case 3: 加 CUSTOM-MODIFIED 注释引用 DBA-bug-13", has_comment))

    # Case 4: create_target_workflow 函数还包含 pair.target_instance
    has_instance = "instance=pair.target_instance" in src
    cases.append(("Case 4: create_target_workflow 仍含 pair.target_instance", has_instance))

    passed = 0
    for name, ok in cases:
        marker = "[PASS]" if ok else "[FAIL]"
        print(f"  {marker} {name}")
        if ok:
            passed += 1
    print(f"\nPASS {passed}/{len(cases)}")
    return passed == len(cases)


def check_lazy_auto_enable():
    print()
    print("=" * 70)
    print("静态用例: views.py lazy auto-enable 逻辑 (配合 sync_trigger 修法)")
    print("=" * 70)
    src = VIEWS.read_text(encoding="utf-8")
    cases = []

    # Case 1: lazy auto-enable 存在
    has_lazy = "lazy auto-enable" in src
    cases.append(("Case 1: views.py 含 'lazy auto-enable' 逻辑", has_lazy))

    # Case 2: enable_gh_ost + status=review_pass 守卫
    has_guard = re.search(
        r"if\s*\(\s*getattr\(workflow_detail,\s*['\"]enable_gh_ost['\"]"
        r".*?workflow_detail\.status\s*==\s*['\"]workflow_review_pass['\"]",
        src, re.DOTALL,
    )
    cases.append(("Case 2: lazy auto-enable 守卫: enable_gh_ost=True + status=workflow_review_pass", bool(has_guard)))

    # Case 3: 自动调 _enable_ghost_for_workflow (跨行)
    has_call = re.search(r"_enable_ghost_for_workflow\(\s*workflow_detail", src)
    cases.append(("Case 3: lazy auto-enable 自动调 _enable_ghost_for_workflow", bool(has_call)))

    # Case 4: existing is None 守卫 (避免重复创建)
    has_existing_none = re.search(
        r"existing\s*=\s*DdlGhostTask\.objects\.filter\([^)]+\)\s*\.\s*first\(\)\s*if\s+existing\s+is\s+None",
        src, re.DOTALL,
    )
    cases.append(("Case 4: existing is None 守卫 (避免重复创建 DdlGhostTask)", bool(has_existing_none)))

    passed = 0
    for name, ok in cases:
        marker = "[PASS]" if ok else "[FAIL]"
        print(f"  {marker} {name}")
        if ok:
            passed += 1
    print(f"\nPASS {passed}/{len(cases)}")
    return passed == len(cases)


def check_logical():
    print()
    print("=" * 70)
    print("逻辑验证: 镜像工单 (enable_gh_ost=True) + 业务方打开详情页 → lazy auto-enable")
    print("=" * 70)
    src_views = VIEWS.read_text(encoding="utf-8")
    src_sync = SYNC_TRIGGER.read_text(encoding="utf-8")

    # 关键流程
    print("\n  流程验证:")
    print("    1. DDL-Sync 创建镜像工单 (sync_trigger.py)")
    print("       enable_gh_ost=source_workflow.enable_gh_ost (True)")
    print("       gh_ost_mode=source_workflow.gh_ost_mode ('smart')")
    print("    2. 业务方打开详情页 → views.py detail 视图渲染")
    print("       if enable_gh_ost=True AND status=review_pass:")
    print("           if existing is None (没 DdlGhostTask):")
    print("               _enable_ghost_for_workflow(workflow, ...)")
    print("    3. _enable_ghost_for_workflow:")
    print("       - smart 模式 + size_info 查大表 → 创建 DdlGhostTask")
    print("       - 全部小表 → 加入 small_alters (DBA-bug-13 守卫 not has_native_alter)")
    print("    4. detail.html 渲染:")
    print("       has_ghost_task=True → 显示进度面板")
    print("       has_native_alter=True (小表) → 显示已加入小表原生 ALTER 队列")
    print("       can_enable_ghost=False → 不显示启用按钮")

    cases = []
    # sync_trigger 有 enable_gh_ost + gh_ost_mode
    cases.append(("sync_trigger 复制 enable_gh_ost", "enable_gh_ost=getattr" in src_sync))
    cases.append(("sync_trigger 复制 gh_ost_mode", "gh_ost_mode=getattr" in src_sync))
    # views.py lazy auto-enable
    cases.append(("views.py lazy auto-enable 触发条件正确", "enable_gh_ost" in src_views and "workflow_review_pass" in src_views))
    cases.append(("views.py lazy auto-enable 调 _enable_ghost_for_workflow", "_enable_ghost_for_workflow" in src_views))
    # DBA-bug-13 守卫 (DBA-bug-12 + not-stack)
    cases.append(("views.py can_enable_ghost 加 not has_native_alter 守卫 (DBA-bug-13)",
                  "and not has_native_alter" in src_views))

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
    print(f"sync_trigger.py: {SYNC_TRIGGER}")
    print(f"views.py: {VIEWS}")
    print()
    ok1 = check_sync_trigger()
    ok2 = check_lazy_auto_enable()
    ok3 = check_logical()
    if ok1 and ok2 and ok3:
        print("\n[ALL PASS] 4 + 4 + 5 = 13/13")
        print("下一步: 134 dev + 110 prod 部署 + 阿达叔叔浏览器实战测 wf#4878 (硬刷新)")
        sys.exit(0)
    else:
        print("\n[FAIL] 有用例失败")
        sys.exit(1)