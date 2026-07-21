#!/bin/bash
set -e
DBOPS_PWD="$(cat /etc/archery/dbops_password)"
REDIS_PWD="$(cat /etc/archery/redis_password)"

for env in dev staging prod; do
    # 每环境独立 SECRET_KEY (50 字符 url-safe)
    SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"

    # DEBUG 标志：dev=True，staging/prod=False
    if [ "${env}" = "dev" ]; then
        DEBUG="True"
    else
        DEBUG="False"
    fi

    cat > "/opt/archery/${env}/.env" <<EOF
# ========== Django ==========
DEBUG=${DEBUG}
SECRET_KEY=${SECRET_KEY}
ALLOWED_HOSTS=localhost,127.0.0.1,172.20.2.134

# ========== 钉钉 OA 二次开发（启用后才走 dingtalk_oa 流程）==========
CUSTOM_DINGTALK_OA_ENABLED=True
CUSTOM_DINGTALK_OA_AUDITOR=sql.extensions.audit_drivers.configurable_auditor:ConfigurableAuditor
CUSTOM_DINGTALK_OA_RETRY_TIMES=3
CUSTOM_DINGTALK_OA_TIMEOUT_SECONDS=10
CUSTOM_DINGTALK_OA_RECONCILE_INTERVAL_MIN=5
CUSTOM_DINGTALK_OA_RECONCILE_TIMEOUT_MIN=30
CUSTOM_DINGTALK_OA_FALLBACK_ENABLED=True
# 注：以下 5 个凭据必须填真实值（钉钉开放平台后台拿），否则 callback 验签失败
DINGTALK_OA_APP_KEY=
DINGTALK_OA_APP_SECRET=
DINGTALK_OA_AGENT_ID=
DINGTALK_OA_CALLBACK_TOKEN=
DINGTALK_OA_CALLBACK_AES_KEY=
DINGTALK_OA_CALLBACK_RECEIVEID=
# 失败告警 webhook（fallback 触发 / 安全告警时调用）
DINGTALK_NOTIFY_WEBHOOK=

# ========== MySQL（django-environ 用 DATABASE_URL 读，格式：mysql://user:pass@host:port/db）==========
# 注意：特殊字符（@, #, $）必须 URL-encode（@ → %40, # → %23, $ → %24）
DBOPS_ENC="$(python3 -c 'import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=""), end="")' "${DBOPS_PWD}")"
DATABASE_URL=mysql://dbops:${DBOPS_ENC}@127.0.0.1:3306/archery_${env}

# 兼容旧字段（部分代码可能直接读 MYSQL_*）
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=dbops
MYSQL_PASSWORD=${DBOPS_PWD}
MYSQL_DB=archery_${env}

# ========== Redis ==========
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=${REDIS_PWD}

# ========== Celery ==========
CELERY_BROKER_URL=redis://:${REDIS_PWD}@127.0.0.1:6379/1
CELERY_RESULT_BACKEND=redis://:${REDIS_PWD}@127.0.0.1:6379/2

# ========== 通知（空 - 部署后再填）==========
DINGTALK_WEBHOOK=
DINGTALK_SECRET=
WECOM_WEBHOOK=
EMAIL_HOST=
EMAIL_PORT=25
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=

# ========== LDAP（默认禁用）==========
LDAP_ENABLED=False
LDAP_SERVER=
LDAP_BIND_DN=
LDAP_BIND_PASSWORD=
LDAP_SEARCH_BASE=
LDAP_USER_DN_TEMPLATE=

# ========== 内部定制开关 ==========
CUSTOM_ENABLE_DATA_MASKING=True
CUSTOM_ENABLE_AUDIT_LOG_ENHANCED=True
CUSTOM_INTERNAL_DEPT_SSO=False
EOF

    chown archery:archery "/opt/archery/${env}/.env"
    chmod 600 "/opt/archery/${env}/.env"
    echo "  OK  /opt/archery/${env}/.env ($(wc -c < /opt/archery/${env}/.env) bytes, $(stat -c %a /opt/archery/${env}/.env) perms)"
done

echo ""
echo "=== verify ==="
for env in dev staging prod; do
    echo "--- /opt/archery/${env}/.env ---"
    ls -la "/opt/archery/${env}/.env"
    echo "MYSQL_DB=$(grep '^MYSQL_DB=' /opt/archery/${env}/.env)"
    echo "REDIS_HOST=$(grep '^REDIS_HOST=' /opt/archery/${env}/.env)"
    echo "SECRET_KEY length=$(grep '^SECRET_KEY=' /opt/archery/${env}/.env | cut -d= -f2 | wc -c)"
    echo ""
done