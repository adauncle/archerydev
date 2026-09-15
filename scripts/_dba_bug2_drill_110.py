"""
DBA-bug-2 110 prod 端点 /gh_ost/column_diff/ 演练
@ 2026-09-11 @ mavis
模拟业务方 SQL, 看端点返什么
"""
import urllib.request
import urllib.parse
import http.cookiejar
import re
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://prodarchery.ahggwl.com:9123"
USER = "archery"
PWD = "archery123"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# 1. 登录
r = opener.open(f"{BASE}/login/")
html = r.read().decode("utf-8", errors="replace")
csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html).group(1)
data = urllib.parse.urlencode({"csrfmiddlewaretoken": csrf, "username": USER, "password": PWD}).encode()
opener.open(urllib.request.Request(
    f"{BASE}/authenticate/",
    data=data,
    headers={"Referer": f"{BASE}/login/", "Content-Type": "application/x-www-form-urlencoded"},
))
print("[1/3] 登录成功")

# 访问 submitsql 拿新 CSRF + session
r = opener.open(f"{BASE}/submitsql/")
sub_html = r.read().decode("utf-8", errors="replace")
csrf_match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', sub_html)
if csrf_match:
    csrf = csrf_match.group(1)
print(f"  csrftoken: {csrf[:20] if csrf else 'NONE'}...")

# 2. 找 prod core for etc 变更实例 id (用 hly_billing.consume_flow 测试)
# 通过 admin instance 列表 API: /api/v1/instance/ 或 /admin/sql/instance/ 等
# 试一下 Archery admin 路径
instances = []
for iid in [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]:
    sql_test = "ALTER TABLE `hly_billing`.`consume_flow` ADD INDEX idx_x (id)"
    data_post = urllib.parse.urlencode({
        "instance_id": iid, "db_name": "hly_billing", "sql_content": sql_test,
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/gh_ost/column_diff/",
        data=data_post,
        headers={"Referer": f"{BASE}/submitsql/", "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrf},
    )
    try:
        r = opener.open(req)
        body = r.read().decode("utf-8", errors="replace")
        if "ok" in body and '"ok": true' in body:
            print(f"  instance_id={iid} 找到了 (ok=true)")
            instances.append(iid)
            break
        else:
            print(f"  instance_id={iid} body: {body[:200]}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  instance_id={iid} HTTP {e.code}: {e.read().decode()[:200]}")
        continue

if not instances:
    print("[WARN] 没找到 instance_id (4-20)")
    sys.exit(1)

# 3. 用找到的 instance_id 测阿达叔叔的 2 个 SQL
print(f"\n[2/3] 用 instance_id={instances[0]} 测试 SQL")

SQLS = [
    # 业务方真实场景: 工单库是 hly_accesscard, SQL 跨库改 hly_billing.consume_flow
    ("业务方真实 (库=hly_accesscard, SQL 改 hly_billing.consume_flow)", "ALTER TABLE `hly_billing`.`consume_flow` ADD INDEX `idx_create_time` (`create_time`)"),
    ("业务方真实 (库=hly_accesscard, DROP INDEX)", "ALTER TABLE `hly_billing`.`consume_flow` DROP INDEX `idx_create_time`"),
    # 跨库真实场景: 库名是 SELECT 的库, 不是 DDL 改的库
    ("库=hly_billing, ADD INDEX (对照)", "ALTER TABLE `hly_billing`.`consume_flow` ADD INDEX `idx_create_time` (`create_time`)"),
]

for name, sql in SQLS:
    print(f"\n--- {name} ---")
    print(f"SQL: {sql[:120]!r}")
    # 业务方真实场景: 库=hly_accesscard (从 select 选), SQL 跨库改 hly_billing
    data_post = urllib.parse.urlencode({
        "instance_id": instances[0], "db_name": "hly_accesscard", "sql_content": sql,
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/gh_ost/column_diff/",
        data=data_post,
        headers={"Referer": f"{BASE}/submitsql/", "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrf},
    )
    r = opener.open(req)
    body = r.read().decode("utf-8", errors="replace")
    try:
        j = json.loads(body)
        print(f"  ok={j.get('ok')}")
        print(f"  table_name={j.get('table_name')!r}")
        print(f"  big_table_alert={j.get('big_table_alert')}")
        print(f"  high_risk_count={j.get('high_risk_count')}")
        print(f"  mid_risk_count={j.get('mid_risk_count')}")
        print(f"  low_risk_count={j.get('low_risk_count')}")
        print(f"  summary={j.get('summary')!r}")
        if "tables" in j:
            for t in j["tables"]:
                print(f"    table={t.get('table_name')!r} columns={len(t.get('columns', []))} big_table_alert={t.get('big_table_alert')}")
                for c in t.get("columns", [])[:3]:
                    print(f"      col: name={c.get('name')!r} op={c.get('operation')!r} diffs={len(c.get('diffs', []))}")
        print(f"  keys: {list(j.keys())[:20]}")
    except Exception as e:
        print(f"  JSON parse fail: {e}")
        print(f"  body[:300]: {body[:300]}")
