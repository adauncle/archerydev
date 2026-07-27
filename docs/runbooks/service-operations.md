# 服务启停操作手册

> Archery 二次开发项目的服务运维速查手册。所有命令都针对生产服务器 **172.20.2.134**（CentOS 7.9，root 权限）。

## 服务清单

| 服务 | 端口/路径 | 启动方式 | 进程模型 |
|------|----------|---------|---------|
| Archery prod gunicorn | `0.0.0.0:9003` | **systemd** (`archery-prod-gunicorn.service`) | 1 master + 4 workers |
| firewalld | 系统服务 | `systemctl` | — |
| MySQL 8.0 | `127.0.0.1:3306` | `systemctl` | — |
| Redis 3.2 | `127.0.0.1:6379` | `systemctl` | — |
| cloudflared | 系统服务（按需） | `systemctl --user` | 钉钉 OA 回调用 |

> v0.1.1+ 改用 systemd 管理 gunicorn。Celery 仍不用（项目用 `django-q2`）。

## 服务启停速查

### 1. Archery prod gunicorn（9003）— ⭐ systemd 管理

```bash
# === 查状态 ===
ssh root@172.20.2.134 "systemctl status archery-prod-gunicorn.service"
ssh root@172.20.2.134 "systemctl is-active archery-prod-gunicorn.service"
ssh root@172.20.2.134 "curl -sS -m 5 -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:9003/login/"

# === 启动 ===
ssh root@172.20.2.134 "systemctl start archery-prod-gunicorn.service"

# === 优雅停止（master 收到 SIGTERM，通知 workers drain，默认 30s 超时）===
ssh root@172.20.2.134 "systemctl stop archery-prod-gunicorn.service"

# === 重启（stop + start，等同于 systemctl restart）===
ssh root@172.20.2.134 "systemctl restart archery-prod-gunicorn.service"

# === 看日志（journalctl，systemd 接管后的 gunicorn 输出都在这）===
ssh root@172.20.2.134 "journalctl -u archery-prod-gunicorn.service -f"
ssh root@172.20.2.134 "journalctl -u archery-prod-gunicorn.service --since '1 hour ago'"

# === 启用/禁用开机自启 ===
ssh root@172.20.2.134 "systemctl enable archery-prod-gunicorn.service"   # 开机自启
ssh root@172.20.2.134 "systemctl disable archery-prod-gunicorn.service"  # 取消自启
```

**unit 文件位置**：`/etc/systemd/system/archery-prod-gunicorn.service`
**源码**：`scripts/deploy/systemd/archery-prod-gunicorn.service`（项目仓库）
**PID 由 systemd 托管**：`systemctl status` 里 `Main PID` 就是 master

**修改 unit 文件后的生效流程**：
```bash
ssh root@172.20.2.134
# 1. 编辑文件（或 scp 上传新版本）
# 2. 重载 systemd
systemctl daemon-reload
# 3. 重启服务
systemctl restart archery-prod-gunicorn.service
```

**开机自启已配置**：`systemctl is-enabled archery-prod-gunicorn.service` 应返回 `enabled`。

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

### 5. qcluster（django-q2 异步任务 worker，v0.1.9+ 必装）

负责消费 `redis://127.0.0.1:6379/0` 的 `django_q:archery:q` 队列，跑：
- 提交工单后的钉钉通知 (`notify_for_audit`)
- SQL 工单审批流转
- 各种异步任务 (`sqlreview-pass-*`, `sqlreview-submit-*`)

**没装 qcluster → 钉钉通知全部丢失，但页面提交仍"成功"（silent 失败）**。

```bash
# === 查状态 ===
ssh root@172.20.2.134 "systemctl status archery-prod-qcluster"
ssh root@172.20.2.134 "systemctl is-active archery-prod-qcluster"

# === 启停 ===
ssh root@172.20.2.134 "systemctl {start|stop|restart|enable} archery-prod-qcluster"

# === 看 7 个 worker 子进程 + 1 个 pusher + 1 个 monitor ===
ssh root@172.20.2.134 "ps -ef | grep 'manage.py qcluster' | grep -v grep"
# 应该看到 1 主 + 7 子进程 = 4 worker + 1 monitor + 1 pusher + 1 guard + 1 sentinel (django-q2 默认 4 workers)

# === 看 redis 队列消费 ===
ssh root@172.20.2.134 'redis-cli -a $(cat /etc/archery/redis_password) LLEN django_q:archery:q'
# 应该接近 0；如果 > 0 持续增长，说明 worker 没在消费
ssh root@172.20.2.134 'redis-cli -a $(cat /etc/archery/redis_password) INFO clients | grep blocked_clients'
# 应该 = 1 (BLPOP 阻塞等待)；如果 = 0 说明 worker 全部 idle 死掉

# === 看日志（INFO 级别，qcluster 专用） ===
ssh root@172.20.2.134 "journalctl -u archery-prod-qcluster -f"
ssh root@172.20.2.134 "tail -f /opt/archery/prod/logs/qcluster.log"
# 关键关键字: "ready for work", "processing", "Processed", "钉钉 OA 工作通知发送成功"
```

**故障排查**：

| 症状 | 检查 | 解决 |
|------|------|------|
| 提交工单后马克群没收到通知 | `LLEN django_q:archery:q` 持续 > 0 | `systemctl start archery-prod-qcluster` |
| 任务执行失败 | `qcluster.log` 看 "Error"/"Traceback" 行 | 看具体堆栈，可能需要重启 worker |
| redis 密码变了 | `Q_CLUSTER.django_redis="default"` 用 `CACHES.default` | 改 `archery_prod` 的 `.env` 的 `CACHE_URL`，重启 qcluster + gunicorn |
| 任务被消费但没发通知 | `archery.log` 搜 `ding_to_person` / `GroupDingtalkAuditor` | 看 v0.1.7 `GroupDingtalkAuditor` 配置是否正确 |



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
# Archery prod gunicorn 日志（systemd 接管后用 journalctl 查）
journalctl -u archery-prod-gunicorn.service -f           # 实时跟踪
journalctl -u archery-prod-gunicorn.service -n 100       # 最近 100 条
journalctl -u archery-prod-gunicorn.service --since today

# 如果 journalctl 没启用，旧的 /var/log/archery/prod-gunicorn.log 还有
# （v0.1.1+ 改 systemd 后这个文件不会再写，但保留作 fallback）

# Archery qcluster 异步 worker 日志（v0.1.9+ 才有）
journalctl -u archery-prod-qcluster.service -f
/opt/archery/prod/logs/qcluster.log     # INFO 级别日志，qcluster 专用

# Archery Web 业务日志（gunicorn 进程 + qcluster 进程都写这里）
/opt/archery/prod/logs/archery.log      # 100MB × 5 滚动

# 部署日志
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
# systemd 一行搞定
ssh root@172.20.2.134 "systemctl restart archery-prod-gunicorn.service"

# 验证
ssh root@172.20.2.134 "systemctl status archery-prod-gunicorn.service --no-pager"
ssh root@172.20.2.134 "curl -sS -m 5 -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:9003/login/"
```

### 场景 3：紧急下线（保留数据）

```bash
# 只关 gunicorn，不动数据库
ssh root@172.20.2.134 "systemctl stop archery-prod-gunicorn.service"

# 同时关端口（防止误访问）
ssh root@172.20.2.134 "firewall-cmd --permanent --remove-port=9003/tcp && \
    firewall-cmd --reload"

# 重新启用
ssh root@172.20.2.134 "firewall-cmd --permanent --add-port=9003/tcp && \
    firewall-cmd --reload && \
    systemctl start archery-prod-gunicorn.service"
```

### 场景 4：清空 prod 重新部署

```bash
# 跑 scripts/deploy/deploy_prod.sh（在 172.20.2.134 上）
# 会 DROP DATABASE archery_prod → 跑 SQL init → venv → pip install → migrate → seed
# 部署完成后 systemd 启动要手动做（因为 deploy 脚本会 pkill 老 gunicorn）：
ssh root@172.20.2.134 "bash /tmp/deploy_prod.sh"
ssh root@172.20.2.134 "systemctl daemon-reload"   # 重新加载 unit
ssh root@172.20.2.134 "systemctl restart archery-prod-gunicorn.service"
# ⚠️ 首次部署 OK，重跑前确认 prod 没数据
```

### 场景 5：手动从 staging 切回 prod（如果以后又想开 staging）

```bash
# 写一个 archery-staging-gunicorn.service（参考 prod 单元，9002 端口、-w 2）
# 复制 prod unit 改路径和端口即可

ssh root@172.20.2.134 "firewall-cmd --permanent --add-port=9002/tcp && \
    firewall-cmd --reload"

ssh root@172.20.2.134 "systemctl daemon-reload"
ssh root@172.20.2.134 "systemctl enable --now archery-staging-gunicorn.service"
```

## 进程管理坑位（不要踩）

1. **systemd 219 (CentOS 7) "Unit not found" cache bug** —— `daemon-reexec` 或 `daemon-reload` 后 `start` 仍报 "Unit not found"（即使 `list-units` 显示 loaded）。  
   解决：unit 文件**保持最简**（17 行就够），不要用 ProtectSystem/ReadWritePaths 这些 systemd 230+ 才稳定的指令。SELinux context 必须是 `systemd_unit_file_t`（`chcon -t systemd_unit_file_t`）。
2. **dbops.service 死循环** —— 同服务器上的 dbops.service 找不到 uvicorn，每 10s 重启一次，会占满 systemd job queue，导致 archery unit 启动异常。  
   解决：第一次部署时 `systemctl disable --now dbops.service` 停掉（如果不是你们在用的服务）。
3. **gunicorn 没写 PID 文件** —— master 进程由 systemd 托管，`Main PID` 在 `systemctl status` 里看，不要去找 `/var/run/archery.pid`。
4. **`sudo -Hu archery` 后 PATH 改了** —— systemd unit 里用 `ExecStart=/opt/archery/prod/venv/bin/gunicorn ...` 完整路径，不要 `ExecStart=gunicorn ...`。
5. **`archery` 用户 git 1.8 没 `-C` 支持** —— 复杂 git 操作先 `cd DIR && sudo -Hu archery git ...`。
6. **firewalld `--permanent` 必须 `--reload` 才生效** —— 临时改 `--add-port` 不带 permanent 立即生效但 reload 后丢。
7. **Archery v0.1.1+ 不再单独管理 celery worker** —— 项目用 django-q2 替代 Celery，不需要 worker 进程。

## 应急联系

- 服务器 SSH：`ssh root@172.20.2.134`（key 在 `C:\Users\hly\.ssh\archery_deploy`）
- archery 用户 SSH：`ssh archery@172.20.2.134`（同 key）
- GitHub 仓库：https://github.com/adauncle/archerydev
- 钉钉 OA 平台：https://open-dev.dingtalk.com/
