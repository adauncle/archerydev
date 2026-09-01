# 9/1 110 prod SQL 优化工具报"请配置soar_path和test_dsn！"修复

## 症状

9/1 9:01 业务 RD mkq 在 110 prod `prodarchery.ahggwl.com:9123/slowquery_advisor/` 触发 SQL 优化工具，浏览器弹窗报错：

> 请配置soar_path和test_dsn！

DBA 排查发现 `archery.sql_config` 表 3 个 key 实际值：

| id | item | value |
|---|---|---|
| 1940 | sqladvisor | (空) |
| 1941 | soar | **(空)** |
| 1942 | soar_test_dsn | `_3ee_0AGfHGqzfONsa4j3VczIXSBOAFHojKVhv-ZFY_foY6wwU3jguOmfvWEFzAMTu0HKyBfU5-HezmvtGJBBAZyUlFycZYH-SvJZ76F6y4=` |

## 根因

`sql/sql_optimize.py:113-115` 短路检查：

```python
soar_test_dsn = SysConfig().get("soar_test_dsn")
soar_path = SysConfig().get("soar")
if not (soar_path and soar_test_dsn):
    result["status"] = 1
    result["msg"] = "请配置soar_path和test_dsn！"
    return HttpResponse(json.dumps(result), content_type="application/json")
```

`if not (soar_path and soar_test_dsn):` — 1941 soar 空 → 短路返错，**根本不走到 SOAR 调用那一步**。

`common/config.py:33-50` `SysConfig.get` 实现是 **raw 读 sql_config 表 value 字段，不解密**。所以 1942 密文存的话，SysConfig.get 拿到密文直接当 DSN 字符串拼成 `-test-dsn=_3ee_0AGf...` 传给 SOAR binary——**即使 1941 配上，1942 也会让 SOAR 调用挂**（密文当密码连 MySQL 失败）。

**所以 1941 + 1942 必须一起配对**。

## 修法

走 SQL UPDATE 一次性配对（不走 web 后台，理由：1) 业务 RD 在等不能拖，2) web 前端 mirage encrypt JS 提交会变回密文，3) SQL UPDATE 30 秒搞定 + gunicorn 不用 restart，SysConfig.get 每次查 DB）。

```sql
-- 1. 配 soar 路径 (明文)
UPDATE sql_config SET value = '/opt/archery/bin/soar' WHERE id = 1941;
-- 2. 配 soar_test_dsn (用 1942 密文解密出来的明文 DSN, 跟历史一致)
UPDATE sql_config SET value = 'archery:ldlAaBDXqKmycI6cJdDlcRgVWchsC8@172.20.2.110:3306/archery' WHERE id = 1942;
```

**1942 明文 DSN 来源**：通过 `python manage.py shell` 走 `from mirage.crypto import Crypto; print(Crypto().decrypt("..."))` 解密，返 `archery:ldlAaBDXqKmycI6cJdDlcRgVWchsC8@172.20.2.110:3306/archery`。说明之前 DBA 配过这个 DSN（用 110 prod 元库 `archery` 当 test 库，`allow-online-as-test=False` 让 SOAR 只跑 EXPLAIN 不改数据）。

## 验证

```bash
# 1. UPDATE 两条都 RC=0
# 2. SELECT 验证
1940  sqladvisor        (空)  ← 当时以为不影响, 错了, 业务 RD 切换 SQLAdvisor 端点就报错
1941  soar              /opt/archery/bin/soar         ← 配好
1942  soar_test_dsn     archery:ldlAaBDXqKmycI6cJdDlcRgVWchsC8@172.20.2.110:3306/archery  ← 配好
# 3. SOAR binary 可执行: /opt/archery/bin/soar -h → Usage of /opt/archery/bin/soar
# 4. archery 账号连通: mysql --defaults-extra-file=/root/.my.cnf -h 127.0.0.1 -e "SELECT 1" → 1
```

链路全通：业务 RD 触发 SQL 优化 → `SysConfig.get("soar")` 拿路径 → `SysConfig.get("soar_test_dsn")` 拿明文 DSN → 短路检查不触发 → SOAR binary 拿 DSN 试 EXPLAIN → 返优化建议。

## 风险 + 注意

- **配好后这两个 key 不要再 web 后台编辑**——前端 mirage encrypt JS 提交会变回密文又错。要改直接 SQL UPDATE
- **134 dev 同样问题**（1941 空 + 1942 加密），DBA 自用，等下次用了再同样改
- 不需要 gunicorn restart（SysConfig.get 每次查 DB）

## 业务 RD 验证

让 mkq 重新触发 SQL 优化工具，应该看到 SOAR 输出优化建议（不再弹窗报错）。

## 9/1 11:32 补充：1940 SQLAdvisor 路径也补齐

业务 RD 切到 SQLAdvisor 端点 (`sql.sql_optimize_sqladvisor` perm)，又报"请配置SQLAdvisor路径！"。

**根因**：`sql/sql_optimize.py:51-55` 检查 `SysConfig().get("sqladvisor")` 路径：

```python
sqladvisor_path = SysConfig().get("sqladvisor")
if sqladvisor_path is None:
    result["status"] = 1
    result["msg"] = "请配置SQLAdvisor路径！"
```

**第一次 1940 没配是我判断错了**——我以为 SQL 优化只用 SOAR，但实际上 110 prod 部署时同时装了 2 个 binary（`/opt/archery/bin/sqladvisor` 455KB + `sqladvisor_newbuild` 58KB），2 个端点独立 perm 独立调用。

**修法**：同上 SQL UPDATE：

```sql
UPDATE sql_config SET value = '/opt/archery/bin/sqladvisor' WHERE id = 1940;
```

**验证**：`/opt/archery/bin/sqladvisor -h` → `option parsing failed:Missing argument for -h`（说明 binary 启动了，参数要值不是 flag — 跟 soar 不同）。

**完整 3 key 最终状态**：

```
1940  sqladvisor        /opt/archery/bin/sqladvisor
1941  soar              /opt/archery/bin/soar
1942  soar_test_dsn     archery:ldlAaBDXqKmycI6cJdDlcRgVWchsC8@172.20.2.110:3306/archery
```

## 改动文件

- `archery.sql_config` 1940 value (UPDATE 11:32)
- `archery.sql_config` 1941 value (UPDATE 11:24)
- `archery.sql_config` 1942 value (UPDATE 11:24)

无代码改动。

## 提交

110 prod 是非 git 部署，无 commit。changelog 留档供将来推 110 时参考。
