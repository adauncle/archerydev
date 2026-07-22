"""通过 HTTP API 模拟前端 SQL检测 验证整条链路。"""
import http.cookiejar
import json
import urllib.request
import urllib.parse

BASE = "http://127.0.0.1:9003"

# 建 cookie jar
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# 1) GET /login/ 拿 CSRF
r = opener.open(f"{BASE}/login/")
csrf = None
for c in cj:
    if c.name == "csrftoken":
        csrf = c.value
        break
print(f"CSRF: {csrf!r}")

# 2) POST /auth/login/
data = urllib.parse.urlencode({
    "csrfmiddlewaretoken": csrf,
    "username": "archery",
    "password": "archery",
}).encode()
req = urllib.request.Request(f"{BASE}/auth/login/", data=data, method="POST")
req.add_header("Referer", f"{BASE}/login/")
try:
    r = opener.open(req)
    print(f"login: {r.status} {r.url}")
except urllib.error.HTTPError as e:
    print(f"login: {e.code} {e.url}")

# 3) POST /api/v1/workflow/sqlcheck/
sql = "CREATE TABLE `test` (id bigint NOT NULL, PRIMARY KEY (id)) ENGINE=InnoDB"
payload = json.dumps({
    "instance_id": 2,
    "db_name": "archery_dev",
    "full_sql": sql,
}).encode()
req = urllib.request.Request(
    f"{BASE}/api/v1/workflow/sqlcheck/",
    data=payload, method="POST",
)
req.add_header("Content-Type", "application/json")
req.add_header("Referer", f"{BASE}/submitsql/")
req.add_header("X-CSRFToken", csrf)
try:
    r = opener.open(req)
    body = r.read().decode()
    print(f"sqlcheck: {r.status}")
    obj = json.loads(body)
    if "checked" in obj:
        print(f"  ✓ 拿到 {len(obj['checked'])} 条检测结果")
        for row in obj["checked"][:5]:
            print(f"    {row}")
    else:
        print(f"  响应 keys: {list(obj.keys())}")
        print(f"  响应: {json.dumps(obj, ensure_ascii=False)[:500]}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"sqlcheck: HTTP {e.code}")
    print(f"  body: {body[:500]}")
