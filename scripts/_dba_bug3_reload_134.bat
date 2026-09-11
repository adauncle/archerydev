@echo off
chcp 65001 > nul
F:\putty\plink.exe -ssh -pw 123.ahggwl -hostkey SHA256:DHkk6e+b9hkybykAzqxARzkng5AHfvmO8v5KY0XNsLU root@172.20.2.134 "kill -TERM 45705 45706 45707 45708 2>&1; sleep 5; ps -ef | grep gunicorn | head -8"
