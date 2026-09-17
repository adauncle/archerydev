"""DBA-bug-10 端点演练: column_diff 端点对 CREATE INDEX 返 big_table_alert

@ 2026-09-17 @ mavis
"""
import sys
import os
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()

from sql.models import Instance
from sql.extensions.ddl_gh_ost.services.column_diff import column_diff_full

# 找第一个能连通的 instance
print("=== Available instances ===")
for inst in Instance.objects.all()[:5]:
    print(f"  id={inst.id} host={inst.host}:{inst.port}")
inst = Instance.objects.exclude(host="").first()
print(f"Using instance id={inst.id} host={inst.host}:{inst.port}")
sql = "CREATE INDEX test USING BTREE ON hly_accesscard.accesscard_channel_task (req_url);"
result = column_diff_full(inst, "hly_accesscard", sql)
print("=== column_diff_full CREATE INDEX 实战 ===")
# 调试: 直接试 pymysql 连
import pymysql
user, password = inst.get_username_password()
print(f"=== DEBUG 直连 instance {inst.id} {inst.host}:{inst.port} ===")
print(f"user={user} password={'*' * len(password)}")
try:
    conn = pymysql.connect(
        host=inst.host, port=inst.port, user=user, password=password,
        connect_timeout=5, autocommit=True,
    )
    with conn.cursor() as cur:
        cur.execute("SELECT TABLE_ROWS, DATA_LENGTH FROM information_schema.tables WHERE TABLE_SCHEMA='hly_accesscard' AND TABLE_NAME='accesscard_channel_task'")
        row = cur.fetchone()
        print(f"row={row}")
    conn.close()
except Exception as e:
    print(f"connect FAIL: {e}")
import json
print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

# 调试: 直接查 accesscard_channel_task 的 size
from sql.extensions.ddl_gh_ost.services.column_diff import _fetch_table_size, _build_big_table_alert
size_info = _fetch_table_size(inst, "hly_accesscard", "accesscard_channel_task")
print()
print("=== DEBUG size_info ===")
print(json.dumps(size_info, ensure_ascii=False, indent=2, default=str))
print()
print(f"big_table_alert: {_build_big_table_alert(size_info)}")

# 验证 big_table_alert 包含
assert result.get("big_table_alert") is not None, "big_table_alert 应该触发"
assert result["big_table_alert"]["table_name"] == "accesscard_channel_task", "table_name 应为 accesscard_channel_task"
print()
print("✅ big_table_alert 触发:")
print(f"   table={result['big_table_alert']['table_name']}")
print(f"   rows={result['big_table_alert'].get('rows')}")
print(f"   size_mb={result['big_table_alert'].get('size_mb')}")
print(f"   threshold={result['big_table_alert'].get('threshold_rows')}/{result['big_table_alert'].get('threshold_mb')}")