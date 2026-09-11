"""
DBA-bug-3 hotfix: 拿 110 prod /submitsql/ 实际渲染 HTML, 看 {# 是不是没被 Django 移除
@ 2026-09-11 @ mavis
"""
import urllib.request
import urllib.parse
import http.cookiejar
import re
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://prodarchery.ahggwl.com:9123"
USER = "archery"
PWD = "archery123"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# 登录
r = opener.open(f"{BASE}/login/")
html = r.read().decode("utf-8", errors="replace")
csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html).group(1)
data = urllib.parse.urlencode({"csrfmiddlewaretoken": csrf, "username": USER, "password": PWD}).encode()
opener.open(urllib.request.Request(
    f"{BASE}/authenticate/",
    data=data,
    headers={"Referer": f"{BASE}/login/", "Content-Type": "application/x-www-form-urlencoded"},
))
print("[1/2] 登录成功")

# 访问 /submitsql/ 拿渲染后 HTML
r = opener.open(f"{BASE}/submitsql/")
detail = r.read().decode("utf-8", errors="replace")
print(f"[2/2] HTML size: {len(detail)} bytes")

# 检查 {# 是否在输出里 (Django 应该移除, 移除表示没 bug; 保留表示有 bug)
count = detail.count("{#")
print(f"  DOUBLE_HASH_OPEN 出现次数: {count} (Django 应该移除, > 0 表示有 bug)")
if count > 0:
    # 找出 {# 位置
    for m in re.finditer(r'\{#', detail):
        line_num = detail[:m.start()].count("\n") + 1
        # 找 {# 之前和之后的 50 字符, 精确判断在 JS 可执行代码里还是 JS 注释里
        before = detail[max(0, m.start()-30):m.start()]
        snippet = detail[m.start():m.start()+500]
        # 检查前面是否有 // 单行注释开始
        # 找最近一个换行符,看换行后到 {# 之间的字符
        nl_pos = detail.rfind("\n", 0, m.start())
        if nl_pos == -1:
            line_start = 0
        else:
            line_start = nl_pos + 1
        line_before = detail[line_start:m.start()]
        is_in_js_comment = "//" in line_before
        print(f"  line ~{line_num}: in_js_comment={is_in_js_comment}  before={line_before!r}")
        end_m = re.search(r'#\}', snippet)
        if end_m:
            print(f"    -> HASH_CLOSE 在 snippet 内 OK")
        else:
            print(f"    -> HASH_CLOSE 不在 snippet 内, 注释未闭合!")

# 检查 function renderBigTableAlertOnly 出现
count_func = detail.count("function renderBigTableAlertOnly")
print(f"  renderBigTableAlertOnly 出现: {count_func}")

# 检查 fetchColumnDiff 出现
count_fetch = detail.count("function fetchColumnDiff")
print(f"  fetchColumnDiff 出现: {count_fetch}")
