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

## 使用方法

```bash
# 在 172.20.2.134 上
scp scripts/deploy/deploy_prod.sh root@172.20.2.134:/tmp/
ssh root@172.20.2.134
bash /tmp/deploy_prod.sh
```

## 注意事项

- **会 DROP DATABASE**（`archery_prod`）—— 首次部署 OK，重跑前要确认里面没数据
- 脚本幂等性：除 DROP 步骤外都可重跑（pip 跳过已装、gunicorn 启动前先 pkill 旧进程）
- 跑通后建议删除 `/tmp/deploy_prod.sh`（避免留在服务器临时目录）
