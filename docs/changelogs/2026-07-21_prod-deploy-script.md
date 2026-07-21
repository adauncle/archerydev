# 2026-07-21 · prod 部署脚本

## 背景

staging 在 `2ddd91a`（tag `v0.1.0-staging`）已 100% 上线。
进入 prod 部署阶段，需要一份"一键脚本"在 172.20.2.134 上把 prod 跑起来。

`scripts/deploy/02_deploy.sh` 是环境无关的通用模板（接受 `ARCHERY_ENV` 参数）；
本次新增 `scripts/deploy/deploy_prod.sh` 是 **prod 专用的实操脚本**，硬编码了 prod 的具体参数：

- 数据库：`archery_prod`
- 端口：`9003`（staging 是 9002）
- workers：4（staging 是 2）
- 部署路径：`/opt/archery/prod`
- admin 用户：`archery` / `archery`（与 staging 一致，便于记忆）

## 改动

### 新增
- `scripts/deploy/deploy_prod.sh`（114 行）
  - 14 步：状态检查 → 重建库 → v1.0_init + 升级 SQL → 加 audit_driver 字段 → 建 venv → pip install → migrate → seed_sql_types + init_fallback_flow → 建 admin 用户 → 建 logs/media/static → collectstatic → 启动 gunicorn → 开 firewalld → 验证 → 端口监听

## 密码处理

脚本不内嵌任何密码，凭据从 `/etc/archery/` 读取：
- `dbops_password` —— dbops 用户密码
- `.mysql_root` —— root 密码（隐藏文件，chmod 600）

mysql 命令加 `2>&1 | grep -v 'Using a password'` 屏蔽密码告警。

## 注意事项

- **会 DROP DATABASE**（`archery_prod`）—— 首次部署 OK，重跑前要确认里面没数据
- 脚本幂等性：除 DROP 步骤外都可重跑（pip 跳过已装、gunicorn 启动前先 pkill 旧进程）
- 跑通后建议删除 `/tmp/deploy_prod.sh`（避免留在服务器临时目录）

## 已知坑 & 修复

### v1.1 (commit 6b9dfee) — `set -e` + `grep -v` 退码 1

**症状**：脚本在 step 1 后静默中止，archery_prod 库被 DROP+CREATE 但后续步骤都没跑。
**根因**：`mysql ... 2>&1 | grep -v 'Using a password'` —— 当 mysql 只输密码告警那一行时，grep 过滤后空输出 → exit code 1 → `set -e` 让整个脚本死掉。
**修复**：
- 提取 `mysql_run()` 函数，统一 `2>/dev/null` 吞告警
- pkill 加 `|| true` 兜底（首次部署没有旧进程时 pkill 也会退出 1）

诊断方法：直接看 `/var/log/archery/deploy_prod.log`，停在 "=== 1. 重建 archery_prod 库 ===" 之后一行都没输出，就是这个坑。
