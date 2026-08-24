# 2026-08-24 字段 diff 详情页"无展示" bug 修复

## 摘要

修复详情页"DBA 审核节点"大表 alert 中"字段 diff" 按钮点了不展示 diff 结果的 bug。

## 根因

`sql/extensions/ddl_gh_ost/services/column_diff.py:540-547` `column_diff_full` 函数, `_parse_alter_column_changes` 用 regex 匹配 `^\s*ALTER\s+TABLE\s+...`, **要求 SQL 以 ALTER TABLE 开头**。

但详情页 `sql/templates/detail.html:823` 直接把 `workflow_detail.sqlworkflowcontent.sql_content` 传给后端, 这是**整段 SQL**, 包括 Archery 提交页常见的 `use \`xxx\`` 前缀:

```sql
use `archery_dev`
ALTER TABLE accesscard_black_detail drop COLUMN test3
```

regex 匹配失败, `_parse_alter_column_changes` 返回 [], `column_diff_full` 返回 `{"ok": False, "error": "SQL 不是 ALTER TABLE ..."}`。

前端 `renderColumnDiffModal` (detail.html:850-855) 实际**会弹 modal**, 但只显示 alert 警告 "SQL 不是 ALTER TABLE..."。
- **业务 RD / DBA 看到 modal 弹了一个错误警告, 没看到 diff 结果, 以为"没展示"**
- 实际是 8/12 写字段 diff 时漏考虑 `use` 前缀, 一直没踩到

## 复现 (8/24 用户报)

工单 #89:
```sql
use `archery_dev`
ALTER TABLE accesscard_black_detail drop COLUMN test3
```

详情页底部"检测到 accesscard_black_detail 是大表 DDL" alert 中, 点"字段 diff" 按钮, modal 弹了但只显示 "SQL 不是 ALTER TABLE 或不包含 MODIFY/ADD/DROP COLUMN" 错误。

## 修法

`sql/extensions/ddl_gh_ost/services/column_diff.py:540-580`:

```python
## CUSTOM-MODIFIED: 8/24 兼容 use `xxx` 前缀
## 1. 先用 sqlparse.split 拆 SQL, 在每段内找 ALTER TABLE 起始位置
alter_sql = None
statements = [s for s in sqlparse.split(sql_content) if s.strip()]
for stmt in statements:
    m = re.search(r"\bALTER\s+TABLE\b", stmt, re.IGNORECASE)
    if m:
        alter_sql = stmt[m.start():].strip().rstrip(";").strip()
        break
## 2. 用 alter_sql 替代 sql_content 调 _parse_alter_column_changes + 拿表名
changes = _parse_alter_column_changes(alter_sql)
# 拿表名也用 alter_sql, 跟上面同步
m = re.match(r"^\s*ALTER\s+TABLE\s+...", alter_sql.strip(), re.IGNORECASE)
```

**关键修复点**:
1. sqlparse 可能把 `use \`x\`\nALTER TABLE` 拆成 1 段 (没有分号结尾), 在段内再查 ALTER 起始位置
2. 加 `import sqlparse` (8/12 写时漏 import, 我用 line 280 的 regex 没用 sqlparse)
3. 拿表名也用 `alter_sql` 替代 `sql_content` (line 576), 保持一致

## 演练 (134 dev, 8/24 15:43)

2 Case 端到端跑通:

| Test | SQL 格式 | 修前 | 修后 | 期望 |
|---|---|---|---|---|
| 1 | 整段 (含 use 前缀) | ✗ FAIL "SQL 不是 ALTER TABLE" | ✓ PASS, 1 列 (test3 DROP) | ✓ |
| 2 | 单条 ALTER | ✓ PASS | ✓ PASS, 1 列 (test3 DROP) | ✓ |

**演练脚本**: `scripts/_archive/_drill_column_diff_8_24_20260824.py`

**reload 流程** (按 8/24 SOP):
1. scp 修后 column_diff.py 到 134 dev
2. kill master 12144 → systemd 拉起新 master (15:43 启动)
3. 跑 2 Case, Test 1 通过

## 推 110 必做

跟 commit `eaf9853` (cancel 流程) + `9d66064` (precheck 过度限制) + `a41c4d0` (ConfigurableAuditor) 一起推 110。业务代码改动, 5 步必做步骤 13 覆盖。

## 文件改动

- `sql/extensions/ddl_gh_ost/services/column_diff.py` (2 处 + import sqlparse + CUSTOM-MODIFIED 注释头)

## 关联

- 8/12 字段 diff 设计: `docs/designs/2026-08-12_gh-ost-column-diff-mockup.html`
- 8/12 字段 diff changelog: `docs/changelogs/2026-08-12_gh-ost-column-diff.md`
- 8/24 reload SOP: `docs/runbooks/2026-08-24_gunicorn-reload-after-code-change.md`
- troubleshooting.md: 加这条 bug 根因
