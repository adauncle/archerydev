#!/bin/bash
# DBA-bug-1 单元测试 @ 134 dev
set -e
cd /opt/archery/prod
export DJANGO_SETTINGS_MODULE=archery.settings
/opt/archery/prod/venv/bin/python -c '
import sys, os, django
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()
exec(open("scripts/_dba_bug1_unit_test.py").read())
'
