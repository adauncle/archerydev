"""临时脚本: 拿 wf#4841 的 sql_content + 解析 CREATE 语句"""
"""
Wf#4841 业务方实测拿不到的 CREATE TABLE 语句, 让他 review 后决定补建
@ 2026-09-16 @ mavis
"""
import os
import sys

sys.path.insert(0, "/dbdata/archery_v114_c9236a0")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django  # noqa: E402

django.setup()

from sql.models import SqlWorkflow, SqlWorkflowContent  # noqa: E402
from sql.extensions.ddl_gh_ost.views import _parse_all_statements  # noqa: E402


def load_env(env_path):
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


load_env("/dbdata/archery_v114_c9236a0/.env")

wf_id = 4841
try:
    wf = SqlWorkflow.objects.get(id=wf_id)
    c = SqlWorkflowContent.objects.get(workflow=wf)
    sql_content = c.sql_content or ""
    print(f"=== wf#{wf_id} ===")
    print(f"engineer: {wf.engineer}")
    print(f"db_name: {wf.db_name}")
    print(f"instance: {wf.instance.instance_name if wf.instance else 'N/A'}")
    print(f"status: {wf.status}")
    print(f"finish_time: {wf.finish_time}")
    print()
    print("=== SQL CONTENT (raw) ===")
    print(sql_content)
    print()
    print("=== PARSED STATEMENTS ===")
    parsed = _parse_all_statements(sql_content)
    for idx, s in enumerate(parsed):
        print(f"  [{idx}] type={s['stmt_type']} db={s['db']} table={s['table']}")
        print(f"      full (first 200 chars): {s['full'][:200]}")
    print()
    print("=== CREATE / 非 ALTER 语句 (供业务方 review) ===")
    non_alter = [s for s in parsed if s["stmt_type"] != "ALTER"]
    if non_alter:
        for s in non_alter:
            print(f"--- {s['stmt_type']} ---")
            print(s["full"])
            print()
    else:
        print("(无)")
except SqlWorkflow.DoesNotExist:
    print(f"wf#{wf_id} 不存在")