# `scripts/deploy/` —— 部署与运维脚本

> 本目录下的脚本是**模板/源文件**，由 CI/CD 或运维同事 push 到服务器（`172.20.2.134`）。
> 不要在开发机上直接执行；服务器上由 systemd / cron 触发。

## 目录结构

```
scripts/
├── deploy/                          # 部署相关
│   ├── 04_backup.sh                 # 每日备份（MySQL + GPG + media + 30d 保留）
│   ├── README.md                    # 本文件
│   └── systemd/                     # systemd 单元模板
│       ├── archery-monitor.timer
│       ├── archery-monitor.service
│       ├── archery-prod-gunicorn.service        # 示例
│       └── archery-prod-celery-worker.service   # 示例
└── monitor/
    └── check_health.sh              # 健康检查（curl /healthz + 钉钉告警）
```

## 部署链路概览

> 完整设计见 [`docs/designs/2026-07-20_devops-cicd.md`](../../docs/designs/2026-07-20_devops-cicd.md)

```
开发者 push / tag
    │
    ▼
GitHub Actions
    │
    ▼ (SSH)
172.20.2.134
    ├── systemd
    │   ├── archery-{prod,staging,dev}-gunicorn.service
    │   ├── archery-{prod,staging,dev}-celery-worker.service
    │   ├── archery-{prod,staging,dev}-celery-beat.service
    │   ├── cloudflared.service        # 钉钉回调隧道
    │   └── archery-monitor.timer      # 健康检查（5 min）
    │
    └── cron / systemd timer
        └── /opt/archery/scripts/deploy/04_backup.sh  # 每日 02:00 备份
```

## 脚本清单

| 文件 | 用途 | 触发方式 | 设计依据 |
|------|------|----------|----------|
| `04_backup.sh` | MySQL dump + GPG 加密 + media 打包 + 30 天清理 | systemd timer（推荐）/ cron 0 2 * * * | §7.3 |
| `monitor/check_health.sh` | curl `/healthz`，失败推钉钉 | systemd timer（每 5 min）| §7.2 |

> **注**：`01_init_server.sh`（服务器初始化）、`02_deploy.sh`（应用部署）、`03_rollback.sh`（回滚）见 §4、§5、§8.2，本 PR 暂不交付（按节奏分批）。

## 配置文件约定

所有敏感信息通过**文件路径**传递，绝不硬编码到脚本中：

| 文件 | 用途 | 由谁生成 | 权限 |
|------|------|----------|------|
| `/opt/archery/prod/.env` | Django + MySQL + Redis 凭据 | 运维手动创建（`cp .env.example .env` + 编辑） | `600 archery:archery` |
| `/etc/archery/backup_passphrase` | GPG 备份加密密码 | `01_init_server.sh` 自动生成 | `600 root:root` |
| `/etc/archery/dingtalk_webhook` | 钉钉通知 webhook | 运维手动写入 | `600 root:root` |
| `/etc/archery/redis_password` | Redis 密码 | `01_init_server.sh` 自动生成 | `600 root:root` |

## systemd 单元部署

### 一次性部署（运维手工）

```bash
# 1. ssh 到服务器
ssh archery@172.20.2.134

# 2. 创建脚本目录（如果不存在）
sudo mkdir -p /opt/archery/scripts/{deploy,monitor}
sudo mkdir -p /opt/archery/scripts/deploy/systemd
sudo chown -R archery:archery /opt/archery/scripts

# 3. 由 CI/CD 或 git pull 同步最新脚本
cd /opt/archery
git pull origin main

# 4. 复制 systemd 单元
sudo cp scripts/deploy/systemd/archery-monitor.{timer,service} /etc/systemd/system/
sudo cp scripts/deploy/systemd/archery-prod-*.service /etc/systemd/system/

# 5. 设置可执行权限
sudo chmod +x /opt/archery/scripts/deploy/04_backup.sh
sudo chmod +x /opt/archery/scripts/monitor/check_health.sh

# 6. 重新加载 systemd
sudo systemctl daemon-reload

# 7. 启用并启动
sudo systemctl enable --now archery-monitor.timer
sudo systemctl enable --now archery-prod-gunicorn.service
sudo systemctl enable --now archery-prod-celery-worker.service

# 8. 验证
systemctl list-timers archery-monitor.timer
systemctl status archery-prod-gunicorn.service
curl -fsS http://127.0.0.1:9003/healthz
```

### 备份的 systemd timer（推荐方式）

> 比 cron 更现代（journald 日志、依赖管理、错过补跑）。

**还没交付**——按 v0.9 实施路线图（§10 阶段 8）下一步提供：
- `scripts/deploy/systemd/archery-backup.timer`
- `scripts/deploy/systemd/archery-backup.service`

**临时使用 cron 的写法**（如果 systemd timer 还没部署）：

```bash
# /etc/cron.d/archery-backup
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

0 2 * * * root /opt/archery/scripts/deploy/04_backup.sh >> /var/log/archery/backup.log 2>&1
```

## 验证脚本语法

在开发机（Windows + PowerShell）上用 WSL/Git Bash：

```bash
# 语法检查
bash -n scripts/deploy/04_backup.sh
bash -n scripts/monitor/check_health.sh

# （可选）shellcheck 更严格
shellcheck scripts/deploy/04_backup.sh
shellcheck scripts/monitor/check_health.sh
```

## 关键设计点

### 备份脚本（`04_backup.sh`）

- **GPG 对称加密**（`AES256` + `--pinentry-mode loopback`）—— 可在脚本中自动化，无需人工输入密码
- **临时文件清理**（`trap cleanup EXIT`）—— 即使中途失败也不留明文 dump
- **失败告警** —— `die()` 函数同时记录日志和推钉钉
- **manifest 文件** —— 备份目录里同时有 `backup_<时间戳>.manifest` 记录元数据，便于恢复时识别
- **可调参数** —— 所有路径、超时、保留天数都可通过环境变量覆盖

### 健康检查（`check_health.sh`）

- **告警节流**（`ALERT_COOLDOWN=300s`）—— 同一故障 5 分钟内只发一次钉钉，避免刷屏
- **失败重试**（默认 2 次）—— 避免网络抖动导致误报
- **curl 错误分类** —— 区分 `connection refused` / `timeout` / `5xx`，生成不同告警指纹
- **强制只读** —— 纯 GET 请求，对服务零侵入

### systemd 安全加固

所有 service 文件都启用：
- `NoNewPrivileges=true` —— 禁止提权
- `ProtectSystem=strict` —— 文件系统只读
- `ProtectHome=true` —— 隔离 /home
- `PrivateTmp=true` —— 隔离 /tmp
- `ReadWritePaths=...` —— 白名单可写目录

## 故障排查

```bash
# 看健康检查日志
journalctl -u archery-monitor.service -f

# 看健康检查 timer 状态
systemctl list-timers archery-monitor.timer

# 手动跑一次健康检查
/opt/archery/scripts/monitor/check_health.sh

# 看备份日志
tail -f /var/log/archery/backup.log

# 手动跑一次备份（要 root）
sudo /opt/archery/scripts/deploy/04_backup.sh

# 验证 GPG 加密文件可解密
GPG_PASSPHRASE=$(sudo cat /etc/archery/backup_passphrase)
gpg --batch --pinentry-mode loopback --passphrase "${GPG_PASSPHRASE}" \
    -d /opt/archery/shared/backups/mysql_20260720_020000.sql.gpg | head -20

# 恢复 MySQL
gpg -d mysql_20260720_020000.sql.gpg | mysql -h 172.20.2.134 -u dbops -p

# 恢复 media
tar -xzf media_20260720_020000.tar.gz -C /opt/archery/shared/
```

## 关联 changelog

- `docs/changelogs/2026-07-20_devops-backup-monitor.md` —— 本次交付
- `docs/changelogs/2026-07-20_v0.9-devops-decisions.md` —— 12 个决策落档
- `docs/changelogs/2026-07-20_design-devops-cicd.md` —— 设计文档落档
