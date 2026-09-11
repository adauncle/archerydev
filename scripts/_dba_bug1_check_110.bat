@echo off
chcp 65001 > nul
F:\putty\plink.exe -ssh -pw lAqfb8uEmQYsnGNQwIHtGPwukjCz6J -hostkey SHA256:DHkk6e+b9hkybykAzqxARzkng5AHfvmO8v5KY0XNsLU root@172.20.2.110 "grep -n 'status_for_alert' /dbdata/archery_v114_c9236a0/sql/views.py; echo ---; grep -n 'workflow_manreviewing' /dbdata/archery_v114_c9236a0/sql/views.py; echo ---; grep -n 'CUSTOM-MODIFIED' /dbdata/archery_v114_c9236a0/sql/views.py | head -10"
