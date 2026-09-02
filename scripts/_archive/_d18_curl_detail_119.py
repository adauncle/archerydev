# -*- coding: utf-8 -*-
"""9/2 D18: curl /detail/119/ 看实际渲染."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    hostname="172.20.2.134", port=22, username="root",
    password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW",
    timeout=15,
)

def run(cmd, timeout=30):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out, err, stdout.channel.recv_exit_status()

try:
    print("=" * 70)
    print("D18: 134 dev curl /detail/119/ 实际渲染")
    print("=" * 70)

    # Step 1: login (Archery 走 session + csrf, 先 GET 拿 token 再 POST)
    print("\n[1] login 拿 cookie (先 GET 拿 csrftoken, 再 POST 带 csrf)")
    print("-" * 70)
    out, _, _ = run("rm -f /tmp/cookies.txt && curl -s -c /tmp/cookies.txt http://127.0.0.1:9003/login/ -o /dev/null -w 'login_page=%{http_code}" + chr(10) + "'")
    print(out.strip())
    out, _, _ = run("cat /tmp/cookies.txt | grep csrftoken | awk '{print $7}'")
    csrftoken = out.strip()
    print(f"csrftoken: {csrftoken}")
    out, _, _ = run("curl -s -b /tmp/cookies.txt -c /tmp/cookies.txt -X POST -H 'Referer: http://127.0.0.1:9003/login/' -d 'username=archery&password=archery&csrfmiddlewaretoken=" + csrftoken + "' http://127.0.0.1:9003/authenticate/ -L -o /dev/null -w 'authenticate=" + chr(37) + "{http_code}" + chr(10) + "'")
    print(out.strip())
    out, _, _ = run("cat /tmp/cookies.txt | grep -E 'sessionid|csrftoken'")
    print(f"cookies after auth: {out.strip()}")

    # Step 2: curl /detail/119/
    print("\n[2] curl /detail/119/")
    print("-" * 70)
    out, _, _ = run("curl -s -b /tmp/cookies.txt -o /tmp/detail119.html -w 'http_code=%{http_code} size=%{size_download}\\n' http://127.0.0.1:9003/detail/119/")
    print(out.strip())

    # Step 3: 关键内容 grep
    print("\n[3] /detail/119/ 关键内容 grep")
    print("-" * 70)
    queries = [
        ("SQL 内容", r"add COLUMN test\d+"),
        ("镜像 关键词", r"镜像"),
        ("目标库 hly_accesscard_history", r"hly_accesscard_history"),
        ("源库 hly_accesscard", r"hly_accesscard(?!_)"),
        ("源工单 link", r"wf#1\d{2}|/detail/11\d{2}/"),
        ("workflow_name", r"\[镜像\] test"),
        ("status 关键词", r"workflow_manreviewing|workflow_abort|workflow_finish|workflow_review_pass|workflow_queuing"),
        ("测试 MySQL 8.0", r"测试 MySQL 8.0"),
        ("audit_auth_groups 14,3", r"14,3"),
    ]
    for label, pat in queries:
        out, _, _ = run(f"grep -cE '{pat}' /tmp/detail119.html")
        cnt = out.strip()
        print(f"  {label:30s} count={cnt}")

    # Step 4: workflow_name 实际值
    print("\n[4] workflow_name / status 实际值")
    print("-" * 70)
    out, _, _ = run("grep -oE 'workflow_name.{0,100}' /tmp/detail119.html | head -3")
    print(f"workflow_name 附近: {out[:200]}")
    out, _, _ = run("grep -oE 'badge.{0,80}workflow_(manreviewing|abort|finish|review_pass|queuing)' /tmp/detail119.html | head -3")
    print(f"status badge: {out[:200]}")

    # Step 5: SQL 内容显示
    print("\n[5] SQL 内容显示")
    print("-" * 70)
    out, _, _ = run("grep -oE 'add COLUMN test1 VARCHAR.{0,150}' /tmp/detail119.html | head -1")
    print(f"完整 SQL 行: {out[:250]}")
    out, _, _ = run("grep -oE 'sql_content|workflow-detail-sql|SQL 内容' /tmp/detail119.html | head -3")
    print(f"SQL 显示块标签: {out[:200]}")

    # Step 6: 镜像工单特殊标识
    print("\n[6] 镜像标识 / 源工单关联")
    print("-" * 70)
    out, _, _ = run("grep -oE '源工单|来源|source_workflow|源 DDL|源业务库' /tmp/detail119.html | sort -u")
    print(f"源工单相关词: {out.strip()}")
    out, _, _ = run("grep -oE 'ddl_sync|DdlSyncHistory|镜像工单' /tmp/detail119.html | sort -u")
    print(f"ddl_sync 相关词: {out.strip()}")

    # Step 7: head 500 字符看大概结构
    print("\n[7] detail/119 头部 500 字符")
    print("-" * 70)
    out, _, _ = run("head -c 500 /tmp/detail119.html")
    print(out)

finally:
    ssh.close()
