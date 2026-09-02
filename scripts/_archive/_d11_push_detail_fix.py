"""D11 实战 - SFTP 推 134 dev detail.html + views.py 修复 detail/119 JS ReferenceError

根因 (9/2 16:10 实战发现):
- 8/26 21:34 commit 0a04775 在 detail.html 加了字段 diff inline 区域
- 8/26 21:57 commit 2a04a12 修 detail.html + views.py 加 json.dumps 包装
- 8/26 推 110 时 detail.html 没推 (推 110 范围只限 gh-ost + 字段 diff sqlsubmit.html)
- 134 dev 8/26 21:22 推的 detail.html 是 0a04775 版本 (有 inline 但有 JS bug)
- 9/1+9/2 W2 推 ddl_sync 也没动 detail.html
- 134 dev 实际跑 md5 3bbf3cec1ba0818b1cef49763ec2341e (8/26 21:22 mtime)
- 本地 HEAD md5 5b40a9cae5d60b7aad87c2e765541368 (2a04a12 修复后)

修复方案: SFTP 推本地 detail.html + views.py 到 134 dev, kill gunicorn 拉新

DBA 二次开发 6 步 (D7 阶段 1 实战套路):
1. 备份 134 dev 现场
2. SFTP 推 2 文件
3. chown -R archery:archery
4. 清 __pycache__
5. kill gunicorn + nohup 拉新
6. 端点 verify + Django check
"""
import os
import sys
import time
import subprocess
import paramiko
import hashlib

REMOTE_HOST = "172.20.2.134"
REMOTE_PORT = 22
REMOTE_USER = "root"
REMOTE_PASS = "CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW"
REMOTE_BASE = "/opt/archery/prod"
LOCAL_BASE = "G:/MiniMax工作空间/archery_dev"

# 推的文件清单 (tuple: local, remote)
PUSH_FILES = [
    ("sql/templates/detail.html", f"{REMOTE_BASE}/sql/templates/detail.html"),
    ("sql/views.py", f"{REMOTE_BASE}/sql/views.py"),
]

# 备份文件名 (带时间戳)
TS = time.strftime("%Y%m%d_%H%M%S")
BACKUP_FILES = [(remote, remote + f".bak_{TS}") for local, remote in PUSH_FILES]

def local_md5(path):
    p = os.path.join(LOCAL_BASE, path)
    return hashlib.md5(open(p, "rb").read()).hexdigest()

def main():
    print(f"\n{'='*60}")
    print(f"D11 实战 - SFTP 推 134 dev detail.html + views.py 修复")
    print(f"{'='*60}\n")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(REMOTE_HOST, port=REMOTE_PORT, username=REMOTE_USER, password=REMOTE_PASS, timeout=10)
    sftp = ssh.open_sftp()

    def run(cmd, t=30):
        print(f"  $ {cmd}")
        si, so, se = ssh.exec_command(cmd, timeout=t)
        out = so.read().decode("utf-8", errors="replace")
        err = se.read().decode("utf-8", errors="replace")
        if out.strip(): print(f"  >>> {out.strip()[:200]}")
        if err.strip(): print(f"  ERR: {err.strip()[:200]}")
        return out, err

    # 步骤 1: 备份 134 dev 现场
    print(f"\n[步骤 1/6] 备份 134 dev 现场 (mtime={TS})")
    for src, bak in BACKUP_FILES:
        run(f"sudo -u archery cp {src} {bak}")
        run(f"sudo -u archery ls -la {bak}")

    # 步骤 2: SFTP 推文件
    print(f"\n[步骤 2/6] SFTP 推 2 文件")
    for local_rel, remote in PUSH_FILES:
        local_abs = os.path.join(LOCAL_BASE, local_rel)
        print(f"  PUT {local_rel} → {remote}")
        # 先确保父目录存在
        remote_dir = os.path.dirname(remote)
        run(f"sudo -u archery mkdir -p {remote_dir}")
        sftp.put(local_abs, f"/tmp/_push_{os.path.basename(remote)}")
        run(f"sudo -u archery mv /tmp/_push_{os.path.basename(remote)} {remote}")

    # 步骤 3: chown
    print(f"\n[步骤 3/6] chown -R archery:archery")
    for local_rel, remote in PUSH_FILES:
        run(f"chown archery:archery {remote}")
        run(f"sudo -u archery ls -la {remote}")

    # 步骤 4: 清 __pycache__
    print(f"\n[步骤 4/6] 清 __pycache__ (确保新代码生效)")
    run(f"sudo -u archery find {REMOTE_BASE} -type d -name __pycache__ -exec rm -rf {{}} + 2>/dev/null || true")
    out, _ = run(f"sudo -u archery find {REMOTE_BASE} -type d -name __pycache__ 2>/dev/null | head -3")
    if "pycache" not in out:
        print(f"  ✓ __pycache__ 已清空")

    # 步骤 5: kill gunicorn + 拉新
    print(f"\n[步骤 5/6] kill gunicorn + nohup 拉新")
    out, _ = run("pgrep -f 'gunicorn archery.wsgi' | head -10")
    print(f"  当前 gunicorn pids: {out.strip()}")
    run("pkill -9 -f 'gunicorn archery.wsgi' || true")
    time.sleep(2)
    out, _ = run("pgrep -f 'gunicorn archery.wsgi' | head -5 || true")
    if out.strip():
        print(f"  ⚠️  gunicorn 没全 kill, 残留: {out.strip()}")
    else:
        print(f"  ✓ gunicorn 已全 kill")

    # 拉新 (D7 阶段 1 实战套路: setsid nohup)
    gunicorn_cmd = (
        f"sudo -u archery bash -lc 'cd {REMOTE_BASE} && "
        f"setsid nohup venv/bin/gunicorn archery.wsgi:application "
        f"-w 4 -b 0.0.0.0:9003 --access-logfile - --error-logfile - --timeout 120 "
        f"> /tmp/gunicorn_134.log 2>&1 &'"
    )
    run(gunicorn_cmd)
    time.sleep(3)
    out, _ = run("pgrep -f 'gunicorn archery.wsgi' | head -10")
    print(f"  新 gunicorn pids: {out.strip()}")
    if not out.strip():
        print(f"  ❌ gunicorn 拉新失败, 请查 /tmp/gunicorn_134.log")
        sftp.close(); ssh.close()
        return
    print(f"  ✓ gunicorn 拉新成功")

    # 步骤 6: 端点 verify + Django check
    print(f"\n[步骤 6/6] 端点 verify + Django check")
    # 12 端点 verify (D8 阶段 2 实战套路)
    endpoints = [
        ("/login/", 200),
        ("/", 302),
        ("/admin/", 302),
        ("/dbaprinciples/", 302),
        ("/sqlworkflow/", 302),
        ("/api/v1/ddl-sync/pairs/", 302),
        ("/api/v1/ddl-sync/pairs/1/", 302),
        ("/api/v1/ddl-sync/pairs/1/tables/", 302),
        ("/api/v1/ddl-sync/pairs/1/history/", 302),
        ("/api/v1/ddl-sync/diff/", 302),
        ("/static/ddl_sync/pair_detail.js", 200),
    ]
    for ep, expect in endpoints:
        out, _ = run(f"curl -sS -o /dev/null -w 'HTTP:%{{http_code}}' 'http://127.0.0.1:9003{ep}'")
        code = out.strip().replace("HTTP:", "")
        ok = (int(code) == expect) if code.isdigit() else False
        flag = "✓" if ok else "✗"
        print(f"  {flag} {ep:50s} expect={expect} got={code}")

    # Django check
    out, _ = run(f"sudo -u archery bash -lc 'cd {REMOTE_BASE} && venv/bin/python manage.py check ddl_sync 2>&1'")
    if "System check identified no issues" in out:
        print(f"  ✓ Django check ddl_sync: no issues")
    else:
        print(f"  ⚠️  Django check: {out.strip()[:200]}")

    # 实际渲染 detail/119 验证
    print(f"\n[bonus] 重新拉 detail/119 实际渲染, 验证 var dbName 带引号")
    render_script = r'''
import os, sys, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
sys.path.insert(0, "/opt/archery/prod")
import django
django.setup()
from django.template.loader import render_to_string
from django.test import RequestFactory
from sql.models import SqlWorkflow
from sql.views import _workflow_sql_text
wf = SqlWorkflow.objects.get(id=119)
ctx = {
    "workflow_detail": wf,
    "sql_content_for_diff": json.dumps(_workflow_sql_text(wf)),
    "instance_id_for_diff": wf.instance_id or 0,
    "db_name_for_diff": json.dumps(wf.db_name or ""),
}
html = render_to_string("detail.html", ctx, request=RequestFactory().get("/detail/119/"))
with open("/tmp/d11_detail119_fixed.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"rendered {len(html)} bytes", flush=True)
'''
    sftp2 = ssh.open_sftp()
    with sftp2.file("/tmp/d11_render_check.py", "w") as f:
        f.write(render_script)
    sftp2.close()
    out, _ = run("sudo -u archery bash -lc 'cd /opt/archery/prod && /opt/archery/prod/venv/bin/python /tmp/d11_render_check.py'")
    run("grep -n 'var dbName\\|var sqlContent\\|var instanceId\\|hly_accesscard_history' /tmp/d11_detail119_fixed.html | head -10")

    # md5 验证
    print(f"\n[verify] md5 对比")
    out, _ = run(f"sudo -u archery md5sum {REMOTE_BASE}/sql/templates/detail.html {REMOTE_BASE}/sql/views.py")
    print(f"  {out.strip()}")
    print(f"  local  detail.html: {local_md5('sql/templates/detail.html')}")
    print(f"  local  views.py:    {local_md5('sql/views.py')}")

    sftp.close()
    ssh.close()
    print(f"\n{'='*60}")
    print(f"DONE")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
