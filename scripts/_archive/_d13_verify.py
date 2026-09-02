"""D13 实战 - 看 systemd 状态 + gunicorn 跑哪个版本"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)

def run(c, t=10):
    si, so, se = ssh.exec_command(c, timeout=t)
    return so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")

# systemd status
out, _ = run("systemctl status archery-prod-gunicorn 2>&1 | head -30")
print(f"=== systemctl status ===\n{out}", flush=True)

# gunicorn 实际进程
out, _ = run("ps -eo pid,etime,cmd | grep gunicorn | grep -v grep | head -10")
print(f"=== ps gunicorn ===\n{out}", flush=True)

# 验证 column_diff_full 是否新版本 (看 _diff_single_table 函数)
out, _ = run("grep -c 'def _diff_single_table' /opt/archery/prod/sql/extensions/ddl_gh_ost/services/column_diff.py")
print(f"_diff_single_table in actual file: {out}", flush=True)

# md5
out, _ = run("md5sum /opt/archery/prod/sql/extensions/ddl_gh_ost/services/column_diff.py /opt/archery/prod/sql/templates/detail.html /opt/archery/prod/sql/templates/sqlsubmit.html")
print(f"=== md5 ===\n{out}", flush=True)

# 测试 column_diff_full 端点
print("\n=== 实战演练 5 张表演练 ===", flush=True)
test_sql = """ALTER TABLE accesscard_test_diff1
    MODIFY name varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'test' COMMENT '新名称';
ALTER TABLE accesscard_test_diff1
    ADD new_col varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '新列';
ALTER TABLE accesscard_test_diff2
    MODIFY id bigint(20) NOT NULL AUTO_INCREMENT COMMENT 'BIGINT id';
ALTER TABLE accesscard_test_diff3
    ADD col3 varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'x' COMMENT 'col3';
ALTER TABLE accesscard_test_diff4
    DROP old_col;
ALTER TABLE accesscard_test_diff5
    MODIFY id int(11) NOT NULL DEFAULT 0 COMMENT 'ID';"""

# 用 curl POST /gh_ost/column_diff/ (需登录, 先看是否需要)
# 实战先看现有 134 dev 表 list
out, _ = run("sudo -u archery /opt/archery/prod/venv/bin/python -c \"import sys; sys.path.insert(0, '/opt/archery/prod'); import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archery.settings'); import django; django.setup(); from sql.models import Instance; print('Instance list:'); [print(f'  {i.id} {i.instance_name} type={i.type}') for i in Instance.objects.all()[:5]]\" 2>&1 | tail -10")
print(f"=== Instance list ===\n{out}", flush=True)

ssh.close()
print("DONE", flush=True)
