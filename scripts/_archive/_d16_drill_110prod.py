# -*- coding: utf-8 -*-
"""9/2 D16: 实战演练汪银和工单 4771 验证 D15 修复在 110 prod 生效 (简化版)."""
import os
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    hostname="172.20.2.110", port=22, username="root",
    password="lAqfb8uEmQYsnGNQwIHtGPwukjCz6J",
    timeout=15,
)

try:
    drill_script = r'''
import os, sys
os.environ['DJANGO_SETTINGS_MODULE'] = 'archery.settings'
sys.path.insert(0, '/dbdata/archery_v114_c9236a0')
import django
django.setup()

from sql.models import Instance
from sql.extensions.ddl_gh_ost.services.column_diff import column_diff_full, _fetch_current_columns

inst = Instance.objects.get(id=31)
print(f"instance 31: {inst.instance_name} {inst.host}:{inst.port}")

# 实战演练 1: order_penalty 汪银和工单 4771 实战 SQL
print("\n=== 实战演练 order_penalty (汪银和工单 4771) ===")
print("SQL: ALTER TABLE order_penalty MODIFY COLUMN penalty_item varchar(200) DEFAULT NULL COMMENT '罚项'")
sql1 = """ALTER TABLE order_penalty MODIFY COLUMN penalty_item varchar(200) DEFAULT NULL COMMENT '罚项'"""
res1 = column_diff_full(inst, "hly_platform", sql1)
if res1.get("ok"):
    for t in res1.get("tables", []):
        for c in t.get("columns", []):
            print(f"\n表 {t['table_name']} 字段 {c['name']} {c['operation']}:")
            if c.get("diffs"):
                for d in c.get("diffs", []):
                    print(f"  field={d.get('field')}, old={d.get('old')!r}, new={d.get('new')!r}, risk={d.get('risk')}, reason={d.get('reason')}")
            else:
                print("  (无 diff)")
    print(f"\n全局: high={res1.get('high_risk_count')}, mid={res1.get('mid_risk_count')}, low={res1.get('low_risk_count')}")
    print(f"summary: {res1.get('summary')}")
else:
    print(f"实战 ERR: {res1.get('error')}")

# 实战演练 2: waybill_penalty 汪银和工单 4771 实战 SQL
print("\n\n=== 实战演练 waybill_penalty (汪银和工单 4771) ===")
print("SQL: ALTER TABLE waybill_penalty MODIFY COLUMN penalty_item varchar(200) DEFAULT NULL COMMENT '罚项'")
sql2 = """ALTER TABLE waybill_penalty MODIFY COLUMN penalty_item varchar(200) DEFAULT NULL COMMENT '罚项'"""
res2 = column_diff_full(inst, "hly_platform", sql2)
if res2.get("ok"):
    for t in res2.get("tables", []):
        for c in t.get("columns", []):
            print(f"\n表 {t['table_name']} 字段 {c['name']} {c['operation']}:")
            if c.get("diffs"):
                for d in c.get("diffs", []):
                    print(f"  field={d.get('field')}, old={d.get('old')!r}, new={d.get('new')!r}, risk={d.get('risk')}, reason={d.get('reason')}")
            else:
                print("  (无 diff)")
    print(f"\n全局: high={res2.get('high_risk_count')}, mid={res2.get('mid_risk_count')}, low={res2.get('low_risk_count')}")
    print(f"summary: {res2.get('summary')}")
else:
    print(f"实战 ERR: {res2.get('error')}")

# 实战演练 3: 完整汪银和工单 4771 7 张表 (实战原 SQL)
print("\n\n=== 实战演练 汪银和工单 4771 完整 7 张表 ===")
sql3 = """use `hly_platform`;
ALTER TABLE project_config ADD COLUMN test1 VARCHAR(256) DEFAULT NULL COMMENT '测试 1';
ALTER TABLE company_info MODIFY COLUMN company_name VARCHAR(200) DEFAULT NULL;
ALTER TABLE team MODIFY COLUMN team_name VARCHAR(200) DEFAULT NULL;
ALTER TABLE order_penalty MODIFY COLUMN penalty_item VARCHAR(200) DEFAULT NULL COMMENT '罚项';
ALTER TABLE waybill_penalty MODIFY COLUMN penalty_item VARCHAR(200) DEFAULT NULL COMMENT '罚项';
ALTER TABLE company_waybill_protocol_apply ADD COLUMN remark VARCHAR(500) DEFAULT NULL;
"""
res3 = column_diff_full(inst, "hly_platform", sql3)
if res3.get("ok"):
    print(f"全局: high={res3.get('high_risk_count')}, mid={res3.get('mid_risk_count')}, low={res3.get('low_risk_count')}")
    print(f"summary: {res3.get('summary')}")
    for t in res3.get("tables", []):
        for c in t.get("columns", []):
            has_charset_diff = any(d.get("field") in ("charset", "collation") for d in c.get("diffs", []))
            has_charset_high = any(d.get("field") in ("charset", "collation") and d.get("risk") == "high" for d in c.get("diffs", []))
            print(f"  表 {t['table_name']} 字段 {c['name']} {c['operation']}: has_charset_diff={has_charset_diff}, has_charset_high={has_charset_high}, total_diffs={len(c.get('diffs', []))}")
else:
    print(f"实战 ERR: {res3.get('error')}")
'''
    sftp = ssh.open_sftp()
    with sftp.open("/tmp/d16_drill_wangyinhe_v2.py", "w") as f:
        f.write(drill_script)
    sftp.chmod("/tmp/d16_drill_wangyinhe_v2.py", 0o755)
    sftp.close()
    print("Pushed: /tmp/d16_drill_wangyinhe_v2.py")

    cmd = (
        "cd /dbdata/archery_v114_c9236a0 && "
        "sudo -u archery /dbdata/archery_v114_c9236a0/venv/bin/python /tmp/d16_drill_wangyinhe_v2.py"
    )
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print("\nSTDOUT:")
    print(out)
    if err:
        print("\nSTDERR (first 3KB):")
        print(err[:3000])
finally:
    ssh.close()
