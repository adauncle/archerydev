#!/bin/bash
# 110 prod gunicorn reload (大表自动勾选 gh-ost 9/18)
set -a
source /dbdata/archery_v114_c9236a0/.env
set +a
export CAS_SERVER_URL=https://dummy.cas.local
export CAS_SERVER_PORT=443
export CAS_REALM=dummy
export CAS_LOGIN_URL=https://dummy.cas.local/login
export CAS_VALIDATE_URL=https://dummy.cas.local/validate
export CAS_LOGOUT_URL=https://dummy.cas.local/logout
export CAS_VERSION=3
cd /dbdata/archery_v114_c9236a0
pkill -f "gunicorn.*archery" || true
sleep 3
./venv/bin/python3.9 ./venv/bin/gunicorn --workers 5 --bind 0.0.0.0:9123 --access-logfile ./logs/access.log --error-logfile ./logs/error.log --capture-output --daemon --pid /tmp/gunicorn_110.pid archery.wsgi:application
sleep 3
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9123/login/
echo "DONE"