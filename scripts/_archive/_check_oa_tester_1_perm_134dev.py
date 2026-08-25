"""134 dev 实地查 oa_tester_1 的 view_ddlghosttask perm 实际状态.

走 paramiko + root + 134 dev /opt/archery/prod/venv/bin/python3.11
+ manage.py shell 调 Django ORM.
"""
import io
import paramiko
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

HOST = "172.20.2.134"
USER = "root"
PASSWORD = "CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW"
VENV_PY = "/opt/archery/prod/venv/bin/python3.11"
PROD_DIR = "/opt/archery/prod"
CMD = (
    "from django.contrib.auth.models import Group, Permission; "
    "from sql.models import Users; "
    "u = Users.objects.get(username='oa_tester_1'); "
    "print('USERNAME:', u.username); "
    "print('IS_SUPERUSER:', u.is_superuser); "
    "print('GROUPS:', list(u.groups.values_list('name', flat=True))); "
    "perms = u.get_all_permissions(); "
    "print('ALL_PERMS_COUNT:', len(perms)); "
    "print('HAS_VIEW_DDLGHOSTTASK:', 'ddl_gh_ost.view_ddlghosttask' in perms); "
    "print('HAS_CHANGE_DDLGHOSTTASK:', 'ddl_gh_ost.change_ddlghosttask' in perms); "
    "print('VIEW_DDLGHOSTTASK_FROM_USER:', list(u.user_permissions.filter(codename__icontains='ddlghosttask').values_list('content_type__app_label', 'codename'))); "
    "gps = u.groups.all(); "
    "[print('GROUP', g.name, 'PERMS:', [p.codename for p in g.permissions.all() if 'ddlghosttask' in p.codename]) for g in gps]; "
    "print('---END---')"
)

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, 22, USER, PASSWORD, timeout=15)
    except Exception as e:
        print(f"SSH 连接失败: {e}", flush=True)
        return

    shell_cmd = f"cd {PROD_DIR} && {VENV_PY} manage.py shell -c \"{CMD}\" 2>&1 | grep -v 'import local settings failed, ignored' | tail -50"
    print(f"CMD: {shell_cmd}", flush=True)

    stdin, stdout, stderr = client.exec_command(shell_cmd, timeout=60)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    print("=== STDOUT ===", flush=True)
    print(out, flush=True)
    print("=== STDERR ===", flush=True)
    print(err, flush=True)
    client.close()

if __name__ == "__main__":
    main()
