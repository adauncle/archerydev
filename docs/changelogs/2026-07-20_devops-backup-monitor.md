# 每日备份脚本 + 健康检查 systemd timer

**日期**：2026-07-20
**作者**：devops-agent（Mavis 辅助生成）+ 项目 owner
**影响范围**：`scripts/deploy/`、`scripts/monitor/`、`docs/changelogs/`
**风险等级**：低（纯新增文件，不改上游核心）

## 背景

按 v0.9 DevOps/CI-CD 设计（`docs/designs/2026-07-20_devops-cicd.md` §7.2 + §7.3），需要落地两份运维脚本：

1. **每日备份** —— MySQL dump + GPG 加密 + media 打包 + 30 天清理
2. **健康检查 systemd timer** —— 每 5 分钟 curl `/healthz`，失败推钉钉

本次 PR 只交付这两块，**不动**服务器初始化（§4）、应用部署（§5.1）、回滚（§8.2）—— 那些按 v0.9 实施路线图分批交付。

## 改动内容

### 新增文件

| 文件 | 行数 | 用途 |
|------|------|------|
| `scripts/deploy/04_backup.sh` | ~250 | 每日备份主脚本 |
| `scripts/monitor/check_health.sh` | ~180 | 健康检查主脚本 |
| `scripts/deploy/systemd/archery-monitor.timer` | ~30 | 健康检查定时器（每 5 min） |
| `scripts/deploy/systemd/archery-monitor.service` | ~50 | 健康检查执行单元 |
| `scripts/deploy/systemd/archery-prod-gunicorn.service` | ~60 | 生产 gunicorn（示例） |
| `scripts/deploy/systemd/archery-prod-celery-worker.service` | ~50 | 生产 celery worker（示例） |
| `scripts/deploy/README.md` | ~170 | 部署/运维使用说明 |
| `docs/changelogs/2026-07-20_devops-backup-monitor.md` | 本文件 | 变更日志 |

### 关键设计点

#### 备份脚本（`04_backup.sh`）

- **凭据不硬编码**：从 `/opt/archery/prod/.env` 读取 `MYSQL_HOST/PORT/USER/PASSWORD`，GPG 密码从 `/etc/archery/backup_passphrase` 读取
- **GPG 对称加密**：`AES256` + `--pinentry-mode loopback` —— 可在脚本中自动化
- **临时文件清理**：`trap cleanup EXIT` —— 即使中途失败也不留明文 dump
- **失败告警**：`die()` 函数同时记录日志和推钉钉
- **manifest 文件**：每次备份生成 `backup_<时间戳>.manifest` 记录元数据（数据库列表、文件大小、版本号），便于恢复时识别
- **可调参数**：所有路径、超时、保留天数都可通过环境变量覆盖（`BACKUP_DIR` / `KEEP_DAYS` / `BACKUP_DATABASES` 等）
- **跨平台兼容**：`stat` 同时支持 Linux（`%s`）和 macOS（`%z`），方便在开发机调试

#### 健康检查（`check_health.sh`）

- **告警节流**（`ALERT_COOLDOWN=300s`）—— 同一故障 5 分钟内只发一次钉钉，避免刷屏
- **失败重试**（默认 2 次，间隔 2s）—— 避免网络抖动导致误报
- **curl 错误分类** —— 区分 `connection refused` / `timeout` / `5xx`，生成不同告警指纹
- **强制只读**：纯 GET 请求，对服务零侵入
- **退出码语义化**：`0` 健康 / `1` 检查失败 / `2` 配置错误（方便 systemd 和 CI/CD 区分处理）

#### systemd 单元

- **安全加固**：所有 service 启用 `NoNewPrivileges` / `ProtectSystem=strict` / `ProtectHome` / `PrivateTmp` / `ReadWritePaths` 白名单
- **资源限制**：`MemoryMax=2G`（gunicorn/celery）/ `128M`（monitor），`CPUQuota=10%`（monitor 不应占用太多 CPU）
- **timer 持久化**：`Persistent=true` —— 系统关机错过触发时，开机后补跑一次
- **示例文件**：`archery-prod-gunicorn.service` 和 `archery-prod-celery-worker.service` 是演示用，staging/dev 可由本文件派生（替换路径、端口、worker 数）

## 涉及文件

```
scripts/
├── deploy/
│   ├── 04_backup.sh                       (新增, ~250 行)
│   ├── README.md                          (新增, ~170 行)
│   └── systemd/
│       ├── archery-monitor.timer           (新增, ~30 行)
│       ├── archery-monitor.service         (新增, ~50 行)
│       ├── archery-prod-gunicorn.service   (新增, ~60 行, 示例)
│       └── archery-prod-celery-worker.service (新增, ~50 行, 示例)
└── monitor/
    └── check_health.sh                    (新增, ~180 行)

docs/
└── changelogs/
    └── 2026-07-20_devops-backup-monitor.md (本文件)
```

**未修改任何已有文件**（包括 `AGENTS.md`、`docs/customization.md`、上游 Archery 源码）。

## 验证清单

- [x] `bash -n scripts/deploy/04_backup.sh` 通过
- [x] `bash -n scripts/monitor/check_health.sh` 通过
- [x] 脚本头包含 `set -euo pipefail`
- [x] 真实凭据用占位符（`${MYSQL_PASSWORD}` 来自 `.env`，GPG 密码来自 `/etc/archery/backup_passphrase`）
- [x] 文件路径用变量（`${BACKUP_DIR}` / `${MEDIA_DIR}` / `${LOG_FILE}` 等）
- [x] 幂等性：可多次跑不出问题（同名文件覆盖、清理逻辑只看 `mtime`、trap 清理临时文件）
- [x] 关键命令有错误处理（`mysqldump` / `gpg` / `tar` / `curl` 都有失败检测）
- [x] systemd 单元有安全加固（`NoNewPrivileges` / `ProtectSystem` / `MemoryMax`）

## 部署步骤（运维执行）

```bash
# 1. SSH 到服务器
ssh archery@172.20.2.134

# 2. 拉取最新代码
cd /opt/archery && git pull origin main

# 3. 设置可执行权限
sudo chmod +x scripts/deploy/04_backup.sh
sudo chmod +x scripts/monitor/check_health.sh

# 4. 部署 systemd 单元
sudo cp scripts/deploy/systemd/archery-monitor.{timer,service} /etc/systemd/system/
sudo cp scripts/deploy/systemd/archery-prod-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now archery-monitor.timer

# 5. 配置定时备份（临时用 cron，systemd timer 下次 PR 交付）
echo "0 2 * * * root /opt/archery/scripts/deploy/04_backup.sh >> /var/log/archery/backup.log 2>&1" \
    | sudo tee /etc/cron.d/archery-backup

# 6. 验证
systemctl list-timers archery-monitor.timer
curl -fsS http://127.0.0.1:9003/healthz
sudo /opt/archery/scripts/deploy/04_backup.sh --dry-run  # 手动跑一次
```

## 回滚方案

```bash
# 回滚本次提交（不影响服务器，因为服务器上脚本是独立 push）
git revert HEAD  # 或 git reset --hard HEAD~1

# 服务器上清理（如果已经部署）
sudo systemctl disable --now archery-monitor.timer
sudo rm /etc/systemd/system/archery-monitor.{timer,service}
sudo systemctl daemon-reload
```

## 后续工作（按 v0.9 路线图）

- [ ] `01_init_server.sh`（服务器初始化，§4）
- [ ] `02_deploy.sh`（应用部署，§5.1）
- [ ] `03_rollback.sh`（回滚，§8.2）
- [ ] `archery-backup.timer` + `archery-backup.service`（替代 cron 的 systemd 方式）
- [ ] `cloudflared.service`（钉钉回调隧道，§5.6）
- [ ] `.github/workflows/ci.yml` / `cd-staging.yml` / `cd-prod.yml`（CI/CD 流水线，§6）

## 关联文档

- [`docs/designs/2026-07-20_devops-cicd.md`](../../docs/designs/2026-07-20_devops-cicd.md) §7.2 / §7.3 —— 设计依据
- [`docs/customization.md`](../../docs/customization.md) §5 —— changelog 模板
- [`AGENTS.md`](../../AGENTS.md) —— 二次开发硬规则
- [`docs/changelogs/2026-07-20_v0.9-devops-decisions.md`](../../docs/changelogs/2026-07-20_v0.9-devops-decisions.md) —— 12 个决策落档
