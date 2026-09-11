"""
精确验证 110 prod 渲染后 HTML 是否还有未移除的 {# 注释
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

r = opener.open(f"{BASE}/submitsql/")
detail = r.read().decode("utf-8", errors="replace")
print(f"[2/2] HTML size: {len(detail)} bytes")

# 找所有 {# 出现位置, 精确判断是不是真在 JS 可执行代码里
print()
print("=== 精确检查 {# 出现位置 ===")
for m in re.finditer(r'\{#', detail):
    line_num = detail[:m.start()].count("\n") + 1
    # 找当前行开头
    nl_pos = detail.rfind("\n", 0, m.start())
    if nl_pos == -1:
        line_start = 0
    else:
        line_start = nl_pos + 1
    line_before = detail[line_start:m.start()]
    is_in_js_comment = "//" in line_before
    # 看 line_before 是不是在 <script> 内
    # 简化: 数一下 <script> 和 </script> 数量
    before_m = detail[:m.start()]
    script_open = before_m.count("<script")
    script_close = before_m.count("</script>")
    in_script = script_open > script_close
    print(f"  line {line_num}: in_script={in_script}  in_js_comment={is_in_js_comment}")
    print(f"    line before: {line_before!r}")
    if not is_in_js_comment and in_script:
        # 真在 JS 可执行代码里!
        print(f"    [BUG!] 真在 JS 代码里, 会报 SyntaxError!")

# 检查 renderBigTableAlertOnly 函数的实际内容
print()
print("=== renderBigTableAlertOnly 函数定义 (line 700-720 估计) ===")
m = re.search(r"function renderBigTableAlertOnly\(bta\) \{[\s\S]{0,500}", detail)
if m:
    print(f"  found at offset {m.start()}")
    print(f"  content: {m.group(0)[:300]!r}")
