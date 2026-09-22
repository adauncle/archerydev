"""
DBA-bug-12 演练: start 端点 ImportError (MySQLEngine class 名大小写错)
- 静态: views.py:538 import MySQLEngine (大写), sql/engines/mysql.py:66 class MysqlEngine (小写)
- mock: 模拟 start 端点调用 _trigger_native_alters, 验证导入失败
- 修法验证: 删除死 import, 演练 PASS
"""
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.getcwd())
VIEWS = REPO_ROOT / "sql" / "extensions" / "ddl_gh_ost" / "views.py"
MYSQL_ENGINE = REPO_ROOT / "sql" / "engines" / "mysql.py"


def check_static():
    print("=" * 70)
    print("静态用例: start 端点 ImportError (DBA-bug-12)")
    print("=" * 70)
    views_src = VIEWS.read_text(encoding="utf-8")
    mysql_src = MYSQL_ENGINE.read_text(encoding="utf-8")
    cases = []

    # Case 1: views.py:538 引用了 MySQLEngine (大写)
    has_wrong_import = re.search(r"from\s+sql\.engines\.mysql\s+import\s+MySQLEngine", views_src)
    cases.append(("Case 1: views.py 含 'from sql.engines.mysql import MySQLEngine' (错的大小写)", bool(has_wrong_import)))

    # Case 2: mysql.py 里实际 class 是 MysqlEngine (小写)
    actual_class = re.search(r"^class\s+MysqlEngine\s*\(", mysql_src, re.MULTILINE)
    cases.append(("Case 2: sql/engines/mysql.py class 是 MysqlEngine (小写 ysql)", bool(actual_class)))

    # Case 3: mysql.py 里没有 MySQLEngine class (大写)
    no_wrong_class = not re.search(r"^class\s+MySQLEngine\s*\(", mysql_src, re.MULTILINE)
    cases.append(("Case 3: sql/engines/mysql.py 没有 MySQLEngine class (确认大小写错)", no_wrong_class))

    # Case 4: 错误信息在 _trigger_native_alters 函数内
    in_function = "def _trigger_native_alters" in views_src and views_src.find(
        "from sql.engines.mysql import MySQLEngine"
    ) > views_src.find("def _trigger_native_alters")
    cases.append(("Case 4: 错误 import 在 _trigger_native_alters 函数体内", in_function))

    # Case 5: 函数体内实际用的是 get_engine(), 不是 MySQLEngine (死 import)
    uses_get_engine = re.search(
        r"def _trigger_native_alters.*?engine\s*=\s*get_engine",
        views_src, re.DOTALL
    )
    cases.append(("Case 5: 函数体内实际用 get_engine() 不是 MySQLEngine (死 import)", bool(uses_get_engine)))

    # Case 6: start 端点 line 812 调 _trigger_native_alters
    start_calls = re.search(
        r"def start\([^)]*\):.*?_trigger_native_alters",
        views_src, re.DOTALL
    )
    cases.append(("Case 6: start 端点调用 _trigger_native_alters (wf#4872 触发)", bool(start_calls)))

    passed = 0
    for name, ok in cases:
        marker = "[PASS]" if ok else "[FAIL]"
        print(f"  {marker} {name}")
        if ok:
            passed += 1
    print(f"\nPASS {passed}/{len(cases)}")
    return passed == len(cases)


def check_import():
    """静态验证 class 名 vs import 名"""
    print()
    print("=" * 70)
    print("静态验证: MySQLEngine (大写, 错) vs MysqlEngine (小写, 对)")
    print("=" * 70)
    mysql_src = MYSQL_ENGINE.read_text(encoding="utf-8")
    cases = []

    # 1. mysql.py 定义了哪些 MySQL 相关的 class
    import re
    classes = re.findall(r"^class\s+(\w+Engine)\s*\(", mysql_src, re.MULTILINE)
    print(f"\n  mysql.py 里定义的 *Engine class: {classes}")

    # 2. 旧代码 views.py 引用了 MySQLEngine (修后应该删掉)
    #    用 grep 排除注释 (## 或 # 开头), 只查代码行的 from sql.engines.mysql import
    views_src_lines = REPO_ROOT.joinpath("sql/extensions/ddl_gh_ost/views.py").read_text(encoding="utf-8").splitlines()
    code_import_lines = [
        line for line in views_src_lines
        if "from sql.engines.mysql import" in line
        and not line.strip().startswith("#")
    ]
    has_MySQLEngine = any("MySQLEngine" in line for line in code_import_lines)
    has_MysqlEngine = any("MysqlEngine" in line for line in code_import_lines)
    print(f"  views.py 代码 (非注释) 含 from sql.engines.mysql import 行数: {len(code_import_lines)}")
    for line in code_import_lines:
        print(f"    {line.strip()}")
    print(f"  引用 MySQLEngine (大写, 错): {has_MySQLEngine}")
    print(f"  引用 MysqlEngine (小写, 对): {has_MysqlEngine}")

    # 3. 修法验证 (删除死 import 后, views.py 代码里不应再有 from sql.engines.mysql import)
    assert "MysqlEngine" in classes, f"❌ MysqlEngine 不在 mysql.py 的 class 列表 {classes}"
    assert len(code_import_lines) == 0, f"❌ views.py 代码里还有 from sql.engines.mysql import: {code_import_lines}"
    assert not has_MySQLEngine, "❌ views.py 代码还在引用 MySQLEngine (大写) → ImportError 仍在"
    print(f"\n  [PASS] mysql.py 定义 MysqlEngine (小写), views.py 代码已删死 import")
    print(f"  [PASS] 修法 (方案 A): 删除 `from sql.engines.mysql import MySQLEngine` 这一行")
    return True


if __name__ == "__main__":
    print(f"Repo: {REPO_ROOT}")
    print(f"views.py: {VIEWS}")
    print(f"mysql.py: {MYSQL_ENGINE}")
    print()
    ok1 = check_static()
    ok2 = check_import()
    if ok1 and ok2:
        print("\n[ALL PASS] 6 静态 + 2 import 演练")
        print("下一步: views.py:538 删除死 import (或改 MysqlEngine), 134 dev + 110 prod 部署")
        sys.exit(0)
    else:
        sys.exit(1)