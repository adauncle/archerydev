# v0.2.1-rc · promote_110.sh 一键发布脚本

**Commit**: `a5471b3`
**Date**: 2026-08-04
**Type**: feat · ops · 关键工具
**作用**: 把 134 dev 验证过的版本推 110 PROD（裸机，0 依赖 Windows 传文件）

---

## 设计原则

**110 PROD 主动从 github 拉 tarball**，不走 134 dev 中转 / Windows 传文件。

旧 promote 设计痛点（这次重写要解决的）：
- 134 dev 不是 git 仓库（scp 传过去的）
- Windows → 110 走 scp 中文路径经常 abort
- 长 ssh 命令在 bash tool 下不稳定
- 134 中转增加故障点

新设计要点：
- 110 上 `curl -L https://github.com/adauncle/archerydev/archive/v0.2.0.tar.gz | tar -xz`
- 110 上 GitHub API 解析 git ref → commit hash
- 110 上自己跑全部 5 phase（无需外部依赖）
- Windows 端只 ssh 触发（或直接 .ps1 双击）

---

## 5 Phase 流程

| Phase | 内容 | dry-run 行为 |
|---|---|---|
| 0 预检 | root / 110 状态 / github 可达 / git ref 解析 / 备份目录 | 跑 0.1/0.2/0.5 |
| 1 备份 110 | mysqldump + code 归档 + .env + secret_key | 打印 |
| 2 拉代码 | curl github tarball + tar 解压 | 打印 |
| 3 适配 110 | venv 软链 / patch features.py 5.7 / .env / systemd unit 路径 | 打印 |
| 4 deploy | stop / check / migrate / collectstatic / start / smoke | 打印 |
| 5 收尾 | 保留旧版 A 级回滚 / 7 天清理 cron | 打印 |

**默认 dry-run**（仅打印），`--no-dry-run` 真执行。

---

## 触发方式

**方式 1 - 直接 ssh（推荐）**：
```bash
cat scripts/promote_110.sh | ssh root@172.20.2.110 "bash -s -- v0.2.0 --no-dry-run"
```

**方式 2 - Windows 触发器（双击）**：
```powershell
.\scripts\promote_110.ps1 v0.2.0 --no-dry-run
```

**方式 3 - 仅看流程（dry-run）**：
```bash
cat scripts/promote_110.sh | ssh root@172.20.2.110 "bash -s -- v0.2.0"
```

---

## 关键适配（134 dev → 110 prod 差异）

| 项 | 134 DEV | 110 PROD | 适配方式 |
|---|---|---|---|
| 路径 | /opt/archery/prod | /dbdata/archery_v114 | sed 改 systemd unit |
| 端口 | 9003 | 9123 | 沿用 110 systemd unit |
| MySQL | 8.0.22 | 5.7.44 | sed features.py: return (8,) → (5, 7) |
| Redis | 裸机 systemd | 容器 redis:5 | .env: REDIS_HOST=127.0.0.1 |
| Goinception | 裸机 systemd | 容器 @ 4000 | 沿用容器 |
| Python venv | /opt/archery/prod/venv | /dbdata/archery_v114/venv | 软链复用（节省 30-60 min）|

---

## 110 dry-run 验证（2026-08-04 17:50）

| Phase | 状态 |
|---|---|
| 0.1 root 用户 | ✅ |
| 0.2 110 PROD 状态 | ✅ NOT_GIT + venv 存在 |
| 0.3 github.com 可达 | ⏭️ dry-run 跳过（之前 curl 测试 HTTPS 200） |
| 0.4 git ref 解析 | ⏭️ dry-run 跳过（代码会调 GitHub API） |
| 0.5 备份目录 | ✅ /backup/promote/20260804_175046 |
| 1 备份 110 | ⏭️ 打印动作 |
| 2 拉代码 | ⏭️ 打印动作 |
| 3 适配 110 | ⏭️ 打印动作 |
| 4 deploy | ⏭️ 打印动作 |
| 5 收尾 | ⏭️ 打印动作 |

**exit 0**，整链路无语法错误。

---

## 已知风险

1. **GitHub API 限流**：anonymous 60 req/h，promote 一次用 1 req，足够
2. **tarball 体积**：archerydev 仓库 ~ 几 MB（不含 .git），下载 < 30s
3. **venv 软链**：新旧 venv 共享，如果两边 requirements.txt 不一致会冲突 → 适配时增量 `pip install -r requirements.txt`
4. **110 systemd unit 路径替换**：用 sed 替换 `/dbdata/archery_v114` → `/dbdata/archery_v114_<short>`，如果路径里有斜杠可能 sed 误替换（验证过：v114 路径无特殊字符，安全）
5. **D+7 清理 cron**：脚本里只是 log 提示，**未自动加 cron**（需要单独配 D+7 清理任务）

---

## 下一步

- 等用户拍板推 110 时机（业务低峰期，建议工作日 19:00 后）
- 真推 110 前，先在 134 dev 走一次完整 dry-run（实际跑 phase 1~4，看适配逻辑对不对）
- 真推后，D+1 / D+7 巡检按 09 节点上线自检流程
