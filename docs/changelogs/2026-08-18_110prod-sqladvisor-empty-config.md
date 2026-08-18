# 2026-08-18 110 prod SQL Advisor 报错 bug 修复

## 一句话

110 prod `/slowquery_advisor/` 报 `[Errno 2] No such file or directory: '/opt/archery/src/plugins/sqladvisor'`,根因是 v1.10.0 docker 时代 admin 后台配的 sqladvisor 路径,8/05 切 v1.14.0 裸机后没改。修法: 清空 admin 后台 `sql_config.sqladvisor` value, 业务用户点 SQL 优化返友好提示, 不再 500。

## 症状

- 110 prod `http://prodarchery.ahggwl.com:9123/slowquery_advisor/`
- 业务用户 2026-08-18 17:47 选实例 + 库 + 填 SQL + 点"获取优化建议"
- 弹窗: `命令执行失败，失败原因:[Errno 2] No such file or directory: '/opt/archery/src/plugins/sqladvisor'`
- 跟 v0.3.0-beta / v0.4.0 二次开发**完全无关**, 是 Archery 上游 1.10.0 → 1.14.0 切换的历史配置遗漏

## 根因

### 报错链路
```
POST /slowquery_advisor/ (submit form)
  → sql/sql_optimize.py:optimize_sqladvisor
  → SysConfig().get("sqladvisor") 拿 admin 后台配置的路径
  → 返回 "/opt/archery/src/plugins/sqladvisor"  (v1.10.0 docker 时代配的)
  → SQLAdvisor.execute_cmd 调 subprocess.Popen([self.path] + args)
  → FileNotFoundError: [Errno 2] No such file or directory
```

### 实际状态 (8/18 摸底)

| 项 | 现状 | 期望 |
|---|---|---|
| 项目部署路径 | `/dbdata/archery_v114_c9236a0/` (8/05 切换) | - |
| 配置的 sqladvisor 路径 | `/opt/archery/src/plugins/sqladvisor` (v1.10.0 docker 时代配的) | 真实路径 |
| sqladvisor 二进制 | **没装** (which 找不到, `/usr/local/bin` `/usr/bin` 都没有) | 已装 |
| docker overlay 残留 | `/var/lib/docker/overlay2/c108e.../diff/opt/archery/src/plugins/sqladvisor` (v1.10.0 容器残留, 容器 8/17 已删) | - |
| admin 后台配置 | `item='sqladvisor'` 有配置值 (加密 `q8e6-_vUJSOu1mDqHKuKD50fEFljmKzQHV_zlYmII2N5fE2MkhmzjPVSKFaA2hK0`), 解密后是路径字符串 | - |

### 134 dev 对比
- 134 dev **也没装 sqladvisor 二进制** (跟 110 prod 一样)
- 但 134 dev admin 后台**没配** sqladvisor item (sql_config 表查不到)
- 134 dev 点 SQL 优化 → 返"请配置SQLAdvisor路径！"友好提示, 不会 500
- 110 prod 是历史配置残留, 触发 500 报错

## 修法

**B 方案: admin 后台清空 sqladvisor 配置** (8/18 已执行)

```sql
UPDATE sql_config SET value = '' WHERE item = 'sqladvisor';
-- affected_rows: 1
```

执行后:
- 110 prod `sql_config.id=1940` 的 `value` 字段从 64 字符加密值 → 空 (len=0)
- 业务用户点 SQL 优化 → 走 `if sqladvisor_path is None` 分支 → 返"请配置SQLAdvisor路径！"友好提示
- 不再 500 报错

### 备份与回滚

- 备份文件: `scripts/_archive/110prod_sqladvisor_backup_20260818.txt` (含原 value 加密字符串, id=1940)
- 110 prod 端备份: `/tmp/sqladvisor_backup_full_20260818.txt`
- 回滚: 110 prod admin 后台 → 配置项 → id=1940 → 把原 value 加密字符串粘回去
- 回滚后仍会 500 (因为 sqladvisor 二进制没装), 真修复需要 DBA 装二进制后改路径

### 后续修法 (A 方案, 推 110 后 DBA 做)

- 下载 [SQLAdvisor](https://github.com/Meituan-Dianping/SQLAdvisor) source 编译
- 装到 `/usr/local/bin/sqladvisor`
- admin 后台配路径 `/usr/local/bin/sqladvisor`
- 验证 SQL 优化功能可用

## 推 110 时同步

5 步必做脚本 (`scripts/deploy/5step_prerequisites_110prod.sh`) 新增**步骤 6: 清空 sqladvisor 历史配置**:
- 自动检测 `sql_config.sqladvisor` 是否有 value
- 有 → 备份原 value → 清空 → 验证 len=0
- 没有 (已空) → 跳过
- 这是 idempotent 脚本, 推 110 当天可重复跑

## 涉及文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `scripts/deploy/5step_prerequisites_110prod.sh` | 修改 | 新增步骤 6: 清空 sqladvisor 配置 |
| `scripts/_archive/110prod_sqladvisor_backup_20260818.txt` | 新增 | 110 prod 原 value 备份 (含回滚指引) |
| `docs/changelogs/2026-08-18_110prod-sqladvisor-empty-config.md` | 新增 | 本 changelog |

## 教训

1. **Archery 上游 1.10.0 → 1.14.0 切换时, docker 路径配置没改 → 110 prod 残留** (本 bug)
2. **134 dev 还没暴露, 因为 admin 后台没配 sqladvisor item** (但 134 dev 也没装二进制, 一旦配了也踩)
3. **推 110 时 5 步必做应包含历史 bug 修复** (不只是二次开发新功能, 也要清理上游遗留)
4. **admin 后台配置类 bug 优先选 B 方案 (清空/禁用) 而不是 A (装二进制)**, 0 风险快速止血
