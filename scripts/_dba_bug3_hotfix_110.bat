@echo off
chcp 65001 > nul
F:\putty\plink.exe -ssh -pw lAqfb8uEmQYsnGNQwIHtGPwukjCz6J -hostkey SHA256:DHkk6e+b9hkybykAzqxARzkng5AHfvmO8v5KY0XNsLU root@172.20.2.110 "chown archery:archery /dbdata/archery_v114_c9236a0/sql/templates/sqlsubmit.html; kill -TERM 52537 52538 52539 52544 52545 2>&1; sleep 5; ps -ef | grep gunicorn | head -8"
