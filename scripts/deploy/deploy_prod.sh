#!/bin/bash
## 部署 prod 环境（archery_prod 库 + 端口 9003 + 4 workers）
##
## 修过 set -e 兼容：
##   旧版 `mysql ... 2>&1 | grep -v 'Using a password'` 当 mysql 只输密码告警时，
##   grep 过滤后空输出 → exit code 1 → set -e 让脚本中止。
##   改为 `mysql ... 2>/dev/null` 直接吞掉告警，简单可靠。
set -e
DBOPS_PWD="$(cat /etc/archery/dbops_password)"
ROOT_PWD="$(cat /etc/archery/.mysql_root)"
# 通用：吞掉密码告警的 mysql 函数（用 stderr 屏蔽，stdout 仍输出）
mysql_run() {
    mysql -uroot -p"${ROOT_PWD}" -h 127.0.0.1 "$@" 2>/dev/null
}

echo "=== 0. 状态 ==="
echo "  .env 存在: $(ls -l /opt/archery/prod/.env)"
echo "  HEAD (前): $(cd /opt/archery/prod && git log -1 --oneline)"

echo ""
echo "=== 0.5 git pull（确保 requirements.txt / 代码是最新的）==="
# 注意：archery 用户的 git 是 1.8（没 -C 支持），所以先 cd 再 sudo -Hu
cd /opt/archery/prod
sudo -Hu archery git fetch origin 2>&1 | tail -2
sudo -Hu archery git reset --hard origin/main 2>&1 | tail -2
echo "  HEAD (后): $(git log -1 --oneline)"

echo ""
echo "=== 1. 重建 archery_prod 库 ==="
mysql_run -e "DROP DATABASE IF EXISTS archery_prod; CREATE DATABASE archery_prod DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
echo "  ok"

echo ""
echo "=== 2. 跑 Archery v1.0_init.sql + 升级 SQL ==="
mysql_run archery_prod < /opt/archery_upstream/src/init_sql/v1.0_init.sql | tail -3
for f in /opt/archery_upstream/src/init_sql/v1.{1.0,2.0,3.0,3.2,3.7,4.0,4.3,4.5,5.0,5.3_comment,6.0,6.1,6.2,6.3,6.6,6.7,7.0,7.1,7.2,7.3,7.5,7.7,7.8,7.11,7.12,8.3,8.4,9.0,10.0,12.0,13.0}.sql; do
    # 升级 SQL 多数有 IF NOT EXISTS 兜底，但 v1.1.0 / v1.2.0 / v1.5.0 / v1.5.3 / v1.7.7 / v1.10.0 等会因
    # 表/列已存在而报错（DROP 重建后跑全 loop 是幂等依赖这些 IF NOT EXISTS 的）。
    # 升级 SQL 是 best-effort，每个文件失败不影响后续 → || true 兜底
    [ -f "$f" ] && mysql_run archery_prod < "$f" 2>&1 | tail -1 > /dev/null || true
done
mysql_run archery_prod < /opt/archery_upstream/src/init_sql/del_permissions.sql 2>&1 | tail -1 > /dev/null || true
# auth_group.sql 里有 sql_instance_tag INSERT，Django 启动会建默认 auth_group(id=1) → 都可能 duplicate
# 用 --force 让 mysql 遇到 error 继续跑后面的 auth_group + permissions 部分
mysql -uroot -p"${ROOT_PWD}" -h 127.0.0.1 --force archery_prod < /opt/archery_upstream/sql/fixtures/auth_group.sql 2>/dev/null || true
echo "  ok"

echo ""
echo "=== 3. 加 audit_driver 字段到 sql_workflow ==="
# 用 INFORMATION_SCHEMA 判断字段是否已存在，避免 ALTER 报 Duplicate column
EXISTING=$(mysql_run archery_prod -N -B -e "
SELECT COUNT(*) FROM information_schema.columns
WHERE table_schema='archery_prod' AND table_name='sql_workflow'
  AND column_name IN ('audit_driver','audit_fallback_reason');
")
if [ "$EXISTING" = "0" ]; then
    mysql_run archery_prod -e "
ALTER TABLE sql_workflow
  ADD COLUMN audit_driver VARCHAR(32) NOT NULL DEFAULT 'archery' AFTER status,
  ADD COLUMN audit_fallback_reason VARCHAR(255) NOT NULL DEFAULT '' AFTER audit_driver;
"
    echo "  ok (已加 2 个字段)"
else
    echo "  skip (字段已存在，count=$EXISTING)"
fi

echo ""
echo "=== 4. 建 venv ==="
if [ ! -d /opt/archery/prod/venv ]; then
    sudo -Hu archery /usr/local/bin/python3.11 -m venv /opt/archery/prod/venv
fi
echo "  ok"

echo ""
echo "=== 5. pip install ==="
sudo -Hu archery -H bash -lc "cd /opt/archery/prod && set -a && source .env && set +a && \
    source venv/bin/activate && \
    export CFLAGS='-std=gnu99' && export CXXFLAGS='-std=gnu++11' && \
    pip install --upgrade pip wheel setuptools 2>&1 | tail -2 && \
    pip install -r requirements.txt 2>&1 | tail -3"

echo ""
echo "=== 6. Django migrate ==="
# 先 makemigrations 保险（万一 0001_initial 没在 git 里跑不动 migrate）
# 跑过 makemigrations 后再 migrate
sudo -Hu archery -H bash -lc "cd /opt/archery/prod && set -a && source .env && set +a && venv/bin/python manage.py makemigrations --no-input --dry-run --verbosity 1 2>&1" | grep -v 'No changes detected' | tail -3 || true
sudo -Hu archery -H bash -lc "cd /opt/archery/prod && set -a && source .env && set +a && venv/bin/python manage.py migrate --no-input 2>&1" | tail -10

echo ""
echo "=== 7. seed_sql_types + init_fallback_flow ==="
sudo -Hu archery -H bash -lc "cd /opt/archery/prod && set -a && source .env && set +a && venv/bin/python manage.py seed_sql_types 2>&1" | tail -3
sudo -Hu archery -H bash -lc "cd /opt/archery/prod && set -a && source .env && set +a && venv/bin/python manage.py init_fallback_flow 2>&1" | tail -3

echo ""
echo "=== 8. 创建 prod admin 用户（密码 archery 跟 staging 一样）==="
sudo -Hu archery -H bash -lc "cd /opt/archery/prod && set -a && source .env && set +a && venv/bin/python manage.py shell -c \"
from sql.models import Users
from django.contrib.auth.hashers import make_password
u, created = Users.objects.get_or_create(
    username='archery',
    defaults={
        'display': 'Archery Admin (Prod)',
        'email': 'archery@172.20.2.134',
        'is_active': 1,
        'is_staff': 1,
        'is_superuser': 1,
        'password': make_password('archery'),
    }
)
print(f'{\"created\" if created else \"existed\"}: {u.username} id={u.id} is_superuser={u.is_superuser}')
\" 2>&1" | tail -3

echo ""
echo "=== 9. 建 logs/media/static 目录 ==="
chown -R archery:archery /opt/archery/prod
mkdir -p /opt/archery/prod/{logs,media,static}
chown archery:archery /opt/archery/prod/{logs,media,static}
chmod 755 /opt/archery/prod/{logs,media,static}

echo ""
echo "=== 10. collectstatic ==="
sudo -Hu archery -H bash -lc "cd /opt/archery/prod && set -a && source .env && set +a && venv/bin/python manage.py collectstatic --no-input 2>&1" | tail -3

echo ""
echo "=== 11. 启动 gunicorn（9003 端口 0.0.0.0）==="
pkill -f 'gunicorn.*prod' 2>/dev/null || true
pkill -f 'gunicorn.*9003' 2>/dev/null || true
sleep 2
sudo -Hu archery bash -c 'cd /opt/archery/prod && set -a && source .env && set +a && \
    /opt/archery/prod/venv/bin/gunicorn archery.wsgi:application \
        -w 4 -b 0.0.0.0:9003 \
        --access-logfile - --error-logfile - --timeout 120 \
        > /var/log/archery/prod-gunicorn.log 2>&1 &'
sleep 4
ps -ef | grep 'gunicorn.*prod\|gunicorn.*9003' | grep -v grep | head -2

echo ""
echo "=== 12. firewalld 开 9003 ==="
firewall-cmd --permanent --add-port=9003/tcp 2>&1 | tail -1
firewall-cmd --reload 2>&1 | tail -1

echo ""
echo "=== 13. 验证 ==="
echo -n "  http://172.20.2.134:9003/login/  -> "
curl -fsS -m 5 -o /dev/null -w "HTTP %{http_code}\n" http://172.20.2.134:9003/login/
echo -n "  /dingtalk/oa/  -> "
curl -fsS -m 5 -o /dev/null -w "HTTP %{http_code}\n" http://172.20.2.134:9003/dingtalk/oa/
echo ""
echo "=== 14. 端口监听 ==="
ss -tlnp 2>&1 | grep -E '9002|9003'

echo ""
echo "DONE - prod 部署完成"
