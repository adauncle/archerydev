"""D11 实战 - 拉 134 dev detail/119 HTML 看实际渲染"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("172.20.2.134", port=22, username="root", password="CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW", timeout=10)

# 拉 detail/119/ (没 login_required)
cmd = """curl -sS -L 'http://127.0.0.1:9003/detail/119/' -o /tmp/detail119.html -w 'HTTP:%{http_code} SIZE:%{size_download}\\n'"""
stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode())

# 看 line 1950-1960
cmd2 = """awk 'NR>=1948 && NR<=1965 {print NR": "$0}' /tmp/detail119.html"""
stdin, stdout, stderr = ssh.exec_command(cmd2)
print("=== Lines 1948-1965 ===")
print(stdout.read().decode())

# 找所有 var dbName / var sqlContent / hly_accesscard_history
cmd3 = """grep -n 'var dbName\\|var sqlContent\\|var instanceId\\|hly_accesscard_history\\|fetchColumnDiff' /tmp/detail119.html | head -30"""
stdin, stdout, stderr = ssh.exec_command(cmd3)
print("=== grep var ===")
print(stdout.read().decode())

# 找 EditSqlContent / sql_content_for_diff / db_name_for_diff
cmd4 = """grep -n 'sql_content_for_diff\\|db_name_for_diff\\|instance_id_for_diff\\|EditSqlContent\\|editSqlContent' /tmp/detail119.html | head -20"""
stdin, stdout, stderr = ssh.exec_command(cmd4)
print("=== grep diff ===")
print(stdout.read().decode())

# 看 #117 是不是一样的 (之前实战过)
cmd5 = """curl -sS -L 'http://127.0.0.1:9003/detail/117/' -o /tmp/detail117.html -w 'HTTP:%{http_code} SIZE:%{size_download}\\n'"""
stdin, stdout, stderr = ssh.exec_command(cmd5)
print(stdout.read().decode())

# 看 #117 line 1950-1960
cmd6 = """awk 'NR>=1948 && NR<=1965 {print NR": "$0}' /tmp/detail117.html"""
stdin, stdout, stderr = ssh.exec_command(cmd6)
print("=== 117 Lines 1948-1965 ===")
print(stdout.read().decode())

ssh.close()
