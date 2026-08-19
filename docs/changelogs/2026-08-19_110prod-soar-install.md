# 2026-08-19 110 prod SOAR 工具安装 + 路径配置

## 一句话

110 prod 装 [XiaoMi/soar](https://github.com/XiaoMi/soar) 二进制 (从 docker overlay 复用) + admin 后台配路径 `/usr/local/bin/soar`, 业务用户点 SOAR 区域能跑真实 SQL 优化报告 (markdown 格式, 含 EXPLAIN 表 + 优化建议), 不再返 500 错。

## 背景

8/19 09:32 业务用户截图 `/slowquery_advisor/` 报 `[Errno 2] No such file or directory: '/opt/archery/src/plugins/soar'`,根因跟 sqladvisor 一模一样:

- 110 prod 是 8/05 从 v1.10.0 docker 部署切到 v1.14.0 裸机部署
- admin 后台 `sql_config.soar` 还存着 docker 时代配的路径 `/opt/archery/src/plugins/soar`
- 8/05 切 v1.14.0 裸机后没改, 二进制也没装

## 跟 sqladvisor bug 区别

| 项 | sqladvisor (8/18 已修) | soar (本次) |
|---|---|---|
| 二进制 | 已装 (A 方案 8/18 复制) | 8/19 复制 |
| 链接 client lib | libmysqlclient.so.18 (5.7.44) | 不依赖 mysql client (Go 静态编译) |
| 业务用户 IN 多值查询 | ❌ 报 "Invalid parameter number" (上游 bug) | ✅ 正常出报告 (80分) |
| 业务用户单表查询 | ⚠️ 部分 SEGFAULT (上游 bug) | ✅ 正常出报告 |
| 维护状态 | Meituan 2017-03 后不维护 | XiaoMi 2017 后还在维护 |
| 报告格式 | add index 建议 | markdown (EXPLAIN 表 + 优化建议) |

## 安装过程

### 步骤 1: 复制 soar 二进制 (docker overlay 复用)

```bash
cp -av /var/lib/docker/overlay2/0b22047.../diff/opt/soar /usr/local/bin/soar
chmod +x /usr/local/bin/soar
# -rwxr-xr-x. 1 root root 14707104 Dec  7  2021 /usr/local/bin/soar
# 14MB, 2021-12-07 编译的 Go 二进制
```

### 步骤 2: 测 soar 跑真实 SQL

```bash
soar \
  -online-dsn 'archery:ldlAaBDXqKmycI6cJdDlcRgVWchsC8@172.20.2.110:3306/hly_accesscard' \
  -test-dsn 'archery:ldlAaBDXqKmycI6cJdDlcRgVWchsC8@172.20.2.110:3306/hly_accesscard' \
  -allow-online-as-test \
  -report-type=markdown \
  -query "SELECT id, id_old, company_name, card_id FROM accesscard_consumedly WHERE message_id IN ('HLY_ZLQSMX_20260817_140000', ...) LIMIT 10"

# 输出:
# # Query: DA09C2C999DE6F87
# ★ ★ ★ ★ ☆ 80分
# ## 未使用 ORDER BY 的 LIMIT 查询
# Item: RES.002
# Severity: L4
# Content: 没有 ORDER BY 的 LIMIT 会导致非确定性的结果
```

soar 跑成功,出真实报告 (跟 sqladvisor 的"Invalid parameter number" 对比)。

### 步骤 3: admin 后台配路径

110 prod admin 后台 `sql_config.soar` (id=1941) 之前值是 docker 时代路径 `/opt/archery/src/plugins/soar`。
`soar_test_dsn` (id=1942) 之前值是 `archery:xxx@172.20.2.110:3306/archery` (本机 DSN, 仍然有效)。

```python
# 110 prod manage.py shell
from common.config import SysConfig
SysConfig().set('soar', '/usr/local/bin/soar')
# SysConfig().get('soar')  # → '/usr/local/bin/soar' ✓
```

soar_test_dsn 不动 (已经是 172.20.2.110:3306/archery 本机 DSN)。

### 步骤 4: HUP gunicorn 刷 SysConfig 缓存

```bash
# Master PID 102228, kill -HUP, 4 秒后 4 个新 worker (62160-62163) 启动
kill -HUP 102228
```

## 推 110 5 步必做 (与 sqladvisor 相同)

5 步必做脚本 (`scripts/deploy/5step_prerequisites_110prod.sh`) 步骤 6 已加, 检测 `sql_config.soar` + `sqladvisor` value:
- 空 → 跳过 (新装已配)
- 不空 → 清空 (历史残留)

## 涉及文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `/usr/local/bin/soar` | 新增 | XiaoMi/soar 二进制 (从 docker overlay 复用, 14MB) |
| `sql_config.id=1941` | 修改 | item=soar, value 改为加密的 `/usr/local/bin/soar` |
| `docs/changelogs/2026-08-19_110prod-soar-install.md` | 新增 | 本 changelog |

## 教训 (跟 8/18 sqladvisor 一起)

1. **1.10.0 → 1.14.0 切换时, admin 后台所有路径类配置都需清空/改新路径** (sqladvisor / soar / my2sql 都有这个风险)
2. **sqladvisor 上游不维护, 业务用户场景下不可靠** (IN 多值 / SEGFAULT)
3. **XiaoMi/soar 是更现代的 SQL 优化工具**, Go 写, 2017 后还在维护, 业务用户场景下更稳定
4. **docker overlay 复用二进制是 110 prod 装工具的最佳实践** (避免 cmake 编译 + dev 依赖)
5. **HUP gunicorn 让 SysConfig 内存缓存刷新**, 配 admin 后立即生效

## 下一步

- 134 dev 还没装 sqladvisor / soar, 推 110 后 DBA 自己决定要不要装 (134 dev 是 dev 环境, 不强求)
- v0.3.0+ 二次开发跟 sqladvisor / soar 无关, 推 110 流程不变
