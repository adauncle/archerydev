# -*- coding: utf-8 -*-
"""D33 verify pagination: 临时造 5 条 history 让总数 > 20."""
import paramiko

DEV = "172.20.2.134"
PWD = "lAqfb8uEmQYsnGNQwIHtGPwukjCz6J"
DEV_BASE = "/opt/archery/prod"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(hostname=DEV, port=22, username="root", password=PWD, timeout=15)

def run(cmd, timeout=30):
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        return out
    except Exception as e:
        return f"ERR: {e}"

# 1. 备份当前 history count
print("--- 1. 当前 history count ---")
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c 'from sql.extensions.ddl_sync.models import DdlSyncHistory; print(\"count:\", DdlSyncHistory.objects.count())' 2>&1 | tail -3 | iconv -f utf-8 -t ascii//IGNORE')
print(out)

# 2. 造 5 条 history 测分页
print("\n--- 2. 临时造 5 条 history ---")
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c 'from sql.extensions.ddl_sync.models import DdlSyncPair, DdlSyncHistory; from django.utils import timezone; import datetime; pair = DdlSyncPair.objects.get(id=1); for i in range(5): h = DdlSyncHistory.objects.create(pair=pair, table_name=\"_d33_test_pagination_\" + str(i), sync_status=\"synced\", created_at=timezone.now() - datetime.timedelta(minutes=i), finished_at=timezone.now() - datetime.timedelta(minutes=i)); print(\"created:\", h.id); print(\"new count:\", DdlSyncHistory.objects.count())' 2>&1 | tail -10 | iconv -f utf-8 -t ascii//IGNORE")
print(out)

# 3. 验证分页
print("\n--- 3. 验证分页 (21 条 → 2 页) ---")
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c 'from django.test import Client; from sql.models import Users; admin = Users.objects.get(username=\"archery\"); c = Client(); c.force_login(admin); r = c.get(\"/ddl_sync/pair/1/\", HTTP_HOST=\"172.20.2.134\"); html = r.content.decode(\"utf-8\", errors=\"replace\"); print(\"status:\", r.status_code, \"len:\", len(r.content)); print(\"has history_page= link:\", \"history_page=\" in html); print(\"has page 2 link:\", \"history_page=2\" in html); print(\"has page current class:\", \"ddlsync-page-current\" in html)' 2>&1 | tail -10 | iconv -f utf-8 -t ascii//IGNORE")
print(out)

# 4. 测 page 2 渲染
print("\n--- 4. 测 page 2 渲染 ---")
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c 'from django.test import Client; from sql.models import Users; admin = Users.objects.get(username=\"archery\"); c = Client(); c.force_login(admin); r = c.get(\"/ddl_sync/pair/1/?history_page=2\", HTTP_HOST=\"172.20.2.134\"); html = r.content.decode(\"utf-8\", errors=\"replace\"); print(\"status:\", r.status_code, \"len:\", len(r.content)); print(\"has _d33_test_pagination_ in page 2:\", \"_d33_test_pagination_\" in html)' 2>&1 | tail -5 | iconv -f utf-8 -t ascii//IGNORE")
print(out)

# 5. 导出全部 21 条
print("\n--- 5. 导出 21 条 xlsx ---")
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c 'from django.test import Client; from sql.models import Users; admin = Users.objects.get(username=\"archery\"); c = Client(); c.force_login(admin); r = c.get(\"/ddl_sync/pair/1/history_export/\", HTTP_HOST=\"172.20.2.134\"); with open(\"/opt/archery/d33_test.xlsx\", \"wb\") as f: f.write(r.content); print(\"status:\", r.status_code, \"len:\", len(r.content))' 2>&1 | tail -3 | iconv -f utf-8 -t ascii//IGNORE")
print(out)
out = run('ls -la /opt/archery/d33_test.xlsx')
print(out)

# 6. 用 openpyxl 解析
print("\n--- 6. 解析 xlsx ---")
out = run('cd /opt/archery && sudo -u archery venv/bin/python -c "from openpyxl import load_workbook; wb = load_workbook(\\'d33_test.xlsx\\'); ws = wb.active; print(\\'rows:\\', ws.max_row); print(\\'headers:\\', [c.value for c in ws[1]]); print(\\'row 2:\\', [c.value for c in ws[2]])" 2>&1 | head -10')
print(out)

# 7. 清理临时 5 条
print("\n--- 7. 清理临时 5 条 history ---")
out = run('cd ' + DEV_BASE + " && sudo -u archery venv/bin/python manage.py shell -c 'from sql.extensions.ddl_sync.models import DdlSyncHistory; n = DdlSyncHistory.objects.filter(table_name__startswith=\"_d33_test_pagination_\").delete(); print(\"deleted:\", n); print(\"count after:\", DdlSyncHistory.objects.count())' 2>&1 | tail -5 | iconv -f utf-8 -t ascii//IGNORE")
print(out)

# 8. 清理 d33_test.xlsx
out = run('rm -f /opt/archery/d33_test.xlsx')
print(f"cleanup: {out.strip()}")

ssh.close()
