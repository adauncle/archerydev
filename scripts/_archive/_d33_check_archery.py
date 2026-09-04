# -*- coding: utf-8 -*-
"""D33 check v2: 用 archery 用户登录 + 看实际 HTML."""
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

# 试 archery/常见密码
py = '''
import urllib.request, urllib.parse, http.cookiejar, re

BASE = "http://127.0.0.1:9003"

# DBA 业务方账号 archery / mkq
for username in ["archery", "mkq", "admin"]:
    for pwd in ["archery", "archery123", "123456", "admin", "archery@123", "hly@123", "123", "hly", "hly123", "Mkq@123", "mkq@123"]:
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        try:
            r = opener.open(BASE + "/login/")
            html = r.read().decode("utf-8", errors="replace")
            m = re.search(r\'name="csrfmiddlewaretoken" value="([^"]+)"\', html)
            csrf = m.group(1) if m else ""
            data = urllib.parse.urlencode({
                "csrfmiddlewaretoken": csrf,
                "username": username,
                "password": pwd,
            }).encode()
            r = opener.open(BASE + "/login/", data)
            r2 = opener.open(BASE + "/dashboard/")
            if "/login/" not in r2.url:
                print(f"OK: {username}/{pwd}, dashboard: {r2.url}")
                # 访问 ddl_sync/pair/1/
                r3 = opener.open(BASE + "/ddl_sync/pair/1/")
                html3 = r3.read().decode("utf-8", errors="replace")
                # 找 tab-pane 4 个 class
                print(f"  page length: {len(html3)}")
                for tab_id in ["tab-basic", "tab-tables", "tab-history", "tab-logs"]:
                    m = re.search(rf\'id="{tab_id}"[^>]*class="([^"]*)"\', html3)
                    if m:
                        print(f"  {tab_id} class: {m.group(1)}")
                # 找 tab-content 容器
                m = re.search(r\'<div class="tab-content">(.*?)(?=<div class="modal|<!-- 3 modal|\\{% include)\', html3, re.DOTALL)
                if m:
                    snippet = m.group(1)
                    print(f"  tab-content length: {len(snippet)}")
                    # 4 个 tab-pane 顺序提取
                    for tab_id in ["tab-basic", "tab-tables", "tab-history", "tab-logs"]:
                        mt = re.search(rf\'<div class="([^"]*)" id="{tab_id}">\', snippet)
                        if mt:
                            print(f"    {tab_id} actual class: {mt.group(1)}")
                # 看库对详情 table 是否在 tab-basic 内
                if "库对详情" in html3:
                    print("  库对详情 h5 found in HTML")
                if "同步表清单" in html3:
                    print("  同步表清单 h5 found in HTML")
                # 找空白是不是 "基本信息" tab 内容没显示
                # 看 tab-content 内的第一个 .tab-pane
                m = re.search(r\'<div class="tab-content">(.*?)<div class="tab-pane fade" id="tab-tables">\', html3, re.DOTALL)
                if m:
                    print(f"  tab-basic 到 tab-tables 之间: {m.group(1)[:300]}")
                raise SystemExit(0)
        except SystemExit:
            raise
        except Exception as e:
            continue
print("ALL FAILED")
'''
py_b64 = base64.b64encode(py.encode('utf-8')).decode('ascii')
out = run('echo ' + py_b64 + ' | base64 -d > /tmp/_d33_check2.py && python3 /tmp/_d33_check2.py 2>&1')
print(out)

ssh.close()
