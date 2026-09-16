"""拿 wf#4841 完整 SQL (8 条全部) 写到文件供业务方 review"""
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

# 写到 /tmp/wf4841_full.sql
output_path = "/tmp/wf4841_full.sql"
with open(output_path, "w") as f:
    f.write(f"-- wf#{wf_id} full SQL\n")
    f.write(f"-- engineer: {wf.engineer}\n")
    f.write(f"-- db_name: {wf.db_name}\n")
    f.write(f"-- status: {wf.status}\n")
    f.write(f"-- finish_time: {wf.finish_time}\n")
    f.write("--\n")
    f.write("-- 业务方实测 wf#4841 实际包含 8 条 SQL:\n")
    f.write("--   [0] CREATE TABLE vehicle_risk_hit\n")
    f.write("--   [1] CREATE TABLE vehicle_risk_hit_detail\n")
    f.write("--   [2] CREATE TABLE risk_rule_set\n")
    f.write("--   [3] CREATE TABLE risk_rule_operation_log\n")
    f.write("--   [4] ALTER TABLE accesscard_licensefront_info ADD owner_name ...  ← gh-ost 实际处理 (statement_index=0)\n")
    f.write("--   [5] ALTER TABLE vehicle_info_verify ADD data_source ...\n")
    f.write("--   [6] ALTER TABLE accesscard_vehicle_review ADD risk_level ...\n")
    f.write("--   [7] ALTER TABLE accesscard_opendcardapply ADD 3 columns ...\n")
    f.write("--\n")
    f.write("-- gh-ost 只处理 statement_index=0 那一条 (切流 481463/481463 行成功)\n")
    f.write("-- 其余 7 条 (4 CREATE + 3 ALTER) 没执行, 工单状态显示 '已正常结束'\n")
    f.write("-- 业务方需要 review 下面 8 条 SQL, 自己决定哪些要补建/补执行\n")
    f.write("---\n\n")
    f.write(sql_content)
print(f"Written to {output_path}")
print(f"File size: {os.path.getsize(output_path)} bytes")