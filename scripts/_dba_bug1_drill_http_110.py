"""
DBA-bug-1 110 prod 真 HTTP 演练 v2: wf#4803 (drop index, 169660 行)
跑在 Windows 本地, 访问 110 prod prodarchery.ahggwl.com:9123
@ 2026-09-11 @ mavis
"""
import urllib.request
import urllib.parse
import http.cookiejar
import re
import sys
import io

# Force UTF-8 stdout (避免 Windows GBK 编码问题)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://prodarchery.ahggwl.com:9123"
USER = "archery"
PWD = "archery123"  # 9/11 16:50 reset OK

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# 1. GET /login/
print("=== [1/4] GET /login/ ===")
r = opener.open(f"{BASE}/login/")
html = r.read().decode("utf-8", errors="replace")
m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
csrf = m.group(1) if m else ""
print(f"  CSRF: {csrf[:20]}...")

# 2. POST /authenticate/
print("\n=== [2/4] POST /authenticate/ ===")
data = urllib.parse.urlencode({
    "csrfmiddlewaretoken": csrf,
    "username": USER,
    "password": PWD,
}).encode()
req = urllib.request.Request(
    f"{BASE}/authenticate/",
    data=data,
    headers={"Referer": f"{BASE}/login/", "Content-Type": "application/x-www-form-urlencoded"},
)
r = opener.open(req)
print(f"  login status: {r.status}")

# 3. GET /detail/4803/
print("\n=== [3/4] GET /detail/4803/ ===")
r = opener.open(f"{BASE}/detail/4803/")
print(f"  url: {r.url}, status: {r.status}")
detail_bytes = r.read()
print(f"  size: {len(detail_bytes)} bytes")
with open(r"G:\MiniMax工作空间\archery_dev\wf4803_110_detail.html", "wb") as f:
    f.write(detail_bytes)
detail = detail_bytes.decode("utf-8", errors="replace")
print(f"  saved to wf4803_110_detail.html")

# 4. 验证大表 alert
print("\n=== [4/4] 验证大表 alert 关键元素 ===")
m = re.search(r'workflow_detail_disaply">([^<]+)', detail)
status_display = m.group(1) if m else "(none)"
print(f"  status display: {status_display}")

alert_count = detail.count('id="big-table-alert"')
print(f"  big-table-alert div count: {alert_count}")

# 找 waybill_union_carrier (大表名)
m = re.search(r'<code>(waybill_union_carrier)</code>', detail)
if m:
    print(f"  [OK] 找到 waybill_union_carrier 大表名: {m.group(1)}")
else:
    print(f"  [FAIL] 未找到 waybill_union_carrier 大表名")
    sys.exit(1)

# 找 "是大表 DDL" 字符串
if "是大表 DDL" in detail:
    print(f"  [OK] 找到 '是大表 DDL' 字符串")
else:
    print(f"  [FAIL] 未找到 '是大表 DDL' 字符串")
    sys.exit(1)

# 找行数
m = re.search(r'行数 <strong>(\d+)</strong> / 数据大小 <strong>([\d.]+) MB</strong>', detail)
if m:
    print(f"  [OK] 行数 {m.group(1)} / 数据大小 {m.group(2)} MB")

# alert 在 btnPass 前
alert_line = detail.find('id="big-table-alert"')
btnpass_line = detail.find('id="btnPass"')
print(f"  big-table-alert pos: {alert_line}, btnPass pos: {btnpass_line}")
if alert_line > 0 and btnpass_line > 0 and alert_line < btnpass_line:
    print(f"  [OK] alert 在 btnPass 前面 ✓")
elif alert_line > 0 and btnpass_line < 0:
    print(f"  [OK] alert 在前面, 当前用户无审批权限 (无 btnPass 按钮)")
elif alert_line > 0 and alert_line < btnpass_line:
    print(f"  [OK] alert 在 btnPass 前面")
else:
    print(f"  [WARN] alert/btnPass 位置关系未确认")

# wf#4803 状态判断
print(f"\n=== 结论: wf#4803 详情页大表 alert 渲染情况 ===")
if "waybill_union_carrier" in detail and "是大表 DDL" in detail:
    print(f"  [OK] wf#4803 现在能看到大表 DDL 提示 ✓ (DBA-bug-1 修法生效)")
else:
    print(f"  [FAIL] wf#4803 仍然看不到大表 DDL 提示 ✗")
    sys.exit(1)
