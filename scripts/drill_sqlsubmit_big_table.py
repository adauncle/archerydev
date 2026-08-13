"""drill_sqlsubmit_big_table.py

业务: 8/13 用户反馈, 开发点 gh-ost 走流程, 到 DBA 执行阶段才提示大表 DDL。
     期望: SQL 提交页开发点"SQL检测"时就该看到大表 DDL 警告。

修法:
  1. 端点 /gh_ost/column_diff/ 返回加 big_table_alert 字段 (查 information_schema.tables 行数+大小, 跟阈值比)
  2. sqlsubmit.html renderColumnDiff 函数渲染大表 DDL 提示 (放字段 diff 上面)

演练 (134 dev 真实 MySQL, 3 Case):
  A. 大表 (accesscard_black_detail 28w 行 / 134 MB, 阈值 100k/100MB)
     → big_table_alert = dict (有 rows, size_mb, table_name)
  B. 小表 (accesscard_test_diff 5 行)
     → big_table_alert = None
  C. 不存在的表 (e.g. accesscard_no_such_table)
     → 端点应该返 ok=False 或 big_table_alert=None (字段 diff 也走 fallback)
"""
import os
import sys
import django

sys.path.insert(0, '/opt/archery/prod')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archery.settings')
django.setup()

from django.conf import settings as dj_settings
if 'testserver' not in dj_settings.ALLOWED_HOSTS:
    dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver', '127.0.0.1']

from django.test import Client
from sql.models import Users as User
from sql.extensions.ddl_gh_ost.services.column_diff import column_diff_full, _fetch_table_size, _build_big_table_alert


def login(client, user):
    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")


def header(title):
    print(f"\n{'='*60}\n{title}\n{'='*60}")


# === 准备: 134 dev 真实 instance + db + user ===
header("准备: 134 dev 真实数据")
from sql.models import Instance
instance = Instance.objects.get(pk=2)  # 测试 MySQL 8.0
print(f"  instance: id={instance.id} name={instance.instance_name} host={instance.host}:{instance.port}")
db_name = "archery_dev"
u = User.objects.get(username="archery")

# === 直接调 service 函数 (不走 HTTP) 验证逻辑 ===
header("Case A: 大表 (accesscard_black_detail)")
size_info = _fetch_table_size(instance, db_name, "accesscard_black_detail")
print(f"  size_info: {size_info}")
alert = _build_big_table_alert(size_info)
print(f"  big_table_alert: {alert}")
assert size_info is not None, "大表 size_info 应该是 dict"
assert size_info["rows"] > 100000, f"期望 rows > 100000, 实际 {size_info['rows']}"
assert size_info["size_mb"] > 100, f"期望 size_mb > 100, 实际 {size_info['size_mb']}"
assert alert is not None, "大表应该触发 alert"
assert alert["rows"] == size_info["rows"]
assert alert["size_mb"] == size_info["size_mb"]
assert alert["row_threshold"] == 100000
assert alert["size_threshold_mb"] == 100
print(f"  [PASS] 大表 alert 触发, rows={alert['rows']}, size={alert['size_mb']}MB ✓")

header("Case B: 小表 (accesscard_test_diff)")
size_info = _fetch_table_size(instance, db_name, "accesscard_test_diff")
print(f"  size_info: {size_info}")
alert = _build_big_table_alert(size_info)
print(f"  big_table_alert: {alert}")
assert size_info is not None, "小表 size_info 应该是 dict"
assert size_info["rows"] < 1000, f"期望 rows < 1000, 实际 {size_info['rows']}"
assert alert is None, f"小表不应触发 alert, 实际 {alert}"
print(f"  [PASS] 小表 alert 不触发 ✓")

header("Case C: 端点集成 (column_diff_full 大表场景)")
sql = "ALTER TABLE accesscard_black_detail MODIFY COLUMN operator_id BIGINT NOT NULL DEFAULT 0"
result = column_diff_full(instance, db_name, sql)
print(f"  result.ok: {result['ok']}")
print(f"  result.big_table_alert: {result.get('big_table_alert')}")
assert result["ok"] is True
assert result.get("big_table_alert") is not None, "column_diff_full 大表场景应返回 big_table_alert"
assert result["big_table_alert"]["table_name"] == "accesscard_black_detail"
print(f"  [PASS] 端点集成: 大表 alert 正确返回 ✓")

header("Case D: 端点集成 (column_diff_full 小表场景)")
sql = "ALTER TABLE accesscard_test_diff MODIFY COLUMN name VARCHAR(100)"
result = column_diff_full(instance, db_name, sql)
print(f"  result.ok: {result['ok']}")
print(f"  result.big_table_alert: {result.get('big_table_alert')}")
assert result["ok"] is True
assert result.get("big_table_alert") is None, "column_diff_full 小表场景应返回 big_table_alert=None"
print(f"  [PASS] 端点集成: 小表 alert 不返回 ✓")

header("Case E: 端点 HTTP (POST /gh_ost/column_diff/)")
c = Client(SERVER_NAME="127.0.0.1")
login(c, u)
r = c.post("/gh_ost/column_diff/", data={
    "instance_id": instance.id,
    "db_name": db_name,
    "sql_content": "ALTER TABLE accesscard_black_detail MODIFY COLUMN operator_id BIGINT NOT NULL DEFAULT 0",
})
print(f"  status={r.status_code}")
data = r.json()
print(f"  body.ok: {data.get('ok')}")
print(f"  body.big_table_alert: {data.get('big_table_alert')}")
assert r.status_code == 200
assert data.get("ok") is True
assert data.get("big_table_alert") is not None
assert data["big_table_alert"]["table_name"] == "accesscard_black_detail"
print(f"  [PASS] HTTP 端点: 大表 alert 正确返回 ✓")

# === sqlsubmit.html 渲染验证 (直接 grep 模板内容) ===
header("Case F: sqlsubmit.html 渲染逻辑 (大表 alert HTML)")
fp = "/opt/archery/prod/sql/templates/sqlsubmit.html"
with open(fp) as f:
    content = f.read()
checks = [
    ("big_table_alert 字段读取", "data.big_table_alert" in content),
    ("大表 DDL 提示文案", "是大表 DDL" in content),
    ("强烈建议勾选 gh-ost 提示", "强烈建议在上方勾选" in content),
    ("大表 alert div", "sqlsubmit-big-table-alert" in content),
    ("拼接到 html 变量", "bigTableAlertHtml +" in content),
]
for name, ok in checks:
    print(f"  [{'OK' if ok else 'MISS'}] {name}")
    assert ok, f"缺: {name}"
print(f"  [PASS] 模板渲染逻辑完整 ✓")

print(f"\n{'='*60}\n[ALL OK] 6 Case 演练完成\n{'='*60}")
