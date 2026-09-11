@echo off
chcp 65001 > nul
F:\putty\plink.exe -ssh -pw lAqfb8uEmQYsnGNQwIHtGPwukjCz6J -hostkey SHA256:DHkk6e+b9hkybykAzqxARzkng5AHfvmO8v5KY0XNsLU root@172.20.2.110 "grep -n 'CUSTOM-MODIFIED: 9/11 DBA-bug-3' /dbdata/archery_v114_c9236a0/sql/templates/sqlsubmit.html"
