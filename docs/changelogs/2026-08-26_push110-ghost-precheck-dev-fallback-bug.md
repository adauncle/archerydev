# 2026-08-26 推 110 gh-ost precheck dev-only fallback 凭据 1045 bug 修复

**类型**: fix (推 110 prod 应急 bug)
**严重度**: P0 (业务 RD 提单 / gh-ost precheck 全 FAIL, 走不通 SQL 上线流程)
**修复时间**: 2026-08-26 20:55 (2 分钟 fix + 验证)
**commit**: 待补 (推 110 完成后整体 commit)

---

## 症状

8/26 20:49 业务 RD mkq 浏览器提单, 选 instance 没问题 (e.g. "prod core for etc 变更"), 选 database 也不报 500 (CACHE_URL 修复后), 但**点击 gh-ost 预检后, 5 项预检 4 项 FAIL**:

```
[FAIL] binlog_format   数据库连接失败：(1045, "Access denied for user 'dbops'@'127.0.0.1' (using password: YES)")
[FAIL] disk_space      数据库连接失败：(1045, "Access denied for user 'dbops'@'127.0.0.1' (using password: YES)")
[FAIL] replication_privileges  数据库连接失败：(1045, "Access denied for user 'dbops'@'127.0.0.1' (using password: YES)")
[PASS] alter_sql       ALTER 语句符合 gh-ost 要求 ✓
[FAIL] table_type      数据库连接失败：(1045, "Access denied for user 'dbops'@'127.0.0.1' (using password: YES)")
```

业务 RD 走不通 gh-ost SQL 上线流程. instance admin 列表显示 instance 5 (prod core for etc 变更) 配置是 `archery@172.20.2.9:6446` (真业务库), 但 precheck 用了 `dbops@127.0.0.1` (134 dev 演练 fallback 凭据).

---

## 根因

### 直接根因 (gh-ost precheck 走 dev-only fallback 凭据)

`/dbdata/archery_v114_c9236a0/sql/extensions/ddl_gh_ost/...` 的 precheck 逻辑 (settings.py 425-428):

```python
CUSTOM_GH_OST_PRECHECK_HOST = env("CUSTOM_GH_OST_PRECHECK_HOST", default="")
CUSTOM_GH_OST_PRECHECK_PORT = env("CUSTOM_GH_OST_PRECHECK_PORT", default=3306)
CUSTOM_GH_OST_PRECHECK_USER = env("CUSTOM_GH_OST_PRECHECK_USER", default="")
CUSTOM_GH_OST_PRECHECK_PASSWORD = env("CUSTOM_GH_OST_PRECHECK_PASSWORD", default="")
```

代码注释明确: "**仅 dev/演练用**; prod 应保持空, 让 precheck 走 instance 标准路径".

但 110 prod .env 抄了 134 dev 演练时设的 4 变量:
```
CUSTOM_GH_OST_PRECHECK_HOST=127.0.0.1       # 134 dev 业务库本机
CUSTOM_GH_OST_PRECHECK_PORT=3306            # 134 dev 端口
CUSTOM_GH_OST_PRECHECK_USER=dbops           # 134 dev 业务库 user
CUSTOM_GH_OST_PRECHECK_PASSWORD=TJwgoqnHBlPG5WLemg1sG@#P  # 134 dev 业务库 dbops 密码
```

precheck 走 `if CUSTOM_GH_OST_PRECHECK_HOST: 直连 fallback` 路径, **不走 instance.user/password 解密路径**. 110 prod 元库 `archery` user (5.7.44) 没 `dbops` user, dbops@127.0.0.1:3306 报 1045.

### 深层根因 (134 dev .env 跟 110 prod .env 没严格区分)

8/06 教训 K1 时 DBA 抄 134 dev .env 覆盖 110 prod .env. SECRET_KEY / CACHE_URL 等关键配置已经在 8/26 推 110 暴露为 P0 bug. **dev-only 凭据 (CUSTOM_GH_OST_PRECHECK_*) 抄过去没暴露, 因为 134 dev 演练时没走真业务流**.

**这次是 8/26 推 110 第 4 次 P0 修复**, 都因 134 dev .env 跟 110 prod .env 没严格区分:

| 修复 | 时间 | 变量类型 |
|------|------|----------|
| K1 SECRET_KEY 修复 | 8/26 20:22 | 加密变量, dev 跟 prod 必须独立 |
| K2 CACHE_URL 修复 | 8/26 20:43 | 拼配置变量, dev 跟 prod 必须独立 |
| K3 CUSTOM_GH_OST_PRECHECK_* 修复 | 8/26 20:55 | dev-only fallback 凭据, **prod 必清空** |

---

## 修法 (A 方案, 用户 8/26 20:51 拍板)

**A. 110 prod .env 把 CUSTOM_GH_OST_PRECHECK_* 4 变量注释掉**

**操作步骤** (2 分钟):

1. **备份当前 .env** (含错配 4 变量):
   ```bash
   cp -a /dbdata/archery_v114_c9236a0/.env /dbdata/archery_v114_c9236a0/.env.bak_20260826_2055_precheck
   ```

2. **改 .env (Python 写最稳, 避免 sed 转义)**:
   ```python
   # 4 变量前面加 # 注释
   CUSTOM_GH_OST_PRECHECK_HOST=127.0.0.1   →  # CUSTOM_GH_OST_PRECHECK_HOST=127.0.0.1
   CUSTOM_GH_OST_PRECHECK_PORT=3306        →  # CUSTOM_GH_OST_PRECHECK_PORT=3306
   CUSTOM_GH_OST_PRECHECK_USER=dbops       →  # CUSTOM_GH_OST_PRECHECK_USER=dbops
   CUSTOM_GH_OST_PRECHECK_PASSWORD=...     →  # CUSTOM_GH_OST_PRECHECK_PASSWORD=...
   ```

3. **杀 gunicorn + nohup 拉新** (让 settings 重新读 .env):
   ```bash
   pkill -TERM -f 'gunicorn archery.wsgi'
   sleep 5
   cd /dbdata/archery_v114_c9236a0 && \
     setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application \
       -w 4 -b 0.0.0.0:9123 --access-logfile - --error-logfile - --timeout 120 \
       </dev/null >/var/log/archery/gunicorn.log 2>&1 & disown
   ```

4. **验证** (走 instance 路径直连真业务库):
   - Django settings 4 变量: HOST='', USER='', PASSWORD='' (PORT 默认 3306) ✓
   - ORM 走 instance.user='archery' 直连 172.20.2.9:6446 ✓
   - MySQL 8.0.22 真业务库能连 ✓

---

## 教训 (跨项目可复用, 5 条)

1. **134 dev .env 跟 110 prod .env 必严格区分, dev-only 变量推 prod 必清空** — 强化 8/06 K1 教训. settings.py 注释 "prod 应保持空" 是合约, DBA 抄 .env 时必人工 review 哪些变量是 dev-only
2. **dev-only 凭据 fallback 机制是双重风险** — 一是 prod 数据库解密失败时绕过 (应急); 二是 dev 演练值被错带到 prod (这次). 推 prod checklist 必加 "settings.py `env(default="")` 类的变量必 review 是否 dev-only"
3. **`env.cache()` / `env.db()` / `env.bool()` 等 django-environ helper 只拼环境变量, 不自动从相关变量 fallback** — CACHE_URL 不从 REDIS_PASSWORD 拼 (K2 教训), DATABASE_URL 不从 MYSQL_PASSWORD 拼. 推 prod 物料 .env 必含 helper 期望的 URL 变量
4. **5+1 端点验证漏 gh-ost 业务流 precheck 路径** — 8/26 5+1 端点走的是 /gh_ost/rebuild/select/ (选表页), 没走 gh-ost 预检路径. 推 prod 业务流验证必走完整 gh-ost 链路: 选 instance → 选 database → 触发 precheck → 看 5 项结果
5. **每次推 prod 必跑真业务 RD 工单流** (不是 DBA 演练脚本) — DBA 演练脚本是 admin / 134 dev 凭据, 跟业务 RD mkq 真业务流差异巨大. 推 prod checklist 必加 "业务 RD 浏览器走一遍提单 → precheck → 提交"

---

## 推 110 实际时间线 (8/26 周三, 续 20:46 后)

| 时间 | 事件 |
|------|------|
| 20:46 | CACHE_URL 修复完成, 推 110 第 2 次 P0 修复 |
| 20:48 | 业务群延迟 21:00 准备发, 业务 RD mkq 浏览器走通选 instance + database |
| 20:49 | 业务 RD 触发 gh-ost precheck, 5 项 4 项 FAIL (1045) |
| 20:50 | 锁定 134 dev 演练设的 CUSTOM_GH_OST_PRECHECK_* 4 变量抄到 110 prod |
| 20:51 | 用户拍板 A 方案 (注释 4 变量) |
| 20:55 | .env 注释 4 变量 + kill gunicorn + nohup 拉新 + ORM 直连 172.20.2.9:6446 业务库 OK |

**实际推 110 完成时间**: **20:55** (原计划 19:00, 延迟 **1h 55m**, 全因 3 次 P0 bug 修复 K1 SECRET_KEY 1.5min + K2 CACHE_URL 3min + K3 CUSTOM_GH_OST_PRECHECK_* 2min)

---

## 关联

- 上一份 changelog: `2026-08-26_push110-cache-url-missing-500.md` (K2 CACHE_URL 修复)
- 上上份 changelog: `2026-08-26_push110-secretkey-mismatch-bug.md` (K1 SECRET_KEY 修复)
- 8/06 教训 K1: `.env 抄错` (跨项目可复用)
- 推 110 主手册: `docs/runbooks/2026-08-27_push-v030-execution-manual.md` (待更新 5+1 端点 → 5+1+ORM+REST API + gh-ost precheck 端点验证)
