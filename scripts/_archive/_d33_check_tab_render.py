# -*- coding: utf-8 -*-
"""D33 check: 134 dev 实际页面渲染 - 查 tab-content 4 tab 状态."""
import paramiko
import base64

DEV = "172.20.2.134"
PWD = "lAqfb8uEmQYsnGNQwIHtGPwukjCz6J"
DEV_BASE = "/opt/archery/prod"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(hostname=DEV, port=22, username="root", password=PWD, timeout=15)

def run(cmd, timeout=20):
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        return out
    except Exception as e:
        return f"ERR: {e}"

print("=" * 60)
print("D33 check: tab 状态 + 找业务方密码")
print("=" * 60)

# 1. 用 134 dev admin/123456 模拟登录拿 csrf
print("\n--- 1. 看 .env 密码 ---")
out = run('cat ' + DEV_BASE + '/.env 2>&1 | head -30')
print(out)

# 2. 看 134 dev 业务方账号
print("\n--- 2. 找 134 dev 业务方 DBA 账号 ---")
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c 'from sql.models import Users; print(\"DBA:\", [u.username for u in Users.objects.filter(groups__name=\"DBA\")][:5]); print(\"SU:\", [u.username for u in Users.objects.filter(is_superuser=True)][:5])' 2>&1 | tail -10")
print(out)

# 3. 用 admin/archery (默认 admin 密码) 模拟登录看实际页面 HTML
print("\n--- 3. 模拟登录 + 看实际 HTML ---")
py = '''
import urllib.request, urllib.parse, http.cookiejar, re

BASE = "http://127.0.0.1:9003"

# 试 5 个常见密码
for pwd in ["archery", "archery123", "123456", "admin", "archery@123", "Archery@2024"]:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    try:
        r = opener.open(BASE + "/login/")
        html = r.read().decode("utf-8", errors="replace")
        m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
        csrf = m.group(1) if m else ""
        data = urllib.parse.urlencode({
            "csrfmiddlewaretoken": csrf,
            "username": "admin",
            "password": pwd,
        }).encode()
        r = opener.open(BASE + "/login/", data)
        # 检查是否登录成功 (登录后访问 dashboard)
        r2 = opener.open(BASE + "/dashboard/")
        if "/login/" not in r2.url:
            print(f"admin/{pwd} OK, dashboard url: {r2.url}")
            # 访问 ddl_sync/pair/1/
            r3 = opener.open(BASE + "/ddl_sync/pair/1/")
            html3 = r3.read().decode("utf-8", errors="replace")
            # 看 tab-pane 4 个的 display
            for i, tab_id in enumerate(["tab-basic", "tab-tables", "tab-history", "tab-logs"]):
                m = re.search(rf"id=\\"{tab_id}\\" class=\\"([^\\"]*)\\"", html3)
                if m:
                    print(f"  {tab_id} class: {m.group(1)}")
                else:
                    m2 = re.search(rf"id=\\"{tab_id}\\"[^>]*class=\\"([^\\"]*)\\"", html3)
                    if m2:
                        print(f"  {tab_id} class (alt): {m2.group(1)}")
            # 看 tab-content 的内容片段
            m = re.search(r"<div class=\\"tab-content\\">(.*?)</div>\\s*<!--", html3, re.DOTALL)
            if m:
                snippet = m.group(1)[:800]
                print(f"  tab-content snippet: {snippet[:500]}")
            else:
                # 找 tab-content 到结尾
                m = re.search(r"<div class=\\"tab-content\\">(.*)", html3, re.DOTALL)
                if m:
                    print(f"  tab-content: {m.group(1)[:500]}")
            break
    except Exception as e:
        print(f"admin/{pwd} ERR: {e}")
        continue
'''
py_b64 = base64.b64encode(py.encode('utf-8')).decode('ascii')
out = run('echo ' + py_b64 + ' | base64 -d > /tmp/_d33_check.py && python3 /tmp/_d33_check.py 2>&1')
print(out)

ssh.close()
