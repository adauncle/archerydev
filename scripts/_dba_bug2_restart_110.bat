@echo off
chcp 65001 > nul
F:\putty\plink.exe -ssh -pw lAqfb8uEmQYsnGNQwIHtGPwukjCz6J -hostkey SHA256:DHkk6e+b9hkybykAzqxARzkng5AHfvmO8v5KY0XNsLU root@172.20.2.110 "kill -TERM 20691 33466 45397 48379 83802 2>&1; sleep 5; ps -ef | grep gunicorn | head -10"
