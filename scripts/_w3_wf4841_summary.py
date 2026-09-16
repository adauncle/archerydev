"""拿 wf#4841 完整 SQL 摘要 (CREATE/ALTER/USE 各多少条)"""
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
wf = SqlWorkflow.objects.get(id=wf_id)
c = SqlWorkflowContent.objects.get(workflow=wf)
sql_content = c.sql_content or ""
print(f"=== wf#{wf_id} summary ===")
print(f"engineer: {wf.engineer}")
print(f"db_name: {wf.db_name}")
print(f"status: {wf.status}")
print()

parsed = _parse_all_statements(sql_content)
print(f"Total statements: {len(parsed)}")
print()
# 每条类型 + 表名 + 前 200 字符
for idx, s in enumerate(parsed):
    print(f"=== [{idx}] type={s['stmt_type']} db={s['db']} table={s['table']} ===")
    print(s["full"][:200])
    print("..." if len(s["full"]) > 200 else "")
    print()

# 统计
from collections import Counter
type_counts = Counter(s["stmt_type"] for s in parsed)
print("=== Type counts ===")
for t, c in type_counts.most_common():
    print(f"  {t}: {c}")