# -*- coding: utf-8 -*-
"""DBA-bug-15 pure non-ALTER block drill (134 dev + 110 prod, real HTTP).

Tests /gh_ost/check_non_alter/ response fields + integration:
- is_pure_alter / pure_non_alter / is_mixed / disable_gh_ost / block_reason
- 4 case (pure_alter / pure_create_table / pure_create_index / mixed)
- + 2 case (empty / use_only) for completeness
- old workflow regression: wf#4791 (ALTER) / wf#4848 (CREATE) / wf#4841 (mixed)

Usage:
    python _w3_dba_pure_non_alter_drill.py [134|110]
"""
import os
import sys
import django

ENV = sys.argv[1] if len(sys.argv) > 1 else "134"

if ENV == "134":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
    BASE_URL = "http://127.0.0.1:9003"
else:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
    BASE_URL = "http://127.0.0.1:9123"

os.environ.setdefault("CAS_SERVER_URL", "https://cas.example.com")
os.environ.setdefault("CAS_VERSION", "3")

django.setup()

from django.test import Client
from django.contrib.auth import get_user_model

User = get_user_model()

CASES = [
    (
        "pure_alter",
        'ALTER TABLE hly_accesscard.accesscard_account ADD COLUMN test_col1 VARCHAR(64) NOT NULL DEFAULT "x" COMMENT "test";',
    ),
    (
        "pure_create_table",
        (
            "CREATE TABLE hly_accesscard.accesscard_hnfr_infos (\n"
            "  id bigint NOT NULL,\n"
            "  PRIMARY KEY (id)\n"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
        ),
    ),
    (
        "pure_create_index",
        "CREATE INDEX idx_test ON hly_accesscard.accesscard_account (id);",
    ),
    (
        "mixed_alter_create",
        (
            "ALTER TABLE hly_accesscard.accesscard_account ADD COLUMN test_col2 VARCHAR(64);\n"
            "CREATE TABLE hly_accesscard.test_mixed (id bigint NOT NULL, PRIMARY KEY (id));"
        ),
    ),
    ("empty", ""),
    ("use_only", "use hly_accesscard;"),
]

EXPECTED = {
    "pure_alter":         {"is_pure_alter": True,  "pure_non_alter": False, "is_mixed": False, "disable_gh_ost": False, "block_reason": "",          "alter_count_min": 1, "non_alter_count": 0},
    "pure_create_table":  {"is_pure_alter": False, "pure_non_alter": True,  "is_mixed": False, "disable_gh_ost": True,  "block_reason": "pure_non_alter", "alter_count": 0, "non_alter_count_min": 1},
    "pure_create_index":  {"is_pure_alter": True,  "pure_non_alter": False, "is_mixed": False, "disable_gh_ost": False, "block_reason": "",          "alter_count_min": 1, "non_alter_count": 0},
    "mixed_alter_create": {"is_pure_alter": False, "pure_non_alter": False, "is_mixed": True,  "disable_gh_ost": True,  "block_reason": "mixed",   "alter_count_min": 1, "non_alter_count_min": 1},
    "empty":               {"is_pure_alter": False, "pure_non_alter": False, "is_mixed": False, "disable_gh_ost": False, "block_reason": "",          "alter_count": 0, "non_alter_count": 0},
    "use_only":            {"is_pure_alter": False, "pure_non_alter": False, "is_mixed": False, "disable_gh_ost": False, "block_reason": "",          "alter_count": 0, "non_alter_count": 0},
}


def run_check_non_alter_drill(c):
    print("=" * 60)
    print("  4+2 case /gh_ost/check_non_alter/ drill (env=" + ENV + ")")
    print("=" * 60)
    all_pass = True
    for name, sql in CASES:
        r = c.post("/gh_ost/check_non_alter/", {"sql_content": sql})
        ok_status = r.status_code == 200 if sql else r.status_code == 400
        if not ok_status:
            print("  [" + name + "] FAIL status=" + str(r.status_code))
            all_pass = False
            continue
        if not sql:
            print("  [" + name + "] OK status=400 (empty input, correct)")
            continue
        d = r.json()
        exp = EXPECTED[name]
        mismatches = []
        for k in ("is_pure_alter", "pure_non_alter", "is_mixed", "disable_gh_ost", "block_reason"):
            if d.get(k) != exp.get(k):
                mismatches.append(k + "=" + str(d.get(k)) + " (exp " + str(exp.get(k)) + ")")
        if "alter_count_min" in exp and d.get("alter_count", 0) < exp["alter_count_min"]:
            mismatches.append("alter_count=" + str(d.get("alter_count")) + " (exp >= " + str(exp["alter_count_min"]) + ")")
        if "alter_count" in exp and d.get("alter_count") != exp["alter_count"]:
            mismatches.append("alter_count=" + str(d.get("alter_count")) + " (exp " + str(exp["alter_count"]) + ")")
        if "non_alter_count_min" in exp and d.get("non_alter_count", 0) < exp["non_alter_count_min"]:
            mismatches.append("non_alter_count=" + str(d.get("non_alter_count")) + " (exp >= " + str(exp["non_alter_count_min"]) + ")")
        if "non_alter_count" in exp and d.get("non_alter_count") != exp["non_alter_count"]:
            mismatches.append("non_alter_count=" + str(d.get("non_alter_count")) + " (exp " + str(exp["non_alter_count"]) + ")")
        if mismatches:
            print("  [" + name + "] FAIL: " + ", ".join(mismatches))
            all_pass = False
        else:
            print(
                "  [" + name + "] OK (alter=" + str(d.get("alter_count")) +
                ", non_alter=" + str(d.get("non_alter_count")) +
                ", disable=" + str(d.get("disable_gh_ost")) +
                ", reason=" + repr(d.get("block_reason")) + ")"
            )
    print("=" * 60)
    print("  check_non_alter drill: " + ("PASS" if all_pass else "FAIL"))
    print("=" * 60)
    return all_pass


def run_sqlsubmit_html_drill(c):
    # 134 dev + 110 prod 的 URL 路由都是 /submitsql/, 不是 /sqlsubmit/
    # 模板文件名是 sqlsubmit.html, 但 URL path 是 submitsql/ (上游 Archery 设计)
    print("=" * 60)
    print("  /submitsql/ html verify (env=" + ENV + ")")
    print("=" * 60)
    r = c.get("/submitsql/")
    if r.status_code != 200:
        print("  FAIL: /submitsql/ status=" + str(r.status_code))
        return False
    html = r.content.decode("utf-8", errors="replace")
    checks = [
        ('id="sqlsubmit-ghost-block-warning"',  "inline warning div"),
        ('id="sqlsubmit-ghost-block-title"',    "warning title elem"),
        ('id="sqlsubmit-ghost-block-detail"',   "warning detail elem"),
        ('function applyGhostCheckboxState',    "applyGhostCheckboxState function"),
        ('function debouncedUpdateGhostState', "debouncedUpdateGhostState function"),
        ('debouncedUpdateGhostState();',        "editor.on(change) hookup"),
    ]
    all_pass = True
    for needle, desc in checks:
        if needle in html:
            print("  [OK] " + desc + ": " + repr(needle))
        else:
            print("  [FAIL] " + desc + ": " + repr(needle) + " not found")
            all_pass = False
    print("=" * 60)
    print("  html drill: " + ("PASS" if all_pass else "FAIL"))
    print("=" * 60)
    return all_pass


def run_old_workflow_regression(c):
    print("=" * 60)
    print("  Old workflow regression (env=" + ENV + ")")
    print("=" * 60)
    # 134 dev is a drill DB, no wf#4791/4792/4783 (production data only on 110 prod)
    if ENV == "134":
        print("  [SKIP] 134 dev drill DB, skip wf detail regression (wf#4791/4792/4783 on 110 prod)")
        print("=" * 60)
        print("  regression: SKIP (134 dev)")
        print("=" * 60)
        return True
    old_wfs = [
        ("wf#4791", 4791, "pure ALTER (9/9 字段 diff drill)"),
        ("wf#4792", 4792, "pure ALTER mirror (DDL-Sync drill)"),
        ("wf#4783", 4783, "pure ALTER old (字段 diff drill)"),
    ]
    if ENV == "110":
        old_wfs.append(("wf#4848", 4848, "pure CREATE (DBA-bug-9.5b drill, enable_gh_ost=False)"))
        old_wfs.append(("wf#4841", 4841, "mixed ALTER+CREATE (DBA-bug-9 drill)"))
    all_pass = True
    for name, wid, desc in old_wfs:
        r = c.get("/detail/" + str(wid) + "/")
        if r.status_code == 200:
            print("  [" + name + "] OK status=200 (" + desc + ")")
        else:
            print("  [" + name + "] FAIL status=" + str(r.status_code) + " (" + desc + ")")
            all_pass = False
    print("=" * 60)
    print("  regression: " + ("PASS" if all_pass else "FAIL"))
    print("=" * 60)
    return all_pass


def main():
    c = Client(SERVER_NAME="127.0.0.1")
    try:
        u = User.objects.get(username="archery")
        c.force_login(u, backend="django.contrib.auth.backends.ModelBackend")
    except Exception as e:
        print("force_login err: " + str(e))
        return

    r1 = run_check_non_alter_drill(c)
    r2 = run_sqlsubmit_html_drill(c)
    r3 = run_old_workflow_regression(c)
    if r1 and r2 and r3:
        print("\nALL PASS")
    else:
        print("\nFAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
