"""看 wf#4841 的 gh-ost task #26 实际处理了哪一条 ALTER"""
import os
import sys

sys.path.insert(0, "/dbdata/archery_v114_c9236a0")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django  # noqa: E402

django.setup()

from sql.extensions.ddl_gh_ost.models import DdlGhostTask  # noqa: E402


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

t = DdlGhostTask.objects.get(id=26)
print(f"task #{t.id}")
print(f"workflow: {t.workflow_id}")
print(f"db: {t.db_name}")
print(f"table: {t.table_name}")
print(f"statement_index: {t.statement_index}")
print(f"alter_statement (前 500):")
print(t.alter_statement[:500])
print()
print(f"status: {t.status}")
print(f"started: {t.started_at}")
print(f"finished: {t.finished_at}")
print(f"progress_pct: {t.progress_pct}")
print(f"rows: {t.progress_rows_copied}/{t.progress_rows_total}")