# 2026-08-24 gh-ost precheck 过度限制修正 (DROP COLUMN 误禁)

## 摘要

修复 `sql/extensions/ddl_gh_ost/services/precheck.py:34-39` 误将 `DROP` 加进 `FORBIDDEN_ALTER_OPERATIONS` 的问题。gh-ost 1.1.x 官方**明确支持** `DROP COLUMN`, 8/06 v0.3.0-alpha 拍板时误以为是 gh-ost 限制, 导致业务 RD 提 `ALTER TABLE t DROP COLUMN c` 工单被预检 FAIL, 没法走 gh-ost 流程。

## 根因

8/06 v0.3.0-alpha 加 `FORBIDDEN_ALTER_OPERATIONS` 时, 拍了 "RENAME, DROP, TRUNCATE" 三个关键词, 注释说 "这些不是 ALTER"。**但 DROP COLUMN 实际是 ALTER 的一种合法子句, gh-ost 官方支持**。

```python
# 修前
FORBIDDEN_ALTER_OPERATIONS = (
    "RENAME", "DROP", "TRUNCATE",  # 这些不是 ALTER
)
# check_alter_sql line 235
for keyword in ("RENAME TO", "DROP ", "TRUNCATE "):
    if keyword in first.upper():
        return _fail(name, f"检测到禁用操作 {keyword.strip()}, gh-ost 不支持")
```

gh-ost 官方文档 `https://github.com/github/gh-ost/blob/master/doc/requirements-and-limitations.md` 明确:
- 限制列表 (Limitations) 只有: **FOREIGN KEY, TRIGGERS, JSON IN PK, 主键, FEDERATED, ENCRYPTED BINLOG, RENAME TO** 等
- **没有 DROP COLUMN**
- gh-ost 实际就是为 ADD/DROP/MODIFY 设计的工具

## 复现 (8/24 用户反馈)

业务用户 / DBA 提工单 #88:
```sql
ALTER TABLE accesscard_black_detail DROP COLUMN test3;
```

提交时勾选 "启用 gh-ost 无锁变更", 预检 FAIL:
```
✗ FAIL alter_sql 检测到禁用操作 DROP, gh-ost 不支持
```

业务用户疑惑: 既然 gh-ost 是给"无锁 DDL 变更"用的, 为什么不支持最常见的 DROP COLUMN?

## 修法

`sql/extensions/ddl_gh_ost/services/precheck.py:34-39` + line 235-241:

```python
## CUSTOM-MODIFIED: 8/24 修正 gh-ost precheck 过度限制 @ 2026-08-24 @ mavis
FORBIDDEN_ALTER_OPERATIONS = (
    "RENAME",  # ALTER TABLE ... RENAME TO, gh-ost 不支持
    "TRUNCATE",  # TRUNCATE TABLE 不是 ALTER, 不该走 gh-ost
    # 8/24 移除 "DROP": gh-ost 官方支持 DROP COLUMN / DROP INDEX
    # 改主键: gh-ost 1.1.x 已支持, 但 alpha 先禁
    # 改索引类型 / 全文索引: gh-ost 不支持
    # 外键约束: gh-ost 不支持 + 引用的其他表同步问题
)

# check_alter_sql 同步修
for keyword in ("RENAME TO", "TRUNCATE"):  # 不带尾空格, 避免 "TRUNCATE;" 边界 case 漏报
    if keyword in first.upper():
        return _fail(name, ...)
```

边界 case 顺手修: `"TRUNCATE "` (带尾空格) 在 `"TRUNCATE;"` 里 substring 匹配不到, 会漏报。改成 `"TRUNCATE"` 不带尾空格。

## 演练 (134 dev, 8/24 14:16)

5 个 case 端到端跑通:

| Test | SQL | 修前 | 修后 | 期望 |
|---|---|---|---|---|
| 1 | `ALTER TABLE t DROP COLUMN c` | ✗ FAIL | ✓ PASS | ✓ |
| 2 | `ALTER TABLE t RENAME TO t2` | ✗ FAIL | ✗ FAIL | ✗ (gh-ost 不支持 RENAME) |
| 3 | `ALTER TABLE t TRUNCATE` | ⚠️ 漏报 (PASS) | ✗ FAIL | ✗ (不是合法 ALTER) |
| 4 | `ALTER TABLE t ADD COLUMN c INT` | ✓ PASS | ✓ PASS | ✓ |
| 5 | `ALTER TABLE t MODIFY COLUMN c BIGINT` | ✓ PASS | ✓ PASS | ✓ |

**演练流程**:
1. scp 修后 `precheck.py` 到 134 dev (14:12)
2. 按 8/24 SOP 跑 reload gunicorn (commit `7ab3c40` 配套 runbook):
   - master 15701 → 32980 (systemd 自动拉起, 7s 内)
3. 跑 5 个 case, 全部符合期望

**演练脚本**: `scripts/_archive/_drill_precheck_8_24_20260824.py`

## 影响范围

| 范围 | 状态 |
|---|---|
| `ALTER TABLE t DROP COLUMN c` | ✅ 修后通过预检, 可走 gh-ost 流程 |
| `ALTER TABLE t DROP INDEX idx` | ✅ 修后通过预检, 可走 gh-ost 流程 |
| `ALTER TABLE t RENAME TO t2` | ✗ 仍 FAIL (gh-ost 官方不支持, 正确) |
| `ALTER TABLE t TRUNCATE` | ✗ 修后 FAIL (修前漏报, 已修) |
| `ALTER TABLE t ADD/MODIFY COLUMN` | ✓ 一直 PASS, 不受影响 |
| gh-ost 工具实际行为 | ✓ 不变, gh-ost 一直支持 DROP COLUMN, 这次只修预检 |

## 8/24 教训 (跨项目可复用, 重要)

**二次开发前必须查上游工具的真实支持列表, 不要从代码脑补**:
- 之前 (8/06) 我加 `FORBIDDEN_ALTER_OPERATIONS` 时, **没查 gh-ost 官方文档**, 直接写了 "DROP = 禁用"
- 8/24 用户报错才发现, 差点被业务 RD 当成 gh-ost 真不支持
- **教训**: 涉及第三方工具的限制, 必查官方 docs/limitations/wikipedia 列表
- **预防**: 改任何跟上游工具能力相关的代码, 必查 `requirements-and-limitations.md` 类文档

跟 8/18 教训类似: 业务配置 (审批组 ID) 必须看实际审批日志; **工具能力必须查官方 docs**, 不要从代码脑补。

## 推 110 必做

5 步必做脚本 (commit `035850f` + commit ce6a364 步骤 13) 不需要新加步骤 — 这只是 precheck 逻辑修正, 推 110 时跟着代码部署走就行。

## 文件改动

- `sql/extensions/ddl_gh_ost/services/precheck.py` (2 处改动, 加 CUSTOM-MODIFIED 注释头)

## 关联

- 8/06 v0.3.0-alpha 设计: `docs/changelogs/2026-08-06_gh-ost-v030-alpha-skeleton.md`
- gh-ost 官方 limitations: `https://github.com/github/gh-ost/blob/master/doc/requirements-and-limitations.md`
- 8/24 教训: 工具能力查官方 docs, 不要从代码脑补
- 8/24 reload gunicorn SOP: `docs/runbooks/2026-08-24_gunicorn-reload-after-code-change.md` (配套 reload 演练)
