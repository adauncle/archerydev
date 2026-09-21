"""
DBA-bug-11 跨文件 ## 注释演练 (4 文件全项目统一修)
- 静态: 4 文件都加 startswith("##") 注释跳过
- 钉钉 OA 2 文件按用户拍板不动
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(os.getcwd())

# 4 个本批要修的文件
TARGETS_FIX = [
    ("sql/extensions/ddl_gh_ost/views.py", 147),       # gh-ost precheck  (DBA-bug-11 紧急)
    ("sql/extensions/ddl_sync/services/sync_trigger.py", 110),  # 镜像工单解析
    ("sql/views.py", 288),                            # 业务方提交流水 / 字段 diff / 大表 alert
    ("sql/services/ddl_rollback.py", 167),            # DDL 回滚
]

# 2 个钉钉 OA 文件 (用户拍板不动, 留作下一次清理)
TARGETS_KEEP = [
    ("sql/extensions/dingtalk_oa/services/sql_type_detect.py", 79),
    ("sql/extensions/dingtalk_oa/drivers/dingtalk.py", 281),
]


def check_files():
    print("=" * 70)
    print("跨文件 ## 注释支持 (DBA-bug-11 完整清理, 4 文件已修 + 2 文件按用户拍板不动)")
    print("=" * 70)

    passed = 0
    total = 0

    print("\n  [本批要修] (4 文件):")
    for fp, line in TARGETS_FIX:
        total += 1
        full_path = REPO_ROOT / fp
        if not full_path.exists():
            print(f"    [FAIL] {fp}: 文件不存在")
            continue
        src = full_path.read_text(encoding="utf-8")
        # 必须包含 startswith("##") 才算修过
        if 'startswith("##")' in src:
            print(f"    [PASS] {fp}:{line} 已支持 ## 注释")
            passed += 1
        else:
            print(f"    [FAIL] {fp}:{line} 仍未支持 ## 注释")

    print("\n  [本批不动] (2 文件, 用户拍板不动):")
    for fp, line in TARGETS_KEEP:
        total += 1
        full_path = REPO_ROOT / fp
        if not full_path.exists():
            print(f"    [SKIP] {fp}: 文件不存在")
            total -= 1
            continue
        src = full_path.read_text(encoding="utf-8")
        # 验证: 钉钉 OA 文件仍只用 startswith("--") 不处理 ##
        # 这是符合用户拍板的 "不动" 状态
        if 'startswith("--")' in src and 'startswith("##")' not in src:
            print(f"    [PASS] {fp}:{line} 按用户拍板不动 (still only --, not ##)")
            passed += 1
        elif 'startswith("##")' in src:
            print(f"    [WARN] {fp}:{line} 已支持 ## 注释 (与用户拍板矛盾)")
        else:
            print(f"    [N/A]  {fp}:{line} 未发现 startswith('--')")

    print()
    print(f"PASS {passed}/{total}")
    return passed == total


if __name__ == "__main__":
    print(f"Repo: {REPO_ROOT}")
    print()
    ok = check_files()
    if ok:
        print("\n[ALL PASS] 跨文件 ## 注释支持确认 (DBA-bug-11 全项目清理完毕)")
        print("下一步: 134 dev + 110 prod 部署 + 演练 PASS")
        sys.exit(0)
    else:
        print("\n[FAIL] 有文件未修复")
        sys.exit(1)