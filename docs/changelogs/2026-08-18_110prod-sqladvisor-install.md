# 2026-08-18 110 prod SQL Advisor 二进制安装 + 路径配置

## 一句话

110 prod 装 sqladvisor 二进制 (从 docker overlay 复用, 跳过源码编译) + admin 后台配路径 `/usr/local/bin/sqladvisor`, 业务用户点 SQL 优化能跑真 sqladvisor 出报告 (不再返 "请配置")。这是 8/18 上午修法 B 之后的 A 方案收尾。

## 背景

8/18 上午发现 110 prod `/slowquery_advisor/` 报 500 错 `[Errno 2] No such file or directory: '/opt/archery/src/plugins/sqladvisor'`,根因是 v1.10.0 docker 时代 admin 后台配的 sqladvisor 路径, 8/05 切 v1.14.0 裸机后没改, 二进制也没装。当时选了修法 B (admin 后台清空) 立即消除 500 报错, 后续做修法 A (装 sqladvisor)。

本 changelog 记录 A 方案全过程。

## 110 prod 编译环境摸底

| 项 | 现状 |
|---|---|
| OS | CentOS 7 (Core) |
| Kernel | 3.10.0-1160.88.1.el7.x86_64 |
| gcc / g++ / make | 4.8.5 / 4.8.5 / 3.82 (有) |
| cmake | **没装** (但 SQLAdvisor 上游用 cmake) |
| libmysqlclient | 已装 (/usr/lib64/mysql/libmysqlclient.so.18/20, /usr/include/mysql/mysql.h) |
| flex / bison / glib2 | 已装 (编译 SQLAdvisor 必要) |
| 出口网络 | github 5s 超时 (受限), gitee 200ms, api.github.com 200ms |
| **docker overlay 残留** | **`/var/lib/docker/overlay2/1bdc.../diff/usr/local/sqlparser/` (lib + share) + `3ff3.../diff/opt/sqladvisor` (二进制, 2023-01-17 编译)** |

**关键发现**: docker overlay 有现成 sqladvisor 二进制 + 完整 sqlparser 库, 可以直接复用跳过编译。

## 安装过程 (跳过源码编译)

### 步骤 1: 复用 docker overlay 残留

```bash
# 1) 复制 sqladvisor 二进制
cp -av /var/lib/docker/overlay2/3ff3.../diff/opt/sqladvisor /usr/local/bin/sqladvisor
chmod +x /usr/local/bin/sqladvisor

# 2) 复制 sqlparser 完整目录 (bin/lib/share/include)
rm -rf /usr/local/sqlparser
cp -r /var/lib/docker/overlay2/1bdc.../diff/usr/local/sqlparser /usr/local/

# 3) 写 ldconfig 配置
echo '/usr/local/sqlparser/lib' > /etc/ld.so.conf.d/sqlparser.conf
ldconfig
ldconfig -p | grep -i sqlparser
# → libsqlparser-debug.so (libc6,x86-64) => /usr/local/sqlparser/lib/libsqlparser-debug.so
```

### 步骤 2: 测试 sqladvisor 跑真实 SQL

```bash
sqladvisor -h 127.0.0.1 -P 3306 -u archery -p <archery_pass> \
  -d archery -q "SELECT 1" -v 1
# → [Note] 第1步: 对SQL解析优化之后得到的SQL:select 1 AS `1`
# → [Note] 第2步: SQLAdvisor结束!
# → rc: 0 ✓
```

测了 3 个 SQL (SELECT 1 / 单表查询 / 业务用户 22 字段大查询), 都跑成功。
**已知问题**: SQLAdvisor 上游 "Invalid parameter number" bug (2019 年最后一次更新), 不影响解析, 只是 IN 多值时不输出索引建议。

### 步骤 3: admin 后台配路径

```python
# 110 prod manage.py shell
from common.config import SysConfig
SysConfig().set('sqladvisor', '/usr/local/bin/sqladvisor')
```

加密逻辑 (django-mirage-field 1.4.0):
- 算法: AES-ECB (MIRAGE_CIPHER_MODE 默认 ECB)
- Key: SECRET_KEY (50 字符, mirage 要求 >= 32)
- 流程: 明文 → PKCS7 padding → AES encrypt → base64 urlsafe b64encode
- 解密: 反向

**SysConfig().set 内部用 `update_or_create(item=key, defaults={"value": db_value})`**, Django 自动调 get_db_prep_value 加密, 不用手算。

### 步骤 4: 验证加密 + 解密

```sql
SELECT id, item, value, LENGTH(value) AS value_len FROM sql_config WHERE item='sqladvisor';
-- id=1940 item=sqladvisor value=Gw4nMN7a3GmNQxD94R5_QP3IiHXx3m2ydAWJ92ryZxE= value_len=44
```

```python
SysConfig().get('sqladvisor')  # → '/usr/local/bin/sqladvisor' ✓
```

## 涉及文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `/usr/local/bin/sqladvisor` | 新增 | sqladvisor 二进制 (从 docker overlay 复用) |
| `/usr/local/sqlparser/` | 新增 | sqlparser 完整目录 (bin/lib/share/include) |
| `/etc/ld.so.conf.d/sqlparser.conf` | 新增 | ldconfig 配置 |
| `sql_config.id=1940` | 修改 | item=sqladvisor, value 改为加密的 `/usr/local/bin/sqladvisor` |
| `scripts/_archive/mirage_crypto_110prod.py` | 归档 | mirage 加密库实现 (留档) |
| `docs/changelogs/2026-08-18_110prod-sqladvisor-install.md` | 新增 | 本 changelog |

## 推 110 当天 5 步必做

推 v0.3.0-beta 110 prod 时, 5 步必做**步骤 6 (清空 sqladvisor) 已加在 8/18 上午 commit `25ce9b3`**, 现在 A 方案完成, 步骤 6 改成:
- 检测 sqladvisor value 是否空
- 空 → 跳过 (新装已配)
- 不空 → 清空 (历史残留)

## 教训

1. **不要从源码编译 SQLAdvisor** (依赖 cmake / glib2 / libmysqlclient, 装一堆 dev 依赖), 优先复用现成二进制
2. **docker 容器删除后 overlay 仍存文件**, `find /var/lib/docker/overlay2 -name 'sqladvisor'` 能找到老容器的二进制 + 库
3. **Archery 加密字段用 django-mirage-field 1.4.0** (不是 django-cryptography), AES-ECB, SECRET_KEY >= 32
4. **配置 sqladvisor item 走 `SysConfig().set()` 自动加密**, 不要 SQL UPDATE 明文
5. **SECRET_KEY 长度要求 >= 32**, Archery 上游默认 SECRET_KEY 50 字符够用
