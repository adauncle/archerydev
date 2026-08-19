# 2026-08-19 110 prod soar permission denied 修法

## 一句话

110 prod SOAR 装完后业务用户跑报 `open /usr/local/bin/soar.log: permission denied`,根因是 `/usr/local/bin/` 是 root 拥有 755, archery user 写不进日志文件。修法 F: 移 soar 到 `/opt/archery/bin/` (archery 拥有), admin 配新路径, HUP gunicorn。

## 症状

- 8/19 10:39 业务用户浏览器点 SOAR 区域, 弹窗 `命令执行失败，失败原因:open /usr/local/bin/soar.log: permission denied`
- 跟之前 sqladvisor/soar 找不到二进制的 500 错不一样, **这次是子进程能起, 但 soar 写日志失败**
- 110 prod gunicorn 用 `archery` user 跑 (not root), `subprocess.Popen` 调 soar 时继承 archery user 身份
- soar 二进制 (XiaoMi/soar Go 写) 默认在**当前目录**写 `soar.log`, 即 `/usr/local/bin/soar.log`
- 但 `/usr/local/bin/soar.log` 是 root:root 拥有 660, archery user 没写权限 → 失败

## 根因

**110 prod 之前没装任何工具到 /usr/local/bin/**, 是 root:root 拥有 755。soar 是第一个从 docker overlay 复制过来的工具 (8/19 10:34 装到 /usr/local/bin/soar), 触发这个权限问题。

| 项 | 权限 | 问题 |
|---|---|---|
| `/usr/local/bin/` | root:root 755 | archery user 无写权限 |
| `/usr/local/bin/soar` | root:root 755 | ✓ archery 可执行 |
| `/usr/local/bin/soar.log` (创建) | root:root 660 | ✗ archery 不可写 |

业务用户提交 SQL → Archery 调 `subprocess.Popen(['/usr/local/bin/soar', ...])` → soar 启动成功 → 写 `/usr/local/bin/soar.log` → **permission denied 失败** → 业务用户看到 500。

## 修法

**修法 F: 移 soar 到 `/opt/archery/bin/`** (archery 拥有, 可写)

```bash
# 1. 创建目录 (archery 拥有)
mkdir -p /opt/archery/bin /opt/archery/logs
chown -R archery:archery /opt/archery/bin /opt/archery/logs

# 2. 移动 soar 二进制
cp /usr/local/bin/soar /opt/archery/bin/soar
chown archery:archery /opt/archery/bin/soar
chmod 755 /opt/archery/bin/soar

# 3. admin 后台改 soar item 路径
SysConfig().set('soar', '/opt/archery/bin/soar')

# 4. 删 /usr/local/bin/soar.log (root 拥有, 业务用户可能继续尝试)
rm -f /usr/local/bin/soar.log

# 5. HUP gunicorn 让 SysConfig 缓存刷新
kill -HUP 102228  # master pid
```

**验证**:
- archery user 测跑 `sudo -u archery /opt/archery/bin/soar -query 'SELECT 1'` 成功 (输出 SQL 重写结果)
- `/opt/archery/bin/soar.log` archery 拥有 660, archery user 可写
- HUP 后 4 个新 worker (85388-85392) 启动

## 推 110 5 步必做 (5/6/7 步现状)

- 步骤 5: fix_approval_flow_3level (ext_approval_flow audit_auth_groups=14,15,3)
- 步骤 6: 清空 sqladvisor 历史配置 (8/18 commit 25ce9b3)
- 步骤 7: 清空 soar 历史配置 (8/19 commit a2f9ff9)
- 推 110 当天 5 步必做跑完即可, **业务用户 sqladvisor / soar** 装 + admin 配是 DBA 推完后单独做 (跟 sqladvisor/soar 一样, 不在 5 步必做范围)

## 教训

1. **110 prod 装的工具如果用 archery user 跑 (默认), 不能装 /usr/local/bin/ (root 拥有)** — 应该装到 /opt/archery/bin/ 或 /dbdata/archery_v114_c9236a0/bin/ 这种 archery 写得了的目录
2. **soar / sqladvisor 这类工具默认在当前目录写 .log**, 跑子进程时 cwd 通常是 gunicorn 启动目录 (不可预测), 最稳是显式 -log-output 路径
3. **mysql 凭据配置类历史 bug** (sqladvisor/soar docker 路径残留) 在 1.10.0→1.14.0 切换时还有更多 (my2sql 等), 推 110 时应该**全量审计 admin 后台所有路径类配置**

## 涉及文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `/opt/archery/bin/soar` | 新增 | XiaoMi/soar 二进制 (从 /usr/local/bin/ 移过来) |
| `/opt/archery/bin/soar.log` | 新增 | soar 写日志 (archery 拥有) |
| `/opt/archery/logs/` | 新增 | 未来工具日志目录 |
| `/usr/local/bin/soar.log` | 删除 | root 拥有 660 不可写 |
| `sql_config.id=1941` | 修改 | item=soar, value 改为加密的 `/opt/archery/bin/soar` |
