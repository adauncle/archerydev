# 2026-08-26 推 110 DRF Throttling cache 500 bug 修复 (CACHE_URL 缺失)

**类型**: fix (推 110 prod 应急 bug)
**严重度**: P0 (业务 RD 提单 / 选 database 报 500, 走不通 SQL 上线流程)
**修复时间**: 2026-08-26 20:43-20:46 (3 分钟 fix + 验证)
**commit**: 待补 (推 110 完成后整体 commit)

---

## 症状

8/26 20:35 业务 RD 提单时, 选 instance 没问题 (e.g. "prod core for etc 日常"), 但**选 database 时报 500**:

```
GET http://prodarchery.ahggwl.com:9123/api/v1/sqlquery/resources/?instance_name=prod%20core%20for%20etc%E5%8F%98%E6%9B%B4&resource_type=database 500 (Internal Server Error)
```

业务 RD 走不通 SQL 上线流程. SECRET_KEY 修复 (20:24) 后 5+1 端点 200/302 全过, 但**漏了 DRF Throttling cache 路径** (/api/v1/* sqlquery resources 端点).

---

## 根因

### 直接根因 (DRF Throttling 走 cache 失败)

`/api/v1/sqlquery/resources/` 走 DRF `APIView` → DRF Throttling 走 `self.cache.get(self.key, [])` (限流 history) → django_redis → redis AUTH 失败 → 500.

archery.log traceback:
```
File "/dbdata/archery_v114/venv/lib/python3.9/site-packages/rest_framework/throttling.py", line 123, in allow_request
    self.history = self.cache.get(self.key, [])
File ".../django_redis/client/default.py", line 258, in get
    value = client.get(key)
File ".../redis/connection.py", line 340, in read_response
    raise error
redis.exceptions.AuthenticationError: Authentication required.
```

### 深层根因 (CACHE_URL 缺失)

`archery/settings.py` 用 `django-environ` 的 `CACHES = env.cache()` 拼 CACHES 配置. **`env.cache()` 只读 `CACHE_URL` 环境变量**, 不会自动从 `REDIS_HOST/REDIS_PORT/REDIS_DB/REDIS_PASSWORD` 拼 URL.

110 prod .env 设了 `REDIS_HOST/REDIS_PORT/REDIS_PASSWORD`, 但**没设 `CACHE_URL`**, 所以 `env.cache()` 拼出来:
```python
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/0'  # ❌ 无 AUTH 密码
    }
}
```

但 8/26 推 110 时拉了新 redis-server 加了 `--requirepass 'fbbbc6d5267641cdf6df03369dddd8ef151193da39c41d32'`, redis 拒接无密码连接 → DRF Throttling cache 失败 → 500.

### 5+1 端点验证漏掉

8/26 20:24 SECRET_KEY 修复后 5+1 端点验证走的都是**渲染型端点** (login/admin/dbaprinciples/sqlworkflow/sqlsubmit/gh_ost/rebuild/select/), 这些不走 DRF Throttling. **没有走 /api/v1/* REST API 路径**, 所以没踩到 cache 500.

---

## 修法 (A 方案, 用户 8/26 20:38 拍板)

**A. 干净重启 redis + 杀老进程 + .env 加 CACHE_URL + kill gunicorn 重启**

**操作步骤** (3 分钟):

1. **备份老 redis 持久化数据** (RDB 快照, 防止丢数据):
   - `cp -a /var/lib/redis/dump.rdb /backup/redis_20260826_2039/`
   - (110 prod 没 dump.rdb, 是空 RDB)

2. **杀所有 redis 进程 + disable systemd redis**:
   - `pkill -9 -f redis-server` (杀 10952 + 87126 + 后续自动拉的)
   - `systemctl disable redis` (防 systemd 自动拉无密码 redis)
   - 端口 6379 释放

3. **.env 加 CACHE_URL** (跟 REDIS_PASSWORD 同步):
   ```bash
   echo 'CACHE_URL=redis://:fbbbc6d5267641cdf6df03369dddd8ef151193da39c41d32@127.0.0.1:6379/0' >> /dbdata/archery_v114_c9236a0/.env
   ```

4. **拉新 redis-server (加 --requirepass)**:
   ```bash
   redis-server --port 6379 --bind 0.0.0.0 \
     --requirepass 'fbbbc6d5267641cdf6df03369dddd8ef151193da39c41d32' \
     --appendonly yes --dir /var/lib/redis --daemonize yes
   ```

5. **杀 gunicorn + 拉新** (让 settings 重新读 CACHE_URL):
   ```bash
   pkill -TERM -f 'gunicorn archery.wsgi'  # 杀 125173
   sleep 5
   cd /dbdata/archery_v114_c9236a0 && \
     setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application \
       -w 4 -b 0.0.0.0:9123 --access-logfile - --error-logfile - --timeout 120 \
       </dev/null >/var/log/archery/gunicorn.log 2>&1 & disown
   ```

6. **验证**:
   - `redis-cli -a '...' ping` → PONG ✓
   - Django ORM `cache.set/get` → `value_456` ✓
   - `settings.CACHES['default']['LOCATION']` 含 `redis://:password@...` ✓
   - 业务 RD 浏览器场景 (走 /api/v1/sqlquery/resources/) → 不再 500 ✓

**修复后 gunicorn** (8/26 20:46): pid 99766 master + 4 worker, 跑了 24s+ 稳定.

---

## 教训 (跨项目可复用, 6 条)

1. **`env.cache()` 只读 `CACHE_URL`, 不自动拼 REDIS_PASSWORD** — 推 prod 物料 .env 必加 CACHE_URL 跟 REDIS_PASSWORD 同步
2. **5+1 端点验证漏了 /api/v1/* REST API 路径** — DRF Throttling 走 cache, 走不通会 500. **必加 1 个 /api/v1/ 端点验证** (e.g. `/api/v1/sqlquery/instances/`)
3. **redis-server 启动必加 `--requirepass` 跟 .env REDIS_PASSWORD 同步** — 134 dev 演练时 redis 走 systemd, 没要求密码. 110 prod 推过去时手动 nohup 拉 redis, 忘加 requirepass 是 P0 bug 源头
4. **systemd 拉起的 redis 可能没 requirepass** — `systemctl disable redis` 防止 systemd 拉老 unit 配置的 redis. 134 dev 有 systemd unit, 110 prod 110 systemd disabled 但还有残留 generator
5. **DRF Throttling cache 失败返 500 不是 401/429** — 上游 v1.14.0 缺陷, 短期在 `archery/settings.py` CACHES 配 OPTIONS={'IGNORE_EXCEPTIONS': True} 让 cache 失败降级返默认空 list
6. **两次 P0 修复都因为 5+1 端点验证深度不够** — 第一次 SECRET_KEY 走 ORM EncryptedCharField 没测, 第二次 CACHE_URL 走 /api/v1/ 没测. **推 prod 5+1 端点验证 checklist 加 ORM EncryptedCharField 解密 + /api/v1/ REST API 路径 + 业务 RD 真实工单流 (mkq 业务用户登录 → 选 instance → 选 database)**

---

## 推 110 实际时间线 (8/26 周三, 续 20:30 后)

| 时间 | 事件 |
|------|------|
| 20:30 | 业务群发"推 110 完成" (5+1 端点验证已过, SECRET_KEY 修复已过) |
| 20:35 | 业务 RD mkq 浏览器提单, 选 database 报 500 |
| 20:36 | 抓 traceback 锁定 DRF Throttling cache AUTH 失败 |
| 20:38 | 用户拍板 A 方案 (干净重启 redis) |
| 20:39 | 备份 RDB + 杀 10952 + 87126 (systemd 拉 75374) |
| 20:40 | disable systemd redis + 拉新 redis (systemd 又拉 80687, 抢端口) |
| 20:41 | 杀所有 redis 干净, 拉新 redis-server (systemd 又拉 86701) |
| 20:43 | .env 加 CACHE_URL + 杀 gunicorn + 拉新 (Connection in use 失败 1 次) |
| 20:45 | setsid nohup 拉新 gunicorn pid 99766 + 4 worker, 3 端点 OK |
| 20:46 | Django ORM cache 走通, archery 业务流返 200 (密码错) 不再 500 |

**实际推 110 完成时间**: **20:46** (原计划 19:00, 延迟 1h 46m, 全因 2 次 P0 bug 修复 SECRET_KEY 1.5min + CACHE_URL 3min)

---

## 关联

- 上一份 changelog: `2026-08-26_push110-secretkey-mismatch-bug.md` (SECRET_KEY 修复)
- 推 110 主手册: `docs/runbooks/2026-08-27_push-v030-execution-manual.md` (待更新 5+1 端点 → 5+1+ORM+REST API 端点)
- 8/26 推 110 总 changelog: 待写 (含 SECRET_KEY + CACHE_URL + 8/24 6 bug fix)
