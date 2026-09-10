# D39 字段变更检测 type 段 decimal(M, N) 截断修复 (2026-09-10 10:50)

## 业务方反馈 (9/10 10:50 截图)
- 9/10 10:50 业务方提交 DDL: 
  ```sql
  MODIFY COLUMN `left_amount` decimal(15, 4) NULL DEFAULT 0.00 COMMENT '左侧数据金额',
  MODIFY COLUMN `right_amount` decimal(15, 4) NULL DEFAULT 0.00 COMMENT '右侧数据金额'
  ```
- 字段变更检测改后部分只显示 `DECIMAL(15` (缺 `, 4)` 跟后续)
- 同时 default / comment 也被错误识别 (default 0.00 显示 (无), comment '左侧数据金额' 显示 (空))
- 业务方不能看到真实 type 变更, 风险评估错

## 根因
`sql/extensions/ddl_gh_ost/services/column_diff.py` line 275 + 291 `_RE_MODIFY` / `_RE_ADD` 正则 type 段用 `[^,]+`:

```python
r"(?P<definition>"
r"[^,]+"  # 类型段 (greedy, 吃尽可能多)
r"(?:\s+CHARACTER\s+SET\s+\S+)?"  # 可选 CHARSET
r"(?:\s+COLLATE\s+\S+)?"           # 可选 COLLATE
r"(?:\s+NOT\s+NULL)?"               # 可选 NOT NULL
r"(?:\s+NULL)?"                     # 可选 NULL
r"(?:\s+DEFAULT\s+\S+(?:\s*\([^)]*\))?)?"  # 可选 DEFAULT
r"(?:\s+COMMENT\s+'(?:[^']|'')*')?"  # 可选 COMMENT
r"(?:\s+ON\s+UPDATE\s+CURRENT_TIMESTAMP(?:\(\d+\))?)?"  # 可选 ON UPDATE
r")"
```

**机制**: 业务方 SQL `decimal(15, 4) NULL DEFAULT 0.00 COMMENT '左侧数据金额'`:
- `[^,]+` 贪婪吃 `decimal(15` (4 字符, 第一个逗号处停止)
- 后续 optional 段 `\s+CHARACTER\s+SET` / `\s+COLLATE` / `\s+NOT\s+NULL` 全部不匹配 (剩下 `, 4) NULL DEFAULT 0.00 ...`)
- `\s+NULL` 匹配 ` NULL` (前面 consume `4)`, 剩 ` DEFAULT 0.00 COMMENT '左侧数据金额'`)
- `\s+DEFAULT\s+\S+` 匹配 ` DEFAULT 0.00`
- `\s+COMMENT\s+'[^']*'` 匹配 ` COMMENT '左侧数据金额'`
- **definition 段匹配到**: `decimal(15` + ` NULL` + ` DEFAULT 0.00` + ` COMMENT '左侧数据金额'`
- `_parse_definition` 后续 line 384 `result["type"] = s.strip().upper()` 拿到的就是 `DECIMAL(15` ❌

`enum('a','b','c')` / `set(...)` / `geometry(...)` / `point(x, y)` 等含内部逗号的字段类型都受影响 (但 decimal/geometry 是业务方实战最常碰到的).

## 实战踩坑溯源
- 8/26 21:34 D15 引入这个 regex, 当时业务方没 decimal(M,N) 实战
- 9/2 D18 + 9/3 D22 + 9/3 D25 + 9/3 D27 实战, 都没碰到 decimal(M,N) 字段变更
- 9/9 D38 续 6 修过 DEFAULT/COMMENT 多单引号, 没看 type 段
- 9/10 业务方实战, 才暴露这个 bug

## 修法
改 `[^,]+` 为允许括号内逗号:

```python
r"(?:[^,()]+|\([^)]*\))+"  # 类型段: 允许括号块 (内含逗号) + 非逗号非括号字符
```

`_RE_MODIFY` 和 `_RE_ADD` 两处都改 (D22 D15 实战都用了同样的 regex, 同一 bug).

## 演练 PASS 计划
- 134 dev 写 Python 单元测试 + force_login 演练 decimal(15, 4) / enum / set 等
- 110 prod 推 + 真 HTTP 演练 (D38 续 7 实战新发现: 必列推送清单 + 三环境 md5 + 演练老工单新工单两边)

## 演练 PASS 记录 (9/10 11:00-11:50)

### 134 dev 单元测试 (scripts/_d39_unit_test.py, 8/8 PASS)
| 测试 | 输入 | 期望 type | 实际 type |
|------|------|----------|----------|
| test_modify_decimal | `MODIFY COLUMN left_amount decimal(15, 4) NULL DEFAULT 0.00 COMMENT 'left'` | DECIMAL(15, 4) | ✅ `decimal(15, 4) NULL DEFAULT 0.00 COMMENT 'left'` 完整 |
| test_add_decimal | `ADD COLUMN amount decimal(10, 2) NOT NULL DEFAULT 0` | DECIMAL(10, 2) | ✅ 完整 |
| test_enum_with_internal_comma | `enum('a','b','c')` | 完整 | ✅ 完整 |
| test_set_with_internal_comma | `set('a','b','c','d')` | 完整 | ✅ 完整 |
| test_geometry_point | `point(10, 5)` | 完整 | ✅ 完整 |
| test_decimal_with_charset_collate | `varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci` | 完整 | ✅ 完整 |
| test_parse_definition_decimal | 业务方真实 SQL | type=DECIMAL(15, 4) / default=0.00 / comment='左侧数据金额' | ✅ 全对 |
| test_parse_definition_int_basic | 回归: `int(11) NOT NULL DEFAULT 0` | INT(11) | ✅ 回归 PASS |

### 134 dev 业务方真实 SQL 演练 (scripts/_d39_drill_134.py, 4/4 PASS)
| 列 | 旧 type (库里) | 新 type (业务方提交) | 结果 |
|----|---------------|------------------|------|
| check_type | TINYINT (literal) | TINYINT | ✅ |
| left_amount | decimal(15, 2) (库里) | DECIMAL(15, 4) (修复) | ✅ 完整 |
| right_amount | decimal(15, 2) (库里) | DECIMAL(15, 4) (修复) | ✅ 完整 |
| extended_fields | - | TEXT (ADD) | ✅ |

### 110 prod 推 + 真 HTTP 演练 (scripts/_d39_drill_http_110.py, 9/10 11:46 PASS)

**D38 续 7 checklist 三环境 md5 对比**:
| 环境 | column_diff.py md5 |
|------|-------------------|
| Windows 本地 | `BA3F371FA294ACB028B0847BFEE54E38` |
| 110 prod 推后 | `ba3f371fa294acb028b0847bfee54e38` ✅ 一致 |
| 134 dev (Linux 换行差异) | `44b18172e2456d9da122d25608338b23` |

**真 HTTP 演练** (archery superuser, Client.force_login + POST /gh_ost/column_diff/):
- HTTP 200, ok=True
- tables[0] = etc_check_diff, table_exists=True, 4 columns
- `left_amount`: cur.type=`decimal(15,2)` (库里) → new.type=`DECIMAL(15, 4)` (业务方提交) ✅ 完整
- `right_amount`: cur.type=`decimal(15,2)` (库里) → new.type=`DECIMAL(15, 4)` ✅ 完整
- default=`0.00`, comment=`左侧数据金额`/`右侧数据金额` 全部正确
- extended_fields ADD: new.type=`TEXT` ✅

**D38 续 7 回归演练 (老工单两边)**:
- wf#4791 (9/9 源工单): HTTP 200, size 95096, 500error=False ✅
- wf#4792 (9/9 镜像工单): HTTP 200, size 95763, 500error=False ✅
- wf#4783 (9/3 老工单, pic_url): HTTP 200, size 95102, 500error=False ✅

**gunicorn 状态 (9/10 11:51)**:
- 110 prod: master 58208 + 5 workers, 9123 LISTEN, /login/ HTTP 200 ✅
- 134 dev: master 53479 + 4 workers, 9003 LISTEN, /login/ HTTP 200 ✅

## 改动 1 个文件
1. `sql/extensions/ddl_gh_ost/services/column_diff.py` (line 275 + 291) - 改 `[^,]+` 为 `(?:[^,()]+|\([^)]*\))+`

## 实战新发现 (跨项目可复用, 1 条)
**字段类型 regex 必支持内嵌括号逗号** (D39 实战新发现) - 跨项目做"字段变更检测"功能, type 段正则用 `[^,]+` 截断 decimal(M,N) / enum('a','b') / point(x, y) / set(...) 等含内嵌逗号类型. 正确做法: `(?P<type>(?:[^,()]+|\([^)]*\))+)` 允许括号内含逗号. 实战踩坑: 8/26 D15 引入 regex, 9/10 业务方 decimal(15,4) 实战才暴露

## 实战新发现 (跨项目可复用, 1 条补充)
**Windows 跟 110 prod 的 SSH 兼容性问题 (OpenSSH 9.5 vs 7.4) 用 plink 解决** (D39 实战新发现) - Windows 11 自带 OpenSSH 9.5 跟 110 prod 老 OpenSSH 7.4 在 KEX/Auth 阶段兼容差, `ssh root@172.20.2.110 "echo"` 卡 60+ 秒. 跨项目推 110 prod 这种老服务器, 用 `plink -ssh -pw PWD -hostkey SHA256:... root@host "cmd"` 替 ssh 解决. plink 走 putty 协议不依赖 OpenSSH 9.5
