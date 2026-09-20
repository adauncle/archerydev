# 2026-09-20 110 prod gh-ost precheck 1045 排查结论

> 排查结论: 110 prod **当前无 1045 bug**, 8/26 已修过. 阿达叔叔 9/20 13:40 排查请求时一度误判"110 prod .env 4 变量没注释",
> ssh 上去 grep 实际发现**已是注释状态**. 本 changelog 入档避免下次再误判.

## 背景 (9/20 13:40 阿达叔叔排查请求)

阿达叔叔问: "110 prod gh-ost precheck 1045 修法用哪个?"

阿达叔叔的口述诊断:
> "根因: 134 dev 演练时 .env 设了 `CUSTOM_GH_OST_PRECHECK_USER=dbops` 4 个变量, 推 110 时 DBA 拾 .env 没清空, gh-ost precheck 走 fallback 路径 `dbops@127.0.0.1:3306` (110 prod 元库没 dbops) 报 1045. settings.py 注释明确: 'prod 应保持空, 让 precheck 走 instance 标准路径'."

**修法**: 方案 A — `.env` 注释掉 4 变量 (推荐)

## 排查过程 (9/20 13:44)

按"先停 + 查一下"原则, 阿达叔叔先要求停手, 后要求查清状态再决定.

### ssh grep 双端 .env

| 端 | .env 状态 | 结果 |
|----|----------|------|
| **134 dev** `/opt/archery/prod/.env` line 69-72 | ❌ 未注释 (活动) | `CUSTOM_GH_OST_PRECHECK_USER=dbops` / `PASSWORD=TJwgoqnHBlPG5WLemg1sG@#P` |
| **110 prod** `/dbdata/archery_v114_c9236a0/.env` line 69-72 | ✅ **已注释** | `# CUSTOM_GH_OST_PRECHECK_USER=dbops` 等 4 行都是 `#` 开头 |

### settings.py 字段确认

```
archery/settings.py:425-428:
425:    CUSTOM_GH_OST_PRECHECK_HOST = env("CUSTOM_GH_OST_PRECHECK_HOST", default="")
426:    CUSTOM_GH_OST_PRECHECK_PORT = env("CUSTOM_GH_OST_PRECHECK_PORT", default=3306)
427:    CUSTOM_GH_OST_PRECHECK_USER = env("CUSTOM_GH_OST_PRECHECK_USER", default="")
428:    CUSTOM_GH_OST_PRECHECK_PASSWORD = env("CUSTOM_GH_OST_PRECHECK_PASSWORD", default="")
```

`default=""` 给 USER/PASSWORD/HOST, `default=3306` 给 PORT. .env 注释掉后走 default → precheck 走 `instance.get_username_password()` 标准路径.

### db.py 优先级逻辑确认

```
sql/extensions/ddl_gh_ost/services/db.py:44-67:
def _get_creds(instance) -> Tuple[str, str, int]:
    """拿 (user, password, host_port) 凭据.

    优先级:
        1. ``CUSTOM_GH_OST_PRECHECK_HOST`` 显式设置 → 走 .env 兜底
        2. ``instance.get_username_password()`` + 探测真实 MySQL 端口
    """
    fallback_host = getattr(settings, "CUSTOM_GH_OST_PRECHECK_HOST", "")
    if fallback_host:
        user = getattr(settings, "CUSTOM_GH_OST_PRECHECK_USER", "")
        password = getattr(settings, "CUSTOM_GH_OST_PRECHECK_PASSWORD", "")
        port = int(getattr(settings, "CUSTOM_GH_OST_PRECHECK_PORT", 3306))
        ...
        return user, password, (fallback_host, port)
    user, password = instance.get_username_password()
    ...
```

110 prod `fallback_host=""` → 走 `instance.get_username_password()` 路径 (标准路径).

### db.py 注释确认 134 dev 设计如此

```
sql/extensions/ddl_gh_ost/services/db.py:11-14:

历史凭据 fallback:
    134 dev 上 archery instance 的 user/password 是历史 mirage 加密密文,
    当前 SECRET_KEY 解不出来 → ``instance.get_username_password()`` 返回密文,
    MySQL 报 1045. 开发者设置 ``CUSTOM_GH_OST_PRECHECK_*`` 后会优先用这套凭据直连,
    跳过 instance 解密(仅 dev/演练用, prod 不应启用).
```

134 dev 这 4 变量是 **dev 设计如此**, 不应该清.

### error.log 实际验证

```
ssh 110 prod + tail -200 /dbdata/archery_v114_c9236a0/logs/error.log | grep "1045|precheck|dbops"
→ 空 (无任何最近 1045/precheck/dbops 报错)
```

## 排查结论

### 1. 110 prod 当前无 1045 bug ✅

- `.env` 4 变量已注释 (8/26 修复后状态)
- `error.log` 最近 200 行无 1045/precheck/dbops 报错
- `db.py` fallback 路径不命中, 走 `instance.get_username_password()` 标准路径

### 2. 134 dev .env 4 变量不应清 ⚠️

- 这是 dev-only 设计 (instance 凭据是历史 mirage 加密密文, SECRET_KEY 解不出来)
- 清掉会让 dev 的 gh-ost precheck 报 1045, dev 不能演练

### 3. 8/26 已修过这个 P0 ✅

`docs/changelogs/2026-08-26_push110-ghost-precheck-dev-fallback-bug.md` 完整记录:
- 症状: 8/26 20:49 业务 RD mkq 提单, gh-ost precheck 4/5 项 FAIL 报 `1045 dbops@127.0.0.1`
- 根因: 134 dev 演练时 .env 加 4 变量, 110 prod .env 抄过去没清
- 修法: **110 prod .env 注释 4 变量** (本次排查请求的方案 A)
- 验证: 业务 RD 重新提单, gh-ost precheck 5/5 PASS

## 误判原因分析

我刚才一开始以为"110 prod .env 没注释, 需要修", 这个误判是因为:
1. 我**没有 ssh 上去实际 grep**, 直接根据口述诊断推断状态
2. 我**没查 8/26 changelog 历史记录**, 那次修复完整记录在案
3. 我**没区分 dev-only 设计和 prod 应有的状态**, 把 134 dev 的活动状态和 110 prod 应有状态混淆

**正确做法**: ssh 实际查 `.env` + `error.log`, 区分 dev/prod 状态, 查历史 changelog.

## 实战新发现 (1 条入 MEMORY, 跨项目可复用)

**dev-only .env 兜底凭据跟 prod 应有状态不能混判 (跨项目应急响应, 9/20 实战新发现)**:
- 跨项目排查 .env 状态时, **不能基于"演练时设了变量"推断 prod 状态**, 必须 ssh 实际 grep
- 实战踩坑: 9/20 阿达叔叔排查 110 prod gh-ost precheck 1045, 我**没 ssh 实际查**就推断"110 prod 4 变量没注释, 需要修". 实际 ssh 上去发现 110 prod **已是注释状态** (8/26 已修), 不需要动
- **dev-only 兜底凭据 vs prod 应有状态**: dev .env 的 fallback 变量 (134 dev 4 变量) 是 **dev 设计如此** (instance 密文解不开), 清掉会让 dev 不能演练; prod .env 应保持注释 (settings.py `default=""`)
- 修法: 排查 .env 状态时 (1) ssh 实际 grep 双端 (2) 查 error.log 最近 N 行有没有实际报错 (3) 查历史 changelog 是否已修过 (4) 区分 dev/prod 状态

## 关联

- 8/26 commit (待补, 推 110 完成后整体 commit): 110 prod .env 注释 4 变量
- `docs/changelogs/2026-08-26_push110-ghost-precheck-dev-fallback-bug.md` (8/26 P0 bug 完整记录)
- `archery/settings.py:425-428` (4 个 CUSTOM_GH_OST_PRECHECK_* 字段定义)
- `sql/extensions/ddl_gh_ost/services/db.py:11-14` (dev-only 设计注释)
- `sql/extensions/ddl_gh_ost/services/db.py:44-67` (`_get_creds` 优先级逻辑)