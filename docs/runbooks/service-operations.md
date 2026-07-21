# 服务启停操作手册

> Archery 二次开发项目的服务运维速查手册。所有命令都针对生产服务器 **172.20.2.134**（CentOS 7.9，root 权限）。

## 服务清单

| 服务 | 端口/路径 | 启动方式 | 进程模型 |
|------|----------|---------|---------|
| Archery prod gunicorn | `0.0.0.0:9003` | `nohup` + `bash -c`（不用 systemd） | 1 master + 4 workers |
| firewalld | 系统服务 | `systemctl` | — |
| MySQL 8.0 | `127.0.0.1:3306` | `systemctl` | — |
| Redis 3.2 | `127.0.0.1:6379` | `systemctl` | — |
| cloudflared | 系统服务（按需） | `systemctl --user` | 钉钉 OA 回调用 |

> ⚠️ Archery v0.1.0+ 不再用 systemd 跑 gunicorn（CentOS 7 systemd 219 有 cache bug，且部署流程走 `nohup` 更直接）。Celery 也没启用（项目用 `django-q2`）。

## 服务启停速查

### 1. Archery prod gunicorn（9003）

```bash
# === 查状态 ===
ssh root@172.20.2.134
ps -ef | grep 'gunicorn.*9003' | grep -v grep
ss -tlnp | grep ':9003 '
curl -sS -m 5 -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:9003/login/

# === 启动 ===
ssh root@172.20.2.134 "sudo -Hu archery bash -c 'cd /opt/archery/prod && \
    set -a && source .env && set +a && \
    /opt/archery/prod/venv/bin/gunicorn archery.wsgi:application \
        -w 4 -b 0.0.0.0:9003 \
        --access-logfile - --error-logfile - --timeout 120 \
        > /var/log/archery/prod-gunicorn.log 2>&1 &'"

# === 优雅停（SIGTERM，master 收到后通知 workers drain）===
ssh root@172.20.2.134 "pkill -TERM -f 'gunicorn.*9003'"
# 等 5 秒
ssh root@172.20.2.134 "sleep 5 && pgrep -f 'gunicorn.*9003' || echo '已全部退出'"

# === 强杀（SIGKILL，不优雅但立即生效）===
ssh root@172.20.2.134 "pkill -9 -f 'gunicorn.*9003'"

# === 重启（先停后启）===
ssh root@172.20.2.134 "pkill -TERM -f 'gunicorn.*9003' && sleep 5 && \
    sudo -Hu archery bash -c 'cd /opt/archery/prod && \
        set -a && source .env && set +a && \
        /opt/archery/prod/venv/bin/gunicorn archery.wsgi:application \
            -w 4 -b 0.0.0.0:9003 \
            --access-logfile - --error-logfile - --timeout 120 \
            > /var/log/archery/prod-gunicorn.log 2>&1 &'"
```

**PID 文件**：gunicorn 当前**没写 PID 文件**（没用 `--pid` 选项）。要查 master PID 用：
```bash
ssh root@172.20.2.134 "pgrep -f 'gunicorn.*9003' | head -1"
```

### 2. firewalld 端口管理

```bash
# === 查当前开放端口 ===
ssh root@172.20.2.134 "firewall-cmd --list-ports"

# === 临时开放（reload 后失效）===
ssh root@172.20.2.134 "firewall-cmd --add-port=9003/tcp"

# === 永久开放（写进配置，需要 --reload）===
ssh root@172.20.2.134 "firewall-cmd --permanent --add-port=9003/tcp && \
    firewall-cmd --reload"

# === 关闭端口 ===
ssh root@172.20.2.134 "firewall-cmd --permanent --remove-port=9002/tcp && \
    firewall-cmd --reload"

# === 查 22/80/443 这些服务型端口 ===
ssh root@172.20.2.134 "firewall-cmd --list-services"
```

**当前 prod 必备端口**：

| 端口 | 用途 |
|------|------|
| 22/tcp | SSH |
| 9003/tcp | Archery prod gunicorn |

> Archery v0.1.0+ 不用 nginx 反代，gunicorn 直接对外。如果将来加 nginx 反代到 80/443，再开对应端口。

### 3. MySQL 8.0

```bash
# === 查状态 ===
ssh root@172.20.2.134 "systemctl status mysqld"
ssh root@172.20.2.134 "systemctl is-active mysqld"

# === 启停 ===
ssh root@172.20.2.134 "systemctl start mysqld"   # 启动
ssh root@172.20.2.134 "systemctl stop mysqld"    # 停止
ssh root@172.20.2.134 "systemctl restart mysqld" # 重启
ssh root@172.20.2.134 "systemctl enable mysqld"  # 开机自启（已默认开启）

# === 查库连接 ===
ssh root@172.20.2.134 'cat /etc/archery/dbops_password | \
    xargs -I {} mysql -udbops -p{} -h 127.0.0.1 -e "SHOW DATABASES;" 2>/dev/null'
```

**数据库清单**：
- `archery_prod`（v0.1.0+ prod 唯一）
- `archery_staging`（v0.1.0 时用过，staging 已停但库保留）
- `archery_dev`（预留）
- `mysql` / `information_schema` / `performance_schema` / `sys`（系统库）

### 4. Redis 3.2

```bash
# === 查状态 ===
ssh root@172.20.2.134 "systemctl status redis"
ssh root@172.20.2.134 "redis-cli -a $(cat /etc/archery/redis_password) PING"
# 应回 PONG

# === 启停（与 MySQL 同）===
ssh root@172.20.2.134 "systemctl {start|stop|restart|enable} redis"
```

### 5. cloudflared（钉钉 OA 回调用，按需启动）

```bash
# === 启动 tunnel（需要先在 cloudflare 后台配好 tunnel） ===
ssh archery@172.20.2.134 "systemctl --user start cloudflared"
ssh archery@172.20.2.134 "systemctl --user status cloudflared"

# === 停 / 重启 ===
ssh archery@172.20.2.134 "systemctl --user {stop|restart} cloudflared"

# === 看 tunnel 状态（需要 cloudflared 配置文件） ===
ssh archery@172.20.2.134 "cloudflared tunnel info <tunnel-name>"
```

> cloudflared 是 `--user` 模式（archery 用户），不能用 root 启。

## 日志位置

```bash
# Archery prod 访问/错误日志（gunicorn --access-logfile - --error-logfile - 重定向到文件）
/var/log/archery/prod-gunicorn.log

# Archery 部署日志
/var/log/archery/deploy_prod.log
/var/log/archery/deploy_staging.log    # 历史

# 服务器初始化日志
/var/log/archery/init.log

# MySQL 慢查询 + 错误日志
/var/log/mysqld.log

# Redis 日志
/var/log/redis/redis.log

# cloudflared 日志（--user 模式）
journalctl --user -u cloudflared -f
```

## 常见运维场景

### 场景 1：发新版本（push → 自动部署）

```bash
# 1. 本地 commit + push（自动触发 GitHub Actions cd-prod workflow）
cd G:\MiniMax工作空间\archery_dev
git add .
git commit -m "feat: ..."
git push origin main

# 2. 走 GitHub Environment approval 页面手动批准
# 3. 等待 CD 跑完，访问 https://github.com/adauncle/archerydev/actions 看进度
# 4. 验证：浏览器打开 http://172.20.2.134:9003/login/ 看新功能
```

### 场景 2：手动重启 prod（不动代码）

```bash
# SSH 上去，杀 gunicorn，起新 gunicorn
ssh root@172.20.2.134 <<'EOF'
pkill -TERM -f 'gunicorn.*9003'
sleep 5
sudo -Hu archery bash -c 'cd /opt/archery/prod && \
    set -a && source .env && set +a && \
    /opt/archery/prod/venv/bin/gunicorn archery.wsgi:application \
        -w 4 -b 0.0.0.0:9003 \
        --access-logfile - --error-logfile - --timeout 120 \
        > /var/log/archery/prod-gunicorn.log 2>&1 &'
sleep 4
echo "=== 状态 ==="
ps -ef | grep 'gunicorn.*9003' | grep -v grep
ss -tlnp | grep ':9003 '
EOF
```

### 场景 3：紧急下线（保留数据）

```bash
# 只关 gunicorn，不动数据库
ssh root@172.20.2.134 "pkill -TERM -f 'gunicorn.*9003' && sleep 5 && \
    pgrep -f 'gunicorn.*9003' || echo '已全部退出'"

# 同时关端口
ssh root@172.20.2.134 "firewall-cmd --permanent --remove-port=9003/tcp && \
    firewall-cmd --reload"
```

### 场景 4：清空 prod 重新部署

```bash
# 跑 scripts/deploy/deploy_prod.sh（在 172.20.2.134 上）
# 会 DROP DATABASE archery_prod → 跑 SQL init → venv → pip install → migrate → seed → 启 gunicorn
# ⚠️ 首次部署 OK，重跑前确认 prod 没数据
ssh root@172.20.2.134 "bash /tmp/deploy_prod.sh"
```

### 场景 5：从 prod 切回 staging（如果以后又想开 staging）

```bash
# 启 staging gunicorn（目录和 venv 都在 /opt/archery/staging）
ssh root@172.20.2.134 "firewall-cmd --permanent --add-port=9002/tcp && \
    firewall-cmd --reload"

ssh root@172.20.2.134 "sudo -Hu archery bash -c 'cd /opt/archery/staging && \
    set -a && source .env && set +a && \
    /opt/archery/staging/venv/bin/gunicorn archery.wsgi:application \
        -w 2 -b 0.0.0.0:9002 \
        --access-logfile - --error-logfile - --timeout 120 \
        > /var/log/archery/staging-gunicorn.log 2>&1 &'"
```

## 进程管理坑位（不要踩）

1. **`pkill -9 -f 'gunicorn.*9003'` 在 ssh 内部用可能杀掉父 bash** —— 用 `pgrep` 先拿 PID 再 `kill`
2. **gunicorn 没写 PID 文件** —— 没法用 `kill $(cat /var/run/archery.pid)`，必须用 pgrep
3. **systemd 219 (CentOS 7) cache bug** —— `systemctl daemon-reexec` 后 service unit 显示 "Unit not found"，所以 v0.1.0+ 改用 `nohup` 不走 systemd
4. **`sudo -Hu archery` 后 PATH 改了** —— 完整路径用 `/usr/local/bin/python3.11` 不用裸 `python`
5. **`archery` 用户 git 1.8 没 `-C` 支持** —— 复杂 git 操作先 `cd DIR && sudo -Hu archery git ...`
6. **firewalld `--permanent` 必须 `--reload` 才生效** —— 临时改 `--add-port` 不带 permanent 立即生效但 reload 后丢

## 应急联系

- 服务器 SSH：`ssh root@172.20.2.134`（key 在 `C:\Users\hly\.ssh\archery_deploy`）
- archery 用户 SSH：`ssh archery@172.20.2.134`（同 key）
- GitHub 仓库：https://github.com/adauncle/archerydev
- 钉钉 OA 平台：https://open-dev.dingtalk.com/
