# DBA-bug-3: 字段 diff 端点 `ADD/DROP INDEX` 大表 alert 丢失 (DBA 实战工单 consume_flow 5M+ 行)

> **DBA 实战**: 阿达叔叔 9/11 18:50 反馈 `/submitsql/` 提交 `consume_flow` 大表工单**没有弹窗**(DBA-bug-2 推了 views.py + sqlsubmit.html banner 后, 业务方多次确认**仍然没有任何弹窗**)。
>
> 9/11 19:00 调研根因: 不是 views.py 的问题 (views.py regex 修后能解析反引号 schema, 详情页 detail.html 大表 alert 验证 PASS), **是 column_diff.py 端点本身的逻辑 bug**。
>
> `_diff_single_table` 在 `not changes` (SQL 不含 MODIFY/ADD/DROP COLUMN 关键字) 时**直接 return `ok=False`, 完全跳过表大小检查**, 所以 `ADD INDEX` / `DROP INDEX` / `RENAME` 等非字段变更 DDL 永远不会触发大表 alert。
>
> 而且前端 sqlsubmit.html 的 `if (!data.ok) return;` 把这种 `ok=False + big_table_alert` 场景也吞了, **业务方完全错过 5M+ 行大表 DDL 警告**。

## 现象

- **触发工单**: 业务方实战 `hly_billing.consume_flow` 表 (5,238,005 行 / 3,482.4 MB) 工单, SQL 是 `ALTER TABLE ... ADD INDEX` / `DROP INDEX`
- **现状 (DBA-bug-2 推后, 9/11 18:50)**:
  - SQL 上线页 (`/submitsql/`) 提交 → 点 "SQL 检测" → 调 `/gh_ost/column_diff/` 端点
  - 端点 `_diff_single_table` 解析 `ADD INDEX` 时 `changes=[]` (没 MODIFY/ADD/DROP COLUMN 关键字), **直接 return `ok=False`, 没查表大小**
  - 端点返 `{"ok": False, "error": "ALTER TABLE 不包含 MODIFY/ADD/DROP COLUMN 字段变更", "big_table_alert": None}`
  - 前端 `if (!data.ok) return;` 静默 return
  - **业务方完全错过 5M+ 行大表 DDL 警告**
- **业务方多次确认**没有弹窗 (banner + modal 都没显示)

## 根因 2 处 (跟 DBA-bug-1/2 同样类型, 后端链路)

### 根因 1: column_diff.py `_diff_single_table` 在 `not changes` 时跳过表大小检查

**位置**: `sql/extensions/ddl_gh_ost/services/column_diff.py:744-750`

```python
changes = _parse_alter_column_changes(alter_sql)
if not changes:
    return {
        "ok": False,
        "error": f"ALTER TABLE 不包含 MODIFY/ADD/DROP COLUMN 字段变更",
        "hint": "只支持 ALTER TABLE ... MODIFY/ADD/DROP COLUMN",
    }
```

`ADD INDEX` / `DROP INDEX` / `RENAME INDEX` 等 DDL 没 `MODIFY/ADD/DROP COLUMN` 关键字, `_parse_alter_column_changes` 返 `changes=[]`, **直接 return, 完全跳过表大小检查**。

但这些 DDL **仍然是大表 DDL**(影响行数大, 走原路径"立即执行"会锁表), **应该触发大表 alert**。

### 根因 2: column_diff.py `column_diff_full` 在单表 ok=False 时覆盖 big_table_alert

**位置**: `sql/extensions/ddl_gh_ost/services/column_diff.py:1245-1259` (DBA-bug-3 修前)

```python
if not single.get("ok"):
    tables_diff.append({
        "ok": False,
        ...
        "big_table_alert": None,  # 关键: 单表失败时直接置 None
    })
    continue
```

即使我修了根因 1 让 `_diff_single_table` 在 not changes 时返 big_table_alert, 顶层 `column_diff_full` 在 not single.ok 时**也直接覆盖为 None**!

而且根因 1 + 根因 2 是连环坑, 必须一起修。

## 修法 3 处

### 1. `_diff_single_table` 提前 table_name 解析 + not changes 时也查大表 alert

```python
# 0. 拿表名 (提前到 changes 解析之前, 让 not changes 也能查大表 alert)
# CUSTOM-MODIFIED: 9/11 DBA-bug-3 提前表名解析 @ 2026-09-11 @ mavis
table_name = force_table_name
if not table_name:
    m = re.match(...)  # regex 跟 column_diff.py:402-405 一致
    if not m:
        return {"ok": False, "error": "解析不到表名"}
    table_name = m.group("table").strip("`")

# 0.5 大表 alert 检查 (DBA-bug-3: 提前到 changes 解析之前, 让 not changes 时也能触发)
size_info = _fetch_table_size(instance, db_name, table_name)
big_table_alert = _build_big_table_alert(size_info)

changes = _parse_alter_column_changes(alter_sql)
if not changes:
    # CUSTOM-MODIFIED: 9/11 DBA-bug-3 not changes 时也保留大表 alert
    return {
        "ok": False,
        "error": f"ALTER TABLE 不包含 MODIFY/ADD/DROP COLUMN 字段变更",
        "hint": "只支持 ALTER TABLE ... MODIFY/ADD/DROP COLUMN",
        "table_name": table_name,
        "big_table_alert": big_table_alert,  # 关键: 大表 alert 即便 not changes 也带上
    }

# ... 表不存在也带上 big_table_alert (虽然 size_info 可能为 None)
```

### 2. `column_diff_full` 保留单表 big_table_alert

```python
if not single.get("ok"):
    # CUSTOM-MODIFIED: 9/11 DBA-bug-3 保留 single 里的 big_table_alert
    single_big_table_alert = single.get("big_table_alert")
    tables_diff.append({
        "ok": False,
        "table_name": single.get("table_name", "?"),
        "table_exists": single.get("table_exists", True),
        "error": single.get("error", "unknown"),
        "columns": [],
        "high_risk_count": 0,
        "mid_risk_count": 0,
        "low_risk_count": 0,
        "summary": single.get("error", "解析失败"),
        "big_table_alert": single_big_table_alert,  # 关键: 保留单表大表 alert
    })
    if single_big_table_alert and not first_big_table_alert:
        first_big_table_alert = single_big_table_alert  # 关键: 顶层汇总也带上
    continue

# ... not tables_diff / not any_table_exists 也带上 first_big_table_alert
```

### 3. sqlsubmit.html `if (!data.ok) return;` 放宽

```javascript
// CUSTOM-MODIFIED: 9/11 DBA-bug-3 ok=False 但有大表 alert 也显示 @ 2026-09-11 @ mavis
$("#sqlsubmit-big-table-alert-banner").remove();
if (!data.ok && !data.big_table_alert) {
    // 真正静默: 表不存在 / SQL 不含 MODIFY 等, 也没大表
    $("#column-diff-modal-body").empty();
    $("#column-diff-inline").hide();
    return;
}
if (!data.ok && data.big_table_alert) {
    // ok=False 但有大表 alert (ADD INDEX/DROP INDEX/RENAME 等非字段变更)
    $("#column-diff-modal-body").html(renderBigTableAlertOnly(data.big_table_alert));
    $('#columnDiffModal').modal('show');
    renderBigTableBanner(data.big_table_alert);
    return;
}
renderColumnDiff(data);
$('#columnDiffModal').modal('show');
if (data.big_table_alert) {
    renderBigTableBanner(data.big_table_alert);
}
```

`renderBigTableAlertOnly` / `renderBigTableBanner` 两个 helper 函数, 跟 detail.html 大表 alert 风格一致。

## 验证

### 134 dev 端点演练 (`scripts/_dba_bug3_drill_134.sh`, 9/11 19:14, 4/4 PASS)

| 测试 | ok | big_table_alert | 备注 |
|------|----|----|------|
| ADD INDEX 大表 | True | {rows: 118932, size_mb: 35.7} | 字段 diff 误识别 INDEX 字段 (老 bug) 但不影响 |
| **DROP INDEX 大表 (主验证)** | **False** | **{rows: 118932, size_mb: 35.7}** | **关键: ok=False 但 big_table_alert 保留** |
| MODIFY COLUMN 大表 (回归) | True | + high_risk_count=1 | 字段 diff 完整 |
| 小表 ADD INDEX | True | None | 不触发大表 (符合预期) |

### 110 prod 端点演练 (`scripts/_dba_bug2_drill_110.py` 加测, 9/11 19:20)

| 工单 | 端点返 |
|------|--------|
| 图1 consume_flow ADD INDEX | `ok=True, big_table_alert={rows: 5238005, size_mb: 3482.4}` ✅ |
| 图2 consume_flow modify column | `ok=True, big_table_alert={rows: 5238005, size_mb: 3482.4}, high_risk=1, mid_risk=1` ✅ |
| **consume_flow DROP INDEX (DBA-bug-3 主验证)** | **`ok=False, big_table_alert={rows: 5238005, size_mb: 3482.4}`** ✅ |
| 回归 waybill drop index | `ok=False, big_table_alert=None` (hly_platform 不存在, size_info=None, 符合预期) |

### 110 prod 老工单回归 (9/11 19:20)

- wf#4803: HTTP 200, 大表 alert 完整渲染 ✅
- wf#4791 / wf#4792 / wf#4783: HTTP 200 0 个 500 ✅

## 推 110 prod

- 134 dev 演练通过 → 推 column_diff.py + sqlsubmit.html → md5 完全一致
- kill -TERM 老 workers (18:46 启动的 123504-123511) → master 8694 自动拉新 workers 19:19 启动
- 真 HTTP 演练 → 老工单回归 → 0 个 500

## 实战新发现 (跨项目可复用, 1 条)

- **端点 `ok=False` 分支也要保留次要数据** (DBA-bug-3 实战新发现) - 跨项目写 API 端点返 `{"ok": bool, "data/alert/...}` 格式, 失败分支 (`ok=False`) **不要一刀切置 None**, 必保留所有**已经查到的次要数据** (如 `big_table_alert` / `error` / `hint`). 实战踩坑: 9/11 DBA-bug-3 column_diff.py 端点 `_diff_single_table` 在 `not changes` 时直接 return `ok=False` 跳过表大小检查, 顶层 `column_diff_full` 在 not single.ok 时把 `big_table_alert` 置 None, **业务方实战 consume_flow 5M+ 行 ADD INDEX 永远不会触发大表 alert**. 修法: 端点 ok=False 失败分支**保留已查到的次要数据** (例: not changes 时也查表大小返 big_table_alert, 顶层 not single.ok 时保留 single.big_table_alert), **前端 `if (!data.ok) return` 也要放宽** (`if (!data.ok && !data.secondary) return`). 跨项目推新端点必加单元测试: **成功路径 + 失败但有次要数据路径 + 失败无数据路径**, 别只测成功
