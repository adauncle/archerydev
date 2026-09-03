# -*- coding: utf-8 -*-
"""D32 完整查 gunicorn 日志."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(hostname='172.20.2.134', port=22, username='root', password='lAqfb8uEmQYsnGNQwIHtGPwukjCz6J', timeout=15)

s, o, e = ssh.exec_command('tail -30 /var/log/archery/gunicorn_d32_drill1.log 2>&1')
print("--- gunicorn_d32_drill1.log 最后 30 行 ---")
print(o.read().decode('utf-8', errors='replace'))

# 试 /ddl_sync/pair/ 看完整响应
s, o, e = ssh.exec_command('curl -s -i http://127.0.0.1:9003/ddl_sync/pair/ 2>&1 | head -20')
print("\n--- curl /ddl_sync/pair/ 完整响应 ---")
print(o.read().decode('utf-8', errors='replace'))

# 试 /ddl_sync/ 看响应
s, o, e = ssh.exec_command('curl -s -i http://127.0.0.1:9003/ddl_sync/ 2>&1 | head -20')
print("\n--- curl /ddl_sync/ 完整响应 ---")
print(o.read().decode('utf-8', errors='replace'))

# 试 /nonexist/ 看 404 vs 302
s, o, e = ssh.exec_command('curl -s -i http://127.0.0.1:9003/nonexist/ 2>&1 | head -10')
print("\n--- curl /nonexist/ 完整响应 ---")
print(o.read().decode('utf-8', errors='replace'))

# 看 urls.py 现在的状态
s, o, e = ssh.exec_command('cat /opt/archery/prod/archery/urls.py | head -80')
print("\n--- urls.py 完整内容 (line 1-80) ---")
print(o.read().decode('utf-8', errors='replace'))

ssh.close()
