# 8/31 gh-ost 启动逻辑 真实端口探测 (8/31 19:00)

## 背景

- 8/31 17:53 业务 RD 冉升成在 110 prod 提 gh-ost 工单 #7 (instance 5 prod core for etc 变更 172.20.2.9:6446 cluster1), 报 `FATAL unexpected database port reported: 3306` 死掉
- 8/31 18:30 排查根因: 6 个 6446 instance 中 3 个 (5/26/31) 配置错 — 实际 MySQL listen 3306 (cluster1/bg-replica1/logisticsdbm), 6446 是 SSH tunnel / 端口转发. 134 dev 演练 instance 全是 3306 端口没暴露, 110 prod 才暴露
- 8/31 18:50 用户拍板: archery instance 配置不能动 (172.20.2.9:6446 是 cluster1 写入节点约定值), 让 gh-ost 启动前探测真实端口

## 决策

### 1. gh-ost 启动前短连接探测 `@@port` (host:port 不变, port 改)

**理由**:
- 134 dev instance 2 (127.0.0.1:3306) 演练 PASS — 探测 actual_port=3306 跟配置一致, 不变
- 110 prod instance 5 (172.20.2.9:6446) 探测 actual_port=3306 跟配置 6446 不一致, 改用 3306
- 110 prod instance 27 (172.20.2.108:6446) 探测 actual_port=6446 跟配置一致, 不变 (不影响 8/27 实战)

**实现**: `sql/extensions/ddl_gh_ost/services/db.py` `_get_creds` 加 `_detect_actual_mysql_port` helper, 用 PyMySQL 短连接 + `SELECT @@port` 拿真实端口

**改的逻辑**:
```python
# 旧 (8/27 前):
user, password = instance.get_username_password()
return user, password, (instance.host, instance.port)

# 新 (8/31 改):
user, password = instance.get_username_password()
host, port = instance.host, instance.port
actual_port = _detect_actual_mysql_port(host, port, user, password)
if actual_port is not None and actual_port != port:
    port = actual_port  # 改用真实端口, host 保留
return user, password, (host, port)
```

### 2. host 保留 archery 配置, port 改

**理由**: 用户明确说 "172.20.2.9:6446 是指定集群写入节点, 数据库变更都是走写入节点". 改 port 不会影响 archery 业务 (SQL 查询/SQL 审核), 因为 6446 跟 3306 都连同一台 MySQL (cluster1), 真实 listen 端口是 3306.

## 改动

**1 文件 +67/-2**:

| 文件 | 改动 | 数量 |
|------|------|------|
| `sql/extensions/ddl_gh_ost/services/db.py` | `_get_creds` 加端口探测 + 新增 `_detect_actual_mysql_port` helper | +67 行 |

**详细改动**:
- 文档头: 加 "## CUSTOM-MODIFIED: 探测 MySQL 真实 listen 端口 (8/31 @ mavis)" 段, 说明根因 (172.20.2.9:6446 cluster1 是写入节点约定, 实际 listen 3306) + 修法 + 演练 (8/31 17:53 task #7 实战踩坑)
- `_get_creds` 函数: 加探测逻辑 (CUSTOM-MODIFIED 注释), actual_port 跟 config port 不一致就用 actual_port
- `_detect_actual_mysql_port` helper: 短连接 + `SELECT @@port` + 异常 fallback 用 config port

**不影响 8/27 实战** (8/27 task #4-6 走 instance 27 etldb1 6446, 探测 actual=6446 跟 config=6446 一致, 走探测逻辑但不改 port):
- 8/27 task #4 #5 #6 (mkq 演练) 走 instance 27 (172.20.2.108:6446 etldb1) - 探测不变, 跟 8/27 实战结果一致
- 8/27 推 110 时 8 个演练 task 走的也是 instance 27, 不破坏

## 演练验证

**134 dev 演练 (8/31 18:55)**:
- instance 2 (测试 MySQL 8.0) 端口 3306 → 探测 actual=3306 → 跟 config 一致, 不变 ✓

**110 prod 演练 (8/31 19:00)**:
- instance 5 (cluster1) 端口 6446 → 探测 actual=3306 → 改用 3306 ✓
- instance 27 (etldb1) 端口 6446 → 探测 actual=6446 → 跟 config 一致, 不变 ✓

## 教训 (跨项目可复用, 1 条新增, 合并到 r1 entry 避免 memory 膨胀)

1. **gh-ost 启动前必探测 MySQL 真实 listen 端口 (避免 1.1.10 port check 错)** — 8/31 17:53 业务 RD 冉升成 110 prod 提 gh-ost 工单 #7 (instance 5 cluster1 配 6446, 实际 3306) 报 "unexpected database port reported: 3306" 死掉. gh-ost 1.1.10 严格检查 @@port == connection port, 不一致 FATAL. archery 配的 host:port 可能是 SSH tunnel / 端口转发, MySQL 实际 listen 跟 connection port 可能不一致. 134 dev 演练没暴露 (instance 全 3306), 110 prod 6 个 6446 instance 中 3 个 (5/26/31 cluster1/bg-replica1/logisticsdbm) 配错. **下次做 gh-ost 集成必加端口探测 (短连接 SELECT @@port)**, archery instance 配 6446 是约定值 (集群写入节点) 不能动, 但 gh-ost 启动时 host 保留 port 改真实端口, 解决 port check. 探测失败 fallback 用 config port (不破坏现有功能).

## 同源 entry

- 8/27 14:18 runner.py alter 子句提取 fix (commit `d7e9219`) - 改的是 alter 提取
- 8/27 15:15 poller zombie + 终态显示 fix (commit `e489031`) - 改的是 poller
- 8/27 17:00 rollback 端点 import 路径 fix (commit `50122ff`) - 改的是 rollback import
- 8/27 17:25 + 17:30 rollback docstring 警告 + 修正 - 改的是 rollback 文档
- 8/31 17:53 业务 RD 冉升成 task #7 报 port 错 (本次触发)
- 8/31 18:50 用户拍板 "archery 配置不能动, 加判断逻辑" (本次修法)

## 下次推 prod 必做 (新增 1 条, 合并到 r1 entry)

1. **gh-ost 集成必加端口探测**, archery instance 配的 port 不一定是 MySQL 真实 listen (e.g. 6446 是 SSH tunnel 约定, 实际 3306). 134 dev 演练全是 3306 端口没暴露, 110 prod 实战才暴露. **下次做 gh-ost 集成必加短连接 `SELECT @@port` 探测**, 探测失败 fallback 用 config port, 不破坏现有功能. 演练必加 110 prod 真实 instance 端口测试 (134 dev 全 3306 不够).
