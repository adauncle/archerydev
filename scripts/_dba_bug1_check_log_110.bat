@echo off
chcp 65001 > nul
F:\putty\plink.exe -ssh -pw lAqfb8uEmQYsnGNQwIHtGPwukjCz6J -hostkey SHA256:DHkk6e+b9hkybykAzqxARzkng5AHfvmO8v5KY0XNsLU root@172.20.2.110 "ps -ef | grep gunicorn | head -10; echo ---; ls -la /dbdata/archery_v114_c9236a0/sql/views.py; echo ---; grep -c 'DBA-bug-1 DEBUG' /dbdata/archery_v114_c9236a0/sql/views.py; echo ---; tail -2 /dbdata/archery_v114_c9236a0/sql/views.py"
