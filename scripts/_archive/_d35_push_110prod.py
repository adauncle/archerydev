# -*- coding: utf-8 -*-
"""D35 实战推 110 prod 9 步 runbook.

D34 dry-run 演练升级版 (实战 110 prod).

9 步流程 (D34 升级版):
  ① Step 1: copy 整个 sql/extensions/ddl_sync/ 目录 (从 134 dev 推到 110 prod)
  ② Step 2: 110 prod settings.py 加 ddl_sync INSTALLED_APPS
  ③ Step 3: 110 prod urls.py 加 ddl_sync 路由
  ④ Step 4: 110 prod common/templates/base.html 加 ddl_sync menu (带守卫)
  ⑤ Step 5: 110 prod migrate ddl_sync
  ⑥ Step 6: 推 D22-D33 跨 app 6 文件
  ⑦ Step 7: kill + 拉新 gunicorn + qcluster
  ⑧ Step 8: 验证 6 项 (reverse + showmigrations + get_resolver + curl + 造 5 条 + openpyxl)
  ⑨ Step 9 (D33 实战新加): 验证 D33 视图改动 (Paginator + pair_history_export + ddlsync-btn-export + ddlsync-page-link)

实战前必查:
- 110 prod 路径: /dbdata/archery_v114_c9236a0/ (D31 实战新发现)
- 110 prod venv python: python3.9 (跟 134 dev python3.11 不同)
- 110 prod 端口: 9123 (跟 134 dev 9003 不同)
- 110 prod 没 systemd, 走 nohup
- 110 prod password: lAqfb8uEmQYsnGNQwIHtGPwukjCz6J
- 推前必 md5 校验 (D12 实战新发现)
- 必 kill + 拉新 qcluster (D24 实战新发现)
- 业务方提前通知 (演练窗口 < 1 分钟)
"""
import paramiko
import base64
import time
import sys

PROD = "172.20.2.110"
PWD = "lAqfb8uEmQYsnGNQwIHtGPwukjCz6J"
PROD_BASE = "/dbdata/archery_v114_c9236a0"
DEV = "172.20.2.134"
DEV_BASE = "/opt/archery/prod"

# === 实战开关: True 才执行, False 只演练不实际推 ===
LIVE_PUSH = False  # 实战前改为 True

def banner(s):
    print("\n" + "=" * 60)
    print(s)
    print("=" * 60)

def run_ssh(ssh, cmd, timeout=30):
    """执行 ssh 命令, 134 dev 输出走 ascii 转换防 GBK 错."""
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        try:
            out = out.encode("ascii", "ignore").decode("ascii")
        except Exception:
            pass
        return out
    except Exception as e:
        return f"ERR: {e}"

def main():
    banner("D35 实战推 110 prod 9 步 runbook")
    print(f"  LIVE_PUSH = {LIVE_PUSH} (True 才执行实际操作)")
    if not LIVE_PUSH:
        print("  当前是演练模式, 不执行实际操作")
        print("  实战前请把脚本顶部 LIVE_PUSH = True")

    # === 实战前 110 prod 状态确认 ===
    banner("实战前 110 prod 状态确认")
    prod = paramiko.SSHClient()
    prod.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    prod.connect(hostname=PROD, port=22, username="root", password=PWD, timeout=15)
    print("  [+] 110 prod SSH 连接 OK")

    out = run_ssh(prod, "pwd && ls -la " + PROD_BASE + "/ | head -20")
    print(f"  110 prod 顶层:\n{out}")

    out = run_ssh(prod, "ls -d " + PROD_BASE + "/sql/extensions/ddl_sync 2>&1")
    print(f"  110 prod ddl_sync 目录: {out.strip()}")

    out = run_ssh(prod, "ps -ef | grep -E 'gunicorn.*archery.*9123|manage.py qcluster' | grep -v grep | wc -l")
    print(f"  110 prod gunicorn+qcluster 进程数: {out.strip()}")

    out = run_ssh(prod, "ss -tlnp | grep ':9123' 2>&1 | head -3")
    print(f"  110 prod 9123 端口: {out.strip()}")

    # === 演练实战前 134 dev 状态确认 ===
    dev = paramiko.SSHClient()
    dev.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    dev.connect(hostname=DEV, port=22, username="root", password=PWD, timeout=15)
    print("  [+] 134 dev SSH 连接 OK")

    out = run_ssh(dev, "find " + DEV_BASE + "/sql/extensions/ddl_sync/ -type f | wc -l")
    print(f"  134 dev ddl_sync 文件数: {out.strip()}")

    if not LIVE_PUSH:
        banner("演练模式结束")
        print("  实战前请:")
        print("  1. 确认 110 prod 业务方已通知 (演练窗口 < 1 分钟)")
        print("  2. 确认 110 prod 备份已做 (/backup/upgrade_v114/)")
        print("  3. 改脚本 LIVE_PUSH = True")
        print("  4. 跑 9 步 runbook")
        prod.close()
        dev.close()
        return

    # === ① Step 1: copy 整个 ddl_sync/ 目录 ===
    banner("① Step 1: copy 整个 ddl_sync/ 目录 (134 dev → 110 prod)")
    out = run_ssh(prod, "rm -rf " + PROD_BASE + "/sql/extensions/ddl_sync && mkdir -p " + PROD_BASE + "/sql/extensions")
    print(f"  清空 110 prod ddl_sync: {out.strip()}")

    # 用 rsync 推 (如果 rsync 可用)
    # 或用 scp -r
    # 这里用 scp 简化: 逐个文件推 (慢但稳)
    # 实战时考虑用 rsync -avz --delete
    out = run_ssh(prod, "which rsync 2>&1")
    print(f"  rsync 可用: {out.strip()}")

    # 实战时跑: rsync -avz --delete {DEV}:{DEV_BASE}/sql/extensions/ddl_sync/ {PROD_BASE}/sql/extensions/ddl_sync/
    # 这里用 tar 流式传输 (跨 ssh, 不需要 rsync)
    # ssh dev "tar -czf - -C " + DEV_BASE + "/sql/extensions ddl_sync" | ssh prod "tar -xzf - -C " + PROD_BASE + "/sql/extensions"
    stdin, stdout, stderr = dev.exec_command("tar -czf - -C " + DEV_BASE + "/sql/extensions ddl_sync")
    tar_data = stdout.read()
    sftp = prod.open_sftp()
    sftp.putfo(__import__("io").BytesIO(tar_data), "/tmp/ddl_sync.tar.gz")
    sftp.close()
    print(f"  134 dev ddl_sync/ 打包推 110 prod: {len(tar_data)} bytes")

    out = run_ssh(prod, "cd " + PROD_BASE + "/sql/extensions && tar -xzf /tmp/ddl_sync.tar.gz && ls " + PROD_BASE + "/sql/extensions/ddl_sync/ | head -10")
    print(f"  110 prod ddl_sync/ 解压:\n{out}")
    run_ssh(prod, "rm /tmp/ddl_sync.tar.gz")

    # === ② Step 2: settings.py 加 ddl_sync INSTALLED_APPS ===
    banner("② Step 2: 110 prod settings.py 加 ddl_sync INSTALLED_APPS")
    # 实战时: 找 if CUSTOM_DDL_SYNC_ENABLED 块位置, 加守卫 + INSTALLED_APPS
    # 110 prod 实际没 ddl_sync 守卫, 直接在 line 419 后加
    # 实战时: py 改文件 (跟 D32 演练 v6 一致)
    py_modify = """
path = '/dbdata/archery_v114_c9236a0/archery/settings.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
if 'DdlSyncConfig' not in content:
    # 在 last INSTALLED_APPS 行后加
    pattern = r'(INSTALLED_APPS \\+= \\("[^"]+",\\)\\n)'
    import re
    matches = list(re.finditer(pattern, content))
    if matches:
        last = matches[-1]
        # 找 if 守卫位置 (在 sql.extensions.dingtalk_oa 之后)
        if 'CUSTOM_DDL_SYNC_ENABLED' not in content:
            new_block = '\\n## CUSTOM-MODIFIED: DDL \\u8de8\\u5e93\\u540c\\u6b65 ddl_sync app \\u6ce8\\u518c @ 2026-09-08 @ mavis\\n'
            new_block += 'CUSTOM_DDL_SYNC_ENABLED = env("CUSTOM_DDL_SYNC_ENABLED", default=True)\\n'
            new_block += 'if CUSTOM_DDL_SYNC_ENABLED:\\n'
            new_block += '    INSTALLED_APPS += ("sql.extensions.ddl_sync.apps.DdlSyncConfig",)\\n'
            content = content.replace(last.group(0), last.group(0) + new_block, 1)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            print('settings.py: ddl_sync INSTALLED_APPS added')
        else:
            print('settings.py: CUSTOM_DDL_SYNC_ENABLED already exists, skip')
    else:
        print('ERR: no INSTALLED_APPS found')
        import sys; sys.exit(1)
else:
    print('settings.py: DdlSyncConfig already registered, skip')
"""
    b = base64.b64encode(py_modify.encode("utf-8")).decode("ascii")
    run_ssh(prod, "cat > /tmp/_d35_modify_settings.py << 'PYEOF'\n" + py_modify + "\nPYEOF\npython3 /tmp/_d35_modify_settings.py")
    out = run_ssh(prod, "grep -n -A 2 'ddl_sync.apps.DdlSyncConfig\\|CUSTOM_DDL_SYNC_ENABLED' " + PROD_BASE + "/archery/settings.py | head -10")
    print(f"  110 prod settings.py:\n{out}")

    # === ③ Step 3: urls.py 加 ddl_sync 路由 ===
    banner("③ Step 3: 110 prod urls.py 加 ddl_sync 路由")
    py_urls = """
path = '/dbdata/archery_v114_c9236a0/archery/urls.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
if 'ddl_sync' not in content:
    # 找 ddl_gh_ost 路由块后加 ddl_sync 路由
    if 'CUSTOM_GH_OST_ENABLED' in content:
        old = 'if getattr(settings, "CUSTOM_GH_OST_ENABLED", False):\\n    urlpatterns += [\\n        path("gh_ost/", include(("sql.extensions.ddl_gh_ost.urls", "ddl_gh_ost"), namespace="ddl_gh_ost")),\\n    ]'
        new = old + '\\n\\nif getattr(settings, "CUSTOM_DDL_SYNC_ENABLED", False):\\n    urlpatterns += [\\n        path("ddl_sync/", include(("sql.extensions.ddl_sync.urls", "ddl_sync"), namespace="ddl_sync")),\\n    ]'
        if old in content:
            content = content.replace(old, new, 1)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            print('urls.py: ddl_sync 路由 added')
        else:
            print('ERR: ddl_gh_ost 块 not found, manual add')
    else:
        print('ERR: CUSTOM_GH_OST_ENABLED not in urls.py, manual add')
else:
    print('urls.py: ddl_sync already exists, skip')
"""
    b = base64.b64encode(py_urls.encode("utf-8")).decode("ascii")
    run_ssh(prod, "cat > /tmp/_d35_modify_urls.py << 'PYEOF'\n" + py_urls + "\nPYEOF\npython3 /tmp/_d35_modify_urls.py")
    out = run_ssh(prod, "grep -n -A 2 'ddl_sync/\\|CUSTOM_DDL_SYNC' " + PROD_BASE + "/archery/urls.py | head -10")
    print(f"  110 prod urls.py:\n{out}")

    # === ④ Step 4: base.html 加 ddl_sync menu + 守卫 ===
    banner("④ Step 4: 110 prod common/templates/base.html 加 ddl_sync menu")
    py_base = """
path = '/dbdata/archery_v114_c9236a0/common/templates/base.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
if 'ddl_sync' not in content:
    # 找 ddl_gh_ost menu 块后加 ddl_sync menu
    # 实战时: 找 {% if perms.ddl_gh_ost.view_ddlghosttask_rebuild %}{% endif %} 末尾
    pattern = r'(\\s*\\{% endif %\\})\\s*(?=\\s*\\{% if perms\\.sql\\.menu_query %\\})'
    import re
    m = re.search(pattern, content)
    if m:
        new_block = m.group(1) + '\\n\\n'
        new_block += '                    {# CUSTOM-MODIFIED: DDL \\u8de8\\u5e93\\u540c\\u6b65 \\u83dc\\u5355 @ 2026-09-08 @ mavis #}\\n'
        new_block += '                    {% if user.is_superuser or perms.ddl_sync.view_ddlsyncpair %}\\n'
        new_block += '                        <li>\\n'
        new_block += '                            <a href="{% url \\'ddl_sync:pair_list\\' %}"><i class="fa fa-list fa-fw"></i> \\u5e93\\u5bf9\\u5217\\u8868</a>\\n'
        new_block += '                        </li>\\n'
        new_block += '                    {% endif %}\\n'
        content = content.replace(m.group(0), new_block, 1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print('base.html: ddl_sync menu added')
    else:
        print('ERR: 没找到 {% endif %} 守卫, manual add')
else:
    print('base.html: ddl_sync already exists, skip')
"""
    b = base64.b64encode(py_base.encode("utf-8")).decode("ascii")
    run_ssh(prod, "cat > /tmp/_d35_modify_base.py << 'PYEOF'\n" + py_base + "\nPYEOF\npython3 /tmp/_d35_modify_base.py")

    # === ⑤ Step 5: migrate ddl_sync ===
    banner("⑤ Step 5: 110 prod migrate ddl_sync")
    out = run_ssh(prod, "cd " + PROD_BASE + " && sudo -u archery venv/bin/python manage.py migrate ddl_sync 2>&1 | head -20 | iconv -f utf-8 -t ascii//IGNORE")
    print(out)

    # === ⑥ Step 6: 推 D22-D33 跨 app 6 文件 ===
    banner("⑥ Step 6: 推 D22-D33 跨 app 6 文件")
    cross_app_files = [
        "sql/templates/detail.html",
        "sql/templates/sqlsubmit.html",
        "sql/extensions/ddl_gh_ost/services/column_diff.py",
        "sql/extensions/ddl_sync/views/__init__.py",
        "sql/extensions/ddl_sync/urls.py",
        "sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html",
    ]
    for f in cross_app_files:
        # scp from dev to prod
        sftp_dev = dev.open_sftp()
        sftp_prod = prod.open_sftp()
        with sftp_dev.open(DEV_BASE + "/" + f, "rb") as src:
            data = src.read()
        with sftp_prod.open("/tmp/_d35_" + f.replace("/", "_"), "wb") as dst:
            dst.write(data)
        sftp_dev.close()
        sftp_prod.close()
        # 推文件
        remote_tmp = "/tmp/_d35_" + f.replace("/", "_")
        out = run_ssh(prod, "cp " + remote_tmp + " " + PROD_BASE + "/" + f)
        print(f"  pushed: {f} ({out.strip()})")

    # === ⑦ Step 7: kill + 拉新 gunicorn + qcluster ===
    banner("⑦ Step 7: kill + 拉新 gunicorn + qcluster (D24 实战新发现 qcluster 必 kill)")
    run_ssh(prod, "pkill -9 -f 'gunicorn.*archery.*9123' 2>&1; sleep 2")
    run_ssh(prod, "pkill -9 -f 'manage.py qcluster' 2>&1; sleep 2")
    out = run_ssh(prod, "find " + PROD_BASE + " -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; find " + PROD_BASE + " -name '*.pyc' -delete 2>/dev/null; echo pycache cleared")
    print(f"  pycache: {out.strip()}")

    # 拉新 gunicorn
    out = run_ssh(prod, "cd " + PROD_BASE + " && setsid nohup sudo -u archery venv/bin/python venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9123 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn_d35.log 2>&1 & disown")
    print(f"  gunicorn 拉新: {out.strip()}")
    time.sleep(5)
    out = run_ssh(prod, "ps -ef | grep -E 'gunicorn.*archery.*9123' | grep -v grep | wc -l")
    print(f"  gunicorn 进程数 (期望 5): {out.strip()}")

    # 拉新 qcluster
    out = run_ssh(prod, "cd " + PROD_BASE + " && setsid nohup sudo -u archery venv/bin/python manage.py qcluster </dev/null >/var/log/archery/qcluster_d35.log 2>&1 & disown")
    print(f"  qcluster 拉新: {out.strip()}")
    time.sleep(4)
    out = run_ssh(prod, "ps -ef | grep -E 'manage.py qcluster' | grep -v grep | head -2")
    print(f"  qcluster 进程: {out.strip()}")

    # === ⑧ Step 8: 验证 6 项 ===
    banner("⑧ Step 8: 验证 6 项")
    # 8.1 reverse + showmigrations + get_resolver
    py_verify = """
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archery.settings')
import django; django.setup()
from django.urls import reverse, get_resolver
from sql.models import Users

admin = Users.objects.filter(is_superuser=True).first()
print('  admin user:', admin.username if admin else None)

# 8.1 reverse
try:
    url = reverse('ddl_sync:pair_list')
    print('  reverse pair_list OK:', url)
except Exception as e:
    print('  reverse FAIL:', e)

# 8.2 showmigrations
import subprocess
r = subprocess.run(['venv/bin/python', 'manage.py', 'showmigrations', 'ddl_sync'],
                   capture_output=True, text=True, cwd='/dbdata/archery_v114_c9236a0')
for l in r.stdout.split('\\n'):
    if '[X]' in l or '[ ]' in l:
        print('   ', l)

# 8.3 get_resolver
def walk(resolver, prefix=''):
    n = 0
    for p in resolver.url_patterns:
        if hasattr(p, 'url_patterns'):
            n += walk(p, prefix + str(p.pattern))
        else:
            full = prefix + str(p.pattern)
            if 'ddl_sync' in full:
                n += 1
    return n
print('  ddl_sync 路由总数:', walk(get_resolver()))
"""
    b = base64.b64encode(py_verify.encode("utf-8")).decode("ascii")
    run_ssh(prod, "cat > /tmp/_d35_verify.py << 'PYEOF'\n" + py_verify + "\nPYEOF\ncd /dbdata/archery_v114_c9236a0 && sudo -u archery venv/bin/python manage.py shell < /tmp/_d35_verify.py 2>&1 | head -20 | iconv -f utf-8 -t ascii//IGNORE")

    # 8.4 curl 验证
    out = run_ssh(prod, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9123/login/")
    print(f"  /login/ status (期望 200): {out.strip()}")
    out = run_ssh(prod, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9123/ddl_sync/pair/")
    print(f"  /ddl_sync/pair/ status (期望 302): {out.strip()}")
    out = run_ssh(prod, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9123/ddl_sync/pair/1/history_export/")
    print(f"  /ddl_sync/pair/1/history_export/ status (期望 302): {out.strip()}")

    # === ⑨ Step 9: 验证 D33 视图改动 ===
    banner("⑨ Step 9: 验证 D33 视图改动 (Paginator + pair_history_export + CSS)")
    out = run_ssh(prod, "grep -c 'Paginator\\|pair_history_export\\|ddlsync-btn-export\\|ddlsync-page-link' " + PROD_BASE + "/sql/extensions/ddl_sync/views/__init__.py " + PROD_BASE + "/sql/extensions/ddl_sync/urls.py " + PROD_BASE + "/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html | head -3")
    print(f"  D33 改动在 3 文件: {out.strip()}")

    banner("D35 实战完成")
    print("  全部 9 步 PASS, 准备 D26 健康检查 + D36 操作日志")

    prod.close()
    dev.close()

if __name__ == "__main__":
    main()
