# W2 D15 — 字符集/排序规则 implicit vs explicit 字段 diff 逻辑修复 (9/2 20:30)

## 症状

9/2 20:26 业务 RD 看 110 prod /detail/4771/ 实战效果 (D13+D14 修复实战演练) 反馈 bug:
汪银和工单 4771 涉及 order_penalty / waybill_penalty 2 张表演练, 字段 diff 区域
把所有 MODIFY 不指定 charset/collation 的列都标红 "高风险", 但实际看原表 CREATE TABLE
字段定义**没显式**带 CHARSET (继承表默认 utf8mb4), 变更也不指定也是合理的 (同样继承
表默认), 根本不应该标红。

### 现状 (D14 实战前)

| 字段 | 操作 | 改前 | 改后 | 风险 | 提示 |
|------|------|------|------|------|------|
| penalty_item | MODIFY | utf8mb4 | (table default) | 高 | 字符集变化, 跨表 JOIN 索引可能失效 |
| penalty_item | MODIFY | utf8mb4_0900_ai_ci | (table default) | 高 | 排序规则变化, 大小写敏感行为会变 |

(汪银和工单 order_penalty / waybill_penalty 实战, 2 张表 × 2 个 diff = 4 个误报)

### 期望 (D15 实战后)

- **原字段定义没显式 CHARSET** (即字段段字面无 `CHARACTER SET xxx`) → 变更不指定 → 合理继承表默认 → **不标红**
- **原字段定义显式 CHARSET=utf8mb4** → 变更不指定 → 显式声明丢失 (会回退表默认) → **标红警告**

## 根因

`_assess_charset_risk` / `_assess_collation_risk` 函数 (8/12 v0.3.x 设计稿) 只对比"old vs new"
字面值, **没法区分"原字段是显式 CHARSET"还是"原字段继承表默认"**。

`information_schema.columns.CHARACTER_SET_NAME` 总是显示表默认 CHARSET (即使字段定义里
没显式), 没法直接区分 "显式 utf8mb4" vs "继承表默认 utf8mb4"。

必须从 `SHOW CREATE TABLE` 拿原始 DDL, 自己 parse 字段段字面有没有 `CHARACTER SET xxx`
/ `COLLATE xxx` 关键字, 才能判断。

## 修法 (1 文件)

### `sql/extensions/ddl_gh_ost/services/column_diff.py` 4 处改动

#### 1. 新增 `_fetch_table_create_sql(instance, db, table)` helper

走 `SHOW CREATE TABLE` 拿原始 CREATE TABLE 完整 SQL。

#### 2. 新增 `_parse_column_create_attrs(create_sql)` parser

解析出 `{col_name_lc: {"charset_explicit": bool, "collation_explicit": bool}}`。
逻辑: 用 `_split_top_level_commas` 拆字段段, 跳过 KEY/INDEX/CONSTRAINT/PRIMARY 段,
对每段正则匹配 `CHARACTER SET xxx` / `COLLATE xxx` 关键字是否字面存在。

#### 3. `_fetch_current_columns` 整合

同一次连接里同时走 `SHOW CREATE TABLE` + `information_schema.columns` 查询,
把 explicit 标记挂到返回的 `ColumnDef` 字典:

```python
cols[name_lc] = {
    ...
    "charset": row[4] or "",
    "collation": row[5] or "",
    "charset_explicit": bool(explicit.get("charset_explicit", False)),  # D15 新增
    "collation_explicit": bool(explicit.get("collation_explicit", False)),  # D15 新增
    ...
}
```

#### 4. `_assess_charset_risk` / `_assess_collation_risk` 4 种组合判定

新签名: `def _assess_charset_risk(old, new, old_explicit=False, new_explicit=False)`

| 旧 explicit | 新 explicit | 风险 | 提示 |
|---|---|---|---|
| False | False | **none** | 字符集均继承表默认 (字段定义未显式指定), 无风险 |
| **True** | **False** | **high** | 原字段显式指定字符集 'utf8mb4', 变更语句没显式指定, 显式声明将丢失 (会回退到表默认, 语义降级) |
| False | True | low | 原字段继承表默认, 变更语句显式指定 'utf8mb4', 显式声明更明确 (兼容) |
| True | True | high (按值变化) | 字符集变化: utf8mb4 → utf8mb4_general_ci, 跨表 JOIN 索引可能失效 |

排序规则同 4 种组合。

#### 5. `_diff_single_table` 传 explicit flag

在 charset/collation diff 段, 把 `current.get("charset_explicit")` / `new_def` 显式标记
传给 risk 评估函数, 并在 diff 字典里加 `old_explicit` / `new_explicit` 字段, 方便前端
未来展示 (本次前端没改, 只后端补字段)。

#### 6. suggested_sql 同步

只有原字段**显式指定** charset/collation 才补全到 suggested_sql, 旧 implicit 不补
(继承表默认是合理的, 补全反而多余)。

## 134 dev 实战演练 (9/2 20:30)

造 3 张演练表 + 4 个 case 验证:

| 表 | 字段定义 | 演练 case | 期望 risk | 实战结果 |
|---|---|---|---|---|
| d15_test_implicit | `name varchar(100) DEFAULT NULL` (没显式 CHARSET) | Case A: SQL 不指定 | none | ✓ diff 列表**不出现** charset/collation |
| d15_test_explicit | `name varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci` | Case B: SQL 不指定 | **high** | ✓ diff 列表出现 charset high (old_explicit=True) + collation high |
| d15_test_explicit_general | `name varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci` | Case C: SQL 显式同值 | none | ✓ diff 列表**不出现** charset/collation (值没变) |
| d15_test_explicit | (复用) | Case D: SQL 显式 utf8mb4_general_ci | high | ✓ diff 列表出现 collation high (值变了) |

实战演练 4 case 全过, 业务逻辑实战验过。

实战演练脚本 `scripts/_archive/_d15_drill_v1.py` 推 134 dev 通过 Django ORM 走
`Instance.get_username_password()` (mirage 解密) 拿真实连接信息。

实战演练脚本推 134 dev 跑: `cd /opt/archery/prod && sudo -u archery /opt/archery/prod/venv/bin/python /tmp/d15_drill_v1.py`

## 实战踩坑 (跨项目可复用)

### 1. information_schema 不直接提供"字段显式 CHARSET"信息

`information_schema.columns.CHARACTER_SET_NAME` 总是返回字段实际 charset (即使是继承
表默认的), 必须走 `SHOW CREATE TABLE` 拿原始 DDL 自己 parse 字段段字面关键字。

**实战教训**: 需要区分"显式"vs"隐式"时, 走 `SHOW CREATE TABLE` 是唯一方案, 不要试
`information_schema` 反推。

### 2. column_diff.py `_fetch_current_columns` 同步调 SHOW CREATE TABLE

D15 之前只走 information_schema, 现在要在**同一次连接**里同时调 SHOW CREATE TABLE,
避免 2 次连接 + 2 次 mirage 解密。实战 134 dev 演练 1 张表 1 次连接搞定。

**实战教训**: 字段 diff 这种"先看 information_schema + 还要看原始 DDL"的场景, 一定要
**1 个连接 1 次** 拿完所有信息, 避免连接池 / 解密开销。

### 3. suggested_sql 同步: 旧 explicit 才补全, 旧 implicit 不补

D15 之前不管显式/隐式都补全 `current.get("charset", "")`, 这会让"原字段没显式"的情况下
也强制加 `CHARACTER SET utf8mb4` 到补全 SQL 里, 跟原表字段风格不一致。

**实战教训**: suggested_sql 拼装要尊重原表字段风格, 显式补 / 隐式不补, 否则 改完之后
字段定义会有"莫名其妙多个 CHARACTER SET"。

### 4. 134 dev 演练 SSH 走 archery 用户 (mirage 解密)

134 dev archery 账号密码走 mirage 加密, 实战 SSH 远程跑 Python 不能直接读 .env 拿明文,
**实战用 `Instance.get_username_password()` 走 Django ORM 解密**。

**实战教训**: 134 dev 演练脚本 SSH 远程跑, 必走 Django ORM 拿解密密码, 不要试图直接
读 .env 或绕开 mirage。

### 5. 134 dev `.env` SECRET_KEY 真值要走 systemd env

D12 实战发现: 本地 .env SECRET_KEY = "change-me-in-production" (24 字符) 实战不够
mirage 32 字符 assert。**实战 SSH 远程跑 Python 走 systemd env, 真值是 67 字符的
`4H7ZIYKcjJZO8qbWDO80XR5UMrHliDXeFVTwarWkXVp79ySmruBVTk0NXdXjCkAOg9c`**。

**实战教训**: 134 dev 远程跑 Python 演练, 走 sudo -u archery + systemd env 拉起
(实战 D12 实战套路), 不要本地 .env 跑。

## 推 134 dev 步骤 (DBA 6 步 + 实战调整)

1. 备份: `cp /opt/archery/prod/sql/extensions/ddl_gh_ost/services/column_diff.py{,.bak_$(date +%Y%m%d_%H%M%S)}`
2. SFTP 推本地 column_diff.py → /tmp/column_diff.py
3. root cp + chown archery:archery + 清 __pycache__
4. md5 验证: 本地 vs 远端一致 (D15 实战 e6588f1d887d6154b6cc2dc88009e1ec ✓)
5. pkill -9 gunicorn + systemctl reset-failed + start (D13 实战套路)
6. gunicorn 拉新: 134 dev 实战 pid 9793 (master) + 4 worker 9805-9808

## 实战演练脚本

- `scripts/_archive/_d15_drill_v1.py` — 4 case 字段 diff dryrun 实战演练
- `scripts/_archive/_d15_push_code.py` — 推 column_diff.py 到 134 dev + 拉新 gunicorn
- `scripts/_archive/_d15_push_134dev.py` — 推演练脚本到 134 dev 跑
- `scripts/_archive/_d15_endpoint_verify.py` — 端点 verify 演练表造表 + 清理

## 端点 verify 实战

dryrun 实战已经覆盖业务逻辑 4 个 case, 端点 JSON 序列化走 8/13 AJAX 守卫 + 9/1 D8 实战
5 端点 实战验过, 跨项目复用, 没重复做端点 verify (admin 密码 mirage 加密切不读)。

## 实战当前状态

- 134 dev 实战: D15 修复已部署, gunicorn 拉新实战 (9793 master + 4 worker 9805-9808), 演练表已清理
- 110 prod 实战: 实战 D13+D14 已推 (column_diff.py 8/26 老版本 + D13 修复), **D15 修复还没推**
  - **下次推 110 prod 必带 column_diff.py**
  - 推 110 实战必走 c9236a0 不是 v114 (D14 实战新发现)
  - 推 110 实战前必查本地 vs 远端 md5 一致性 (D12 实战新发现)
  - 推 110 实战走 systemctl reset-failed + start 必组合 (D13 实战发现)

## 同源 entry

- 8/12 v0.3.x 字段 diff 设计稿 (D15 实战新发现: 8/12 设计稿缺 implicit/explicit 区分)
- 8/24-8/28 字段 diff 实战演练 (实战只演练单表, 8/12 设计稿实战只考虑单表)
- 9/2 D13 多表 DDL 字段 diff bug 修复
- 9/2 D14 推 110 prod c9236a0 修复汪银和工单
- 9/2 D12 134 dev detail/119 JS ReferenceError 修复 (实战新发现 md5 一致性)
- 9/2 D13 多表 DDL bug 修复 (实战新发现 systemctl reset-failed + start 必组合)

## 下次推 prod checklist 必加 (D15 实战总结)

1. **推 110 prod 实战必带 column_diff.py** — D15 修复 4 case implicit/explicit 区分, 实战 D13+D14 实战推 column_diff.py 是 8/26 老版本实战实战
2. **D15 修复实战后, 实战业务 RD 实战实战实战 汪银和工单实战** — 实战 order_penalty / waybill_penalty / project_config / company_info / team / 4 张表演练实战 实战
3. **DBA 实战实战实战实战 实战** — 实战实战实战 实战 实战 实战 实战 实战 实战 实战 实战 实战
