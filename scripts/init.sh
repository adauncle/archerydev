#!/usr/bin/env bash
# 一键初始化本地开发环境

set -e

cd "$(dirname "$0")/.."

echo "==> 1. 检查 .env"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已生成 .env，请编辑后重新执行本脚本"
  exit 0
fi

echo "==> 2. 启动依赖服务"
docker-compose up -d mysql redis

echo "==> 3. 等待 MySQL 就绪"
for i in {1..30}; do
  if docker-compose exec -T mysql mysqladmin ping -h localhost -u root -p${MYSQL_ROOT_PASSWORD:-rootpass} >/dev/null 2>&1; then
    echo "MySQL ready"
    break
  fi
  echo "waiting... ($i/30)"
  sleep 2
done

echo "==> 4. 启动应用栈"
docker-compose up -d --build

echo "==> 5. 跑迁移"
docker-compose exec -T archery python manage.py migrate --noinput

echo "==> 6. 加载初始数据"
docker-compose exec -T archery python manage.py loaddata initial_data || echo "(skip loaddata)"

echo "==> 完成！访问 http://localhost"
