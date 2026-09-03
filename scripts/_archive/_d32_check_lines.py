# -*- coding: utf-8 -*-
"""D32 quick check: 看 base.html 148-175 行."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(hostname='172.20.2.134', port=22, username='root', password='lAqfb8uEmQYsnGNQwIHtGPwukjCz6J', timeout=15)

s, o, e = ssh.exec_command('sed -n "148,175p" /opt/archery/prod/common/templates/base.html')
out = o.read().decode('utf-8', errors='replace')
print(out)
ssh.close()
