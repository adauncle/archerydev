# 核心部署脚本 + 钉钉回调 systemd 单元

**日期**：2026-07-20
**作者**：devops-agent（Mavis 辅助生成）+ 项目 owner
**影响范围**：`scripts/deploy/`、`docs/changelogs/`
**风险等级**：中（新增可执行脚本；不部署到服务器前无副作用）

## 背景

按 v0.9 DevOps/CI-CD 设计（`docs/designs/2026-07-20_devops-cicd.md` §4 / §5.1 / §5.6 / §8.2），
需要在第二批 demo 任务里交付：

1. **服务器初始化脚本**（§4.1） —— 一次性跑，把 172.20.2.134 从裸机变成可部署状态
2. **应用部署脚本**（§5.1） —— 每次部署由 GitHub Actions SSH 调用
3. **一键回滚脚本**（§8.2） —— 部署失败或线上出问题时回退
4. **Cloudflare Tunnel systemd 单元**（§5.6） —— 钉钉 OA 回调的 HTTPS 隧道
5. **Cloudflare Tunnel 配置文档** —— 7 步走通 Tunnel 配置

本次和第一批 demo（`04_backup.sh` + `check_health.sh`）配套，
完成 v0.9 实施路线图（§10）的**阶段 1**（服务器初始化）和**阶段 7**（Cloudflare Tunnel）的脚本部分。

## 改动内容

### 新增文件

| 文件 | 行数 | 用途 |
|------|------|------|
| `scripts/deploy/01_init_server.sh` | ~290 | 服务器初始化（系统包 + Redis + cloudflared + UFW + 用户 + 目录） |
| `scripts/deploy/02_deploy.sh` | ~310 | 通用部署（拉代码 → 装依赖 → migrate → 重启 → 健康检查 → 通知） |
| `scripts/deploy/03_rollback.sh` | ~230 | 一键回滚（git checkout + 重启 + 健康检查） |
| `scripts/deploy/systemd/cloudflared.service` | ~70 | Cloudflare Tunnel 守护进程（Type=notify） |
| `scripts/deploy/cloudflared/README.md` | ~200 | Cloudflare Tunnel 7 步配置指南 |
| `docs/changelogs/2026-07-20_devops-deploy-scripts.md` | 本文件 | 变更日志 |

### 关键设计点

#### `01_init_server.sh`（服务器初始化）

- **幂等性**：用户、目录、密钥文件已存在会跳过；Redis 密码若已存在则复用（不覆盖）；UFW 规则按期望终态重置
- **凭据不硬编码**：Redis 密码（24 字节）和 GPG 备份密码（32 字节）由 `openssl rand` 自动生成，存到 `/etc/archery/`（600 权限）
- **UFW 收口**：只开 22/80，不开 443（钉钉回调走 Cloudflare Tunnel outbound）
- **Redis 密码注入**：用 `sed` 注释掉原文件冲突项，再 append 新配置（避免直接覆盖原文件破坏包升级时的合并）
- **cloudflared 安装**：自动识别 `x86_64` / `aarch64`，从 GitHub releases latest 下载 deb 包
- **SSH 公钥支持**：`SSH_PUBLIC_KEY` 环境变量传入，可重复执行累加（`>>` 而非 `>`）

#### `02_deploy.sh`（应用部署）

- **流程清晰**：0.记录当前版本 → 1.拉代码 → 2.装依赖 → 3.migrate → 4.collectstatic → 5.重启 systemd → 6.健康检查 → 7.通知钉钉
- **环境差异集中**：`case "${ENV}"` 一次性映射 `dev/staging/prod` → 端口/数据库/路径
- **健康检查自动回滚**：连续 10 次 × 2s 失败 → 自动调用 `03_rollback.sh`（可由 `ROLLBACK_ON_FAIL=false` 关闭）
- **优雅降级**：缺钉钉 webhook 时只记日志，不影响部署
- **systemd 状态感知**：用 `systemctl cat` 检查 service 是否部署，缺则给出修复命令
- **失败诊断**：每步失败有清晰的 `die()` 提示（缺什么 / 怎么修）

#### `03_rollback.sh`（一键回滚）

- **和 deploy 镜像结构**：参数解析、工具函数、日志、健康检查完全一致
- **静默安全的回滚范围**：只回滚代码 + 重新 collectstatic + 重启 service，**不回滚数据库**（避免误删数据；如需 DB 回滚应先用 `04_backup.sh` 备份再手动恢复）
- **多次回滚支持**：从坏版本回退到上一个稳定版本；git checkout 本身幂等
- **失败仍钉钉告警**：回滚后健康检查仍失败 → 钉钉群通知人工介入

#### `cloudflared.service`（钉钉回调隧道）

- **Type=notify**：cloudflared 支持 `sd_notify`，启动失败时 systemd 能正确判断（Type=simple 会让"进程没退出"误判为"启动成功"）
- **User=root**：Tunnel 需要特权（绑定 raw socket / 读 `/etc/cloudflared/credentials`）
- **深度安全加固**：
  - `NoNewPrivileges` / `ProtectSystem=strict` / `ProtectHome=false` / `PrivateTmp`
  - `ReadWritePaths=/etc/cloudflared /var/log/cloudflared`（cert + 凭据目录白名单）
  - `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`（限制 socket family）
  - `RestrictNamespaces` / `RestrictRealtime` / `LockPersonality` / `MemoryDenyWriteExecute`
  - `SystemCallArchitectures=native`（防止通过 32 位 syscall bypass）
- **资源**：`LimitNOFILE=65536` / `MemoryMax=256M` / `TasksMax=512`

#### `cloudflared/README.md`（配置指南）

- **7 步走通**：login → create → config → DNS → systemd → 验证 → 钉钉后台
- **完整 config.yml 示例**：含 `originRequest` 调优（HTTP/2 关闭、keep-alive、超时）
- **5 大故障排查**：systemd 状态 / Tunnel 已起但请求不通 / DNS 错 / 钉钉后台拒绝 / 完全重建
- **安全注意**：凭据泄露立即重建 Tunnel；nginx `/dingtalk/oa/callback` 只允许 `127.0.0.1` 访问

## 涉及文件

```
scripts/
├── deploy/
│   ├── 01_init_server.sh                  (新增, ~290 行)
│   ├── 02_deploy.sh                       (新增, ~310 行)
│   ├── 03_rollback.sh                     (新增, ~230 行)
│   ├── cloudflared/                       (新增目录)
│   │   └── README.md                      (新增, ~200 行)
│   └── systemd/
│       └── cloudflared.service            (新增, ~70 行)

docs/
└── changelogs/
    └── 2026-07-20_devops-deploy-scripts.md (本文件)
```

**未修改任何已有文件**（包括 `AGENTS.md`、`docs/customization.md`、上游 Archery 源码、第一批 demo 的 4 个文件）。

## 验证清单

- [x] `bash -n scripts/deploy/01_init_server.sh` 通过
- [x] `bash -n scripts/deploy/02_deploy.sh` 通过
- [x] `bash -n scripts/deploy/03_rollback.sh` 通过
- [x] 三个脚本头都包含 `set -euo pipefail`
- [x] 真实凭据用占位符或从 .env / `/etc/archery/*` 文件读取（无硬编码）
- [x] 所有路径用变量（`${ARCHERY_HOME}` / `${REPO_DIR}` / `${LOG_DIR}` 等），默认值可被环境变量覆盖
- [x] 幂等性：用户/目录/密钥已存在则跳过；Redis 密码复用而非覆盖；UFW 重置为终态；git checkout / pip install 天然幂等
- [x] 关键命令都有错误处理（`systemctl restart` / `git checkout` / `pip install` / `migrate` / `collectstatic` / `curl`）
- [x] 失败有钉钉通知（`die()` 钩子 + 部署/回滚结束时的成功通知）
- [x] `cloudflared.service` 有完整安全加固（`NoNewPrivileges` / `ProtectSystem=strict` / `RestrictAddressFamilies` / `MemoryDenyWriteExecute` 等）
- [x] cloudflared/README.md 覆盖 login/create/config/DNS/systemd/验证/钉钉后台 7 步

## 部署步骤（运维执行）

### 阶段 1：服务器初始化（一次性，~15 分钟）

```bash
# 本地生成 SSH 密钥对（如果还没有）
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/archery_deploy_key

# 上传初始化脚本
scp scripts/deploy/01_init_server.sh root@172.20.2.134:/tmp/

# 在服务器上跑（公钥通过环境变量传入）
ssh root@172.20.2.134 "SSH_PUBLIC_KEY='$(cat ~/.ssh/archery_deploy_key.pub)' bash /tmp/01_init_server.sh"
```

### 阶段 2：SSH 私钥上传到 GitHub Secrets

```bash
# 私钥内容（不是路径）
cat ~/.ssh/archery_deploy_key

# 粘贴到 GitHub Repo → Settings → Secrets → New secret
#   Name:  SSH_PRIVATE_KEY
#   Value: (上面 cat 的内容)
```

### 阶段 3：第一次部署

```bash
# 1. 登录服务器
ssh -i ~/.ssh/archery_deploy_key archery@172.20.2.134

# 2. 创建 .env（每个环境各一份）
sudo -u archery -H bash -c "
    cp /opt/archery/.env.example /opt/archery/prod/.env
    vi /opt/archery/prod/.env
"
# 编辑填入：
#   MYSQL_HOST=172.20.2.134
#   MYSQL_USER=dbops
#   MYSQL_PASSWORD=<真实密码，从密码管理器取>
#   REDIS_PASSWORD=$(sudo cat /etc/archery/redis_password)
#   SECRET_KEY=<强随机>
#   ALLOWED_HOSTS=172.20.2.134
#   DINGTALK_OA_CALLBACK_TOKEN=...
#   DINGTALK_OA_CALLBACK_AES_KEY=...

# 3. 部署 systemd 单元
sudo cp scripts/deploy/systemd/archery-prod-*.service /etc/systemd/system/
sudo cp scripts/deploy/systemd/archery-staging-*.service /etc/systemd/system/
sudo cp scripts/deploy/systemd/archery-dev-*.service /etc/systemd/system/
sudo cp scripts/deploy/systemd/cloudflared.service /etc/systemd/system/
sudo systemctl daemon-reload

# 4. 手动跑第一次部署
cd /opt/archery/scripts/deploy
sudo ./02_deploy.sh prod v1.14.0.1   # 或某个具体 tag

# 5. 验证
curl -fsS http://127.0.0.1:9003/healthz
```

### 阶段 4：Cloudflare Tunnel 配置

详细 7 步见 [`scripts/deploy/cloudflared/README.md`](../../scripts/deploy/cloudflared/README.md)。

简版：

```bash
# 1. 登录 + 创建 tunnel
cloudflared tunnel login
cloudflared tunnel create archery-oa
TUNNEL_ID=$(cloudflared tunnel list | grep archery-oa | awk '{print $1}')
sudo mkdir -p /etc/cloudflared
sudo cp /root/.cloudflared/${TUNNEL_ID}.json /etc/cloudflared/
sudo chmod 600 /etc/cloudflared/${TUNNEL_ID}.json

# 2. 写 config.yml
sudo tee /etc/cloudflared/config.yml > /dev/null <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: /etc/cloudflared/${TUNNEL_ID}.json
ingress:
  - hostname: archery-oa.your-domain.com
    service: http://127.0.0.1:80
  - service: http_status:404
EOF

# 3. DNS 路由
cloudflared tunnel route dns archery-oa archery-oa.your-domain.com

# 4. 启动
sudo systemctl enable --now cloudflared.service
sudo systemctl status cloudflared.service

# 5. 钉钉后台配置回调 URL = https://archery-oa.your-domain.com/dingtalk/oa/callback
```

## 回滚方案

```bash
# 场景 1：CI/CD 部署失败（自动回滚）
# 02_deploy.sh 在健康检查失败时自动调用 03_rollback.sh，无需人工

# 场景 2：线上出问题，需要手动回滚
ssh archery@172.20.2.134
cd /opt/archery/scripts/deploy
sudo ./03_rollback.sh prod v1.14.0    # 回滚到上一个稳定 tag

# 场景 3：完全回滚本次提交（仅源码层）
git revert HEAD  # 或 git reset --hard HEAD~1

# 服务器端清理（如果已经部署）
sudo systemctl disable --now cloudflared.service
sudo rm /etc/systemd/system/cloudflared.service
sudo systemctl daemon-reload
```

## 后续工作（按 v0.9 路线图）

- [ ] `.github/workflows/ci.yml`（CI 流水线，§6.2）
- [ ] `.github/workflows/cd-staging.yml`（push to main 自动部署 staging，§6.3）
- [ ] `.github/workflows/cd-prod.yml`（tag 触发 + 人工审批，§6.4）
- [ ] `archery-backup.timer` + `archery-backup.service`（替代 cron 的 systemd 方式）
- [ ] nginx 配置脚本化（目前手动 `cp` 到 `/etc/nginx/sites-available/archery.conf`）
- [ ] 钉钉 OA 集成代码（`sql/extensions/dingtalk_oa/`）—— coder agent 正在并行

## 关联文档

- [`docs/designs/2026-07-20_devops-cicd.md`](../../docs/designs/2026-07-20_devops-cicd.md) §4 / §5.1 / §5.6 / §8.2 —— 设计依据
- [`docs/customization.md`](../../docs/customization.md) §5 —— changelog 模板
- [`AGENTS.md`](../../AGENTS.md) —— 二次开发硬规则
- [`docs/changelogs/2026-07-20_devops-backup-monitor.md`](../../docs/changelogs/2026-07-20_devops-backup-monitor.md) —— 第一批 demo 配套
- [`docs/changelogs/2026-07-20_v0.9-devops-decisions.md`](../../docs/changelogs/2026-07-20_v0.9-devops-decisions.md) —— 12 个决策落档
