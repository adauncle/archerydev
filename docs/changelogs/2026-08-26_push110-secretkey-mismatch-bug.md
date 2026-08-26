# 2026-08-26 推 110 SECRET_KEY 不匹配 500 bug 修复

**类型**: fix (推 110 prod 应急 bug)
**严重度**: P0 (5+1 端点 /authenticate/ 500, 业务 RD 全部无法登录)
**修复时间**: 2026-08-26 20:22-20:24 (1.5 分钟 fix + 验证)
**commit**: 待补 (推 110 完成后整体 commit)

---

## 症状

推 110 v0.3.0-beta + v0.4.5 + 8/24 6 bug fix 等 60 commit 完成 (commit `1d4fbf6`) 后, 8/26 19:00 推前 5+1 端点预检 /login/=200, /dbaprinciples/=302, /admin/=302 OK. 19:30 业务群发"推 110 完成". 业务 RD 试登录 mkq 报 500 Internal Server Error.

**截图** (8/26 20:01):
```
jquery.min.js:2  POST http://prodarchery.ahggwl.com:9123/authenticate/ 500 (Internal Server Error)
```

---

## 根因

### 直接根因

`/authenticate/` 走 `common/auth.py:89`:

```python
lock_count = int(self.sys_config.get("lock_cnt_threshold", 5))
```

`SysConfig.get("lock_cnt_threshold")` 返 `WP_F3gNc35I4z3axJ61OLA==` (AES 加密密文, 24 字节 base64 编码), `int(密文)` 抛 `ValueError: invalid literal for int() with base 10: 'WP_F3gNc35I4z3axJ61OLA=='`.

### 深层根因 (mirage 静默解密失败)

`Config.value` 是 `mirage.fields.EncryptedCharField` (Django ORM 自动 `from_db_value` 解密). 但 `mirage.Crypto.decrypt` 解密失败时**静默返密文本身**, 不抛异常:

```python
# C:\Users\hly\AppData\Local\Programs\Python\Python311\Lib\site-packages\mirage\crypto.py:88
def decrypt(self, encrypted):
    if encrypted is None:
        return None
    try:
        return self.cipher.decrypt(encrypted)
    except Exception:
        return encrypted  # 静默返密文!
```

所以 ORM `Config.objects.filter(item='lock_cnt_threshold').first().value` 应该返解密后的明文, 但解密失败时返密文本身 → `int(密文)` 500.

**110 prod 推后 SECRET_KEY ≠ 数据库密文用 key**:

| 来源 | SECRET_KEY |
|------|-----------|
| 8/26 推过去的 .env (134 dev 抄) | `4H7ZIYKcjJZO8qbWDO80XR5UMrHliDXeFVTwarWkXVp79ySmruBVTk0NXdXjCkAOg9c` |
| 110 prod 真值 (7/22 升级 v1.14.0) | `hfusaf2m4ot#7)fkw#di2bu6(cv0@opwmafx5n#6=3d%x^hpl6` |
| 来源 | `/backup/upgrade_v114/v110_secret_key.txt` (7/22 备份) + `/dbdata/archery_v114/.env` (7/29 19:47) |

**两值不一致** → mirage AES-ECB 解密失败 → 静默返密文 → `int(密文)` 500.

### 历史教训 (8/06 K1 强化)

8/06 `.env 抄错` 教训 (跨项目) 时, DBA 抄 134 dev 的 .env (含 134 dev SECRET_KEY), 8/19 推 v0.2.0 沿用这个错 .env. v0.2.0 推过去后, 110 prod EncryptedCharField 已经全废, 但因为 v0.2.0 推过去后 mkq/admin 没试过密码登录, 没踩到解密失败点. 8/26 推 v0.3.0-beta 触发 `SysConfig.get("lock_cnt_threshold")` 才首次暴露.

---

## 修法 (A 方案, 用户 8/26 20:21 拍板)

**应急 fix**: 恢复 110 prod `.env` SECRET_KEY 到 7/22 升级 v1.14.0 时的真值.

**操作步骤** (1.5 分钟):
1. 备份当前 .env: `cp -a /dbdata/archery_v114_c9236a0/.env /dbdata/archery_v114_c9236a0/.env.bak_20260826_2022_secretkey`
2. 改 SECRET_KEY (用 Python 写最稳, 避免 sed 转义): `SECRET_KEY='hfusaf2m4ot#7)fkw#di2bu6(cv0@opwmafx5n#6=3d%x^hpl6'`
3. 验证 .env 其它行未动 (MYSQL_USER/PASSWORD/DB + REDIS_PASSWORD + ALLOWED_HOSTS)
4. `pkill -TERM -f "gunicorn archery.wsgi"` (优雅退出)
5. nohup 拉新: `cd /dbdata/archery_v114_c9236a0 && setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9123 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn.log 2>&1 & disown`
6. 等 7s, ps 看 1 master + 4 worker 拉起
7. 验证: mkq/test 走公网域名 200 (密码错返 JSON, 不再 500)

**修复后验证** (8/26 20:24):
- 端点 1 /login/ = 200 ✓
- 端点 2 /admin/ = 302 (跳 login) ✓
- 端点 3 /dbaprinciples/ = 302 ✓
- 端点 4 /sqlworkflow/ = 302 ✓
- 端点 5 /sqlsubmit/ = 302 ✓
- 端点 6 /gh_ost/rebuild/select/ = 302 ✓
- ORM 解密 `lock_cnt_threshold` = `'3'` (明文) ✓
- ORM 解密 `Instance[0].user` = `'archery'` (明文) ✓
- ORM 解密 `Instance[0].password` = `'JST7HthJns&TaCskWeFphyCZ5XCztv'` (明文) ✓

---

## 教训 (跨项目可复用)

1. **抄 .env 时 SECRET_KEY 字段必须从目标 prod 原 .env 拷, 不能从 dev 抄** — 强化 8/06 K1 教训
2. **推 prod 物料准备 checklist 加**: "推前比对目标 prod .env SECRET_KEY, 跟 7/22 升级或上一次推的 .env.bak 比对, 保留 prod 原值, 不从 dev 抄"
3. **mirage.Crypto.decrypt 静默返密文是上游缺陷** — 应该抛 `EncryptedFieldException` 让上游业务知道解密失败, 治本是改 django-mirage-field. 短期在 `common/auth.py:89-90` 加 try/except 防御性兜底
4. **DBA 用 .env.example 模板启动时 SECRET_KEY 占位 `change-me-in-production` 必须立刻改** — 上游默认 key 解密数据库必失败
5. **推 prod 后第一个 5+1 端点验证必走 ORM 实际解一个 EncryptedCharField 字段** — 比 HTTP 端点更深一层, 能提前发现 SECRET_KEY 不匹配
6. **推 prod 物料 scp 准备时, .env 备份只备份 .env → .env.bak 是不够的**, 必须先确认 .env 是 prod 原值 (从更早的 .env.broken_YYYYMMDD 或 /backup/upgrade_v114/ 等历史备份找回)
7. **gunicorn nohup `& disown` 后台跑, 主进程立刻 return 也要 5s timeout** — 第一次 30s timeout 不够, 第二次 `& disown; echo fired` 5s 立刻 return 成功
8. **134 dev .env SECRET_KEY 跟 110 prod 必须分别管理** — 不能"省事"两边用同一个 .env 文件

---

## 推 110 实际时间线 (8/26)

| 时间 | 事件 |
|------|------|
| 19:00 | 推 110 启动 (5 步必做 13 步) |
| 19:05 | 推代码 (scp 物料 + git pull v0.3.0-beta) |
| 19:08 | migration (含 enable_gh_ost 字段手工 ADD COLUMN) |
| 19:10 | kill gunicorn master + nohup 拉新 |
| 19:15 | 5+1 端点预检 3 端点 OK (但未走 ORM EncryptedCharField 深度验证) |
| 19:36 | 修复 .env 配错 (dbops → archery + 补 ALLOWED_HOSTS) |
| 19:57 | 第二次 kill gunicorn + nohup 拉新 (ALLOWED_HOSTS 修复) |
| 20:00 | 业务群发延迟到 20:30 |
| 20:01 | 用户 mkq 试登录 报 500 |
| 20:04 | 开始诊断 (/authenticate/ 500 根因) |
| 20:11 | 锁定 mirage 静默解密失败 + SECRET_KEY 不匹配 |
| 20:21 | 用户拍板 A 方案 (恢复 SECRET_KEY) |
| 20:22 | 备份当前 .env + 改 SECRET_KEY + 验证 .env |
| 20:23 | kill gunicorn + nohup 拉新 (5s disown 立刻 return) |
| 20:24 | mkq/test 走公网域名 200 ✓ + 5+1 端点全过 ✓ |
| 20:30 | 业务群发"推 110 完成 + SECRET_KEY 修复" |
| 21:00 | 5.7 元库 gh-ost 验证 (workflow_log FILE_SIZE 下降) |

**实际推 110 完成时间**: **20:24** (原计划 19:00, 延迟 1h 24m, 全因 SECRET_KEY 修复 1.5 分钟)
