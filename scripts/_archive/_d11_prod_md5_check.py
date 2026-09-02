"""D11 实战 - 同时查 134 dev + 110 prod 实际跑 detail.html md5"""
import paramiko

def check(host, port, user, pwd, label, base):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, port=port, username=user, password=pwd, timeout=10)
    def run(cmd, t=15):
        si, so, se = ssh.exec_command(cmd, timeout=t)
        return so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")
    out, _ = run(f"sudo -u archery md5sum {base}/sql/templates/detail.html {base}/sql/views.py")
    print(f"\n=== {label} ({host}) ===")
    print(out)
    out, _ = run(f"sudo -u archery ls -la {base}/sql/templates/detail.html {base}/sql/views.py")
    print(out)
    ssh.close()

# 134 dev
check("172.20.2.134", 22, "root", "CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", "134 dev", "/opt/archery/prod")
# 110 prod
check("172.20.2.110", 22, "root", "lAqfb8uEmQYsnGNQwIHtGPwukjCz6J", "110 prod", "/dbdata/archery_v114")

# 本地参考
import hashlib
def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()
print(f"\n=== local (G:/MiniMax工作空间/archery_dev) ===")
print(f"detail.html: {md5('G:/MiniMax工作空间/archery_dev/sql/templates/detail.html')}")
print(f"views.py:    {md5('G:/MiniMax工作空间/archery_dev/sql/views.py')}")
