# D35 排查: column_diff.py backticks 解析 bug (110 prod 业务方看不到大表 alert 根因)

> **日期**: 2026-09-07 11:00-12:30
> **发现人**: 阿达叔叔 + Mavis
> **严重度**: 🔴 P0 — 业务方实战 3.8M 行大表 ALTER 走"立即执行"会锁表几分钟, 但**大表 alert 完全不显示**
> **影响范围**: 134 dev + 110 prod **通病** (W2 v0.3.x 时期 column_diff.py 设计 bug)

---

## 一、症状

业务方 9/7 在 110 prod 提工单 wf#4783 (yqf 改 `hly_accesscard.accesscard_vehiclepic.pic_url` varchar(300→1000))。

实际验证: `accesscard_vehiclepic` 是 3,834,233 行 / 1087.6 MB 的大表 (远超 10万行/100MB 阈值), 走"立即执行"**必锁表几分钟**。

**但业务方在 /submitsql/ 页面上完全看不到大表 alert 警告** → 业务方可能直接走"立即执行"路径 → 锁表事故风险。

## 二、根因 (D35 排查定位)

### 关键证据

```
=== 110 prod /gh_ost/column_diff/ API 实测 (用 mkq 业务方 session) ===

[1] 业务方 backticks SQL (实际工单 SQL):
    ALTER TABLE `hly_accesscard`.`accesscard_vehiclepic` MODIFY COLUMN `pic_url`...
    → ok: False, error: "所有 ALTER 涉及表都不存在或查不到列定义"
    → big_table_alert: None  ❌

[2] 去掉 backticks 134 dev 风格 SQL:
    ALTER TABLE hly_accesscard.accesscard_vehiclepic MODIFY COLUMN pic_url...
    → ok: True, big_table_alert: {rows: 3131058, size_mb: 1087.6}  ✅
```

### 根因: `_parse_alter_column_changes` 正则不能解析 backticks schema

`sql/extensions/ddl_gh_ost/services/column_diff.py` line 380-386 (110 prod) / line 400-406 (134 dev):

```python
m = re.match(
    r"^\s*ALTER\s+TABLE\s+"
    r"(?:(?P<schema>[^`\s.()]+)\.)?"   # ❌ schema 字符集排除反引号
    r"`?(?P<table>[^`\s(]+)`?",        # ✅ table 字符集允许反引号包裹
    sql_content.strip(),
    re.IGNORECASE,
)
```

**问题**:
- 业务方 SQL: `ALTER TABLE \`hly_accesscard\`.\`accesscard_vehiclepic\` ...`
- 正则期望: `(?:(?P<schema>[^`\s.()]+)\.)?` —— schema 段**排除反引号**
- 实际: schema 第一个字符是 `, 被字符集直接拒掉 → optional group 不匹配
- 然后 `\`?` 吃掉 schema 前的反引号, `[^`\s(]+` 贪婪匹配到 schema 字符串后**的下一个反引号前** → table 被错误识别为 `hly_accesscard`
- 后续 `.accesscard_vehiclepic` MODIFY 解析全部失败 → 返回 `[]`
- `_diff_single_table` 收到空 changes → 直接返回 `{"ok": False, "error": "ALTER TABLE 不包含 MODIFY/ADD/DROP COLUMN 字段变更"}`
- **大表 alert 检测逻辑完全被绕过** → 返回 `big_table_alert: None`

### 134 dev vs 110 prod 对比

| 文件 | md5 | 行数 | backticks 解析 | D27 增强 |
|------|-----|------|---------------|----------|
| 134 dev `/opt/archery/prod/sql/extensions/ddl_gh_ost/services/column_diff.py` | `ca319afaeb99273b253e332b387e5fa7` | **1291** | ❌ 同 bug | ✅ ALTER COLUMN SET/DROP DEFAULT |
| 110 prod `/dbdata/archery_v114_c9236a0/sql/extensions/ddl_gh_ost/services/column_diff.py` | `e6588f1d887d6154b6cc2dc88009e1ec` | **1168** | ❌ 同 bug | ❌ D27 缺推 |

**结论**: backticks 解析 bug 是 W2 v0.3.x 时期 column_diff.py 的**设计缺陷**, 134 dev + 110 prod **都有**。D27 v0.3.x 字段 diff 增强没推 110 prod (1168 vs 1291 差 123 行), 这是**第二个独立问题**。

## 三、134 dev 端实测确认

```python
# 134 dev 端 ssh run manage.py shell 实测
from sql.extensions.ddl_gh_ost.services.column_diff import _parse_alter_column_changes
SQL_BACKTICKS = """ALTER TABLE `hly_accesscard`.`accesscard_vehiclepic` MODIFY COLUMN `pic_url` varchar(1000) ..."""
_parse_alter_column_changes(SQL_BACKTICKS)
# → []   ❌ 同样失败
```

## 四、修法方案 (待用户拍板)

### 方案 A: 改 column_diff.py 正则, 让 schema 也支持 backticks (推荐, 一劳永逸)

修改 `sql/extensions/ddl_gh_ost/services/column_diff.py` line 380-386 + 134 dev 同样行:

```python
# 修前 (110 prod + 134 dev 都有):
m = re.match(
    r"^\s*ALTER\s+TABLE\s+"
    r"(?:(?P<schema>[^`\s.()]+)\.)?"   # ❌ 排除反引号
    r"`?(?P<table>[^`\s(]+)`?",
    ...
)

# 修后:
m = re.match(
    r"^\s*ALTER\s+TABLE\s+"
    r"(?:(?P<schema>`?[^`\s.()]+`?)\.)?"   # ✅ schema 允许反引号包裹
    r"`?(?P<table>[^`\s(]+)`?",
    ...
)
```

**优点**: 改一行正则, 134 dev + 110 prod 同步修, 业务方原样 backticks 写也能触发大表 alert
**缺点**: 要 134 dev 演练 + 推 110 prod (D35 push 范围本来就包括 column_diff.py)
**影响**: 现有 134 dev 业务方工单 100% 都用 backticks, 修后立即生效, 业务方改大表立刻能看到 alert

### 方案 B: 让业务方改写法, 不修代码 (临时, 不推荐)

让业务方在 /submitsql/ 里手动去掉 backticks:
```sql
ALTER TABLE hly_accesscard.accesscard_vehiclepic MODIFY COLUMN pic_url varchar(1000)...
```

**优点**: 0 代码改动
**缺点**: 业务方日常习惯 MySQL 客户端默认带 backticks, 强制改写法不现实, 容易再翻车

### 方案 C: 前端 sqlsubmit 自动去掉 backticks 后再调 column_diff (治标, 不推荐)

在 `sql/extensions/ddl_gh_ost/views/column_diff.py` 视图层 POST 处理时正则去掉所有反引号再调 column_diff_full。

**优点**: 业务方无感知
**缺点**: 改前端视图, 110 prod 视图层还没推 D28/D29 弹窗化, 改动面更大

## 五、推荐执行 (D35 9/8 启动前必决)

**A 方案**是最干净的修法, 而且 column_diff.py 本身就在 D35 push 范围 (Step 6 跨 app 6 文件之一), **建议合并到 D35 push 一起做**:

D35 push Step 6 改动列表 (更新版):
- `sql/templates/detail.html` (D18/D20/D25 v2)
- `sql/templates/sqlsubmit.html` (D28/D29 弹窗化)
- `sql/extensions/ddl_gh_ost/services/column_diff.py` (D27 ALTER COLUMN 增强 + **D35 backticks 修复**)
- `sql/extensions/ddl_sync/views/__init__.py` (D22/D23/D25/D33 分页+导出)
- `sql/extensions/ddl_sync/urls.py` (D33 history_export)
- `sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html` (D33 同步历史 tab)

修法工作流:
1. 134 dev 改 column_diff.py line 380-386 正则 (一处)
2. 134 dev 演练: 同一业务方 SQL 测 → 应返回 ok=True + big_table_alert 正常
3. commit + 推 110 prod (D35 实战 9 步)
4. 110 prod 验证: yqf 业务方账号实测 wf#4783 SQL → 应看到大表 alert

## 六、相关 context

- 110 prod 路径: `/dbdata/archery_v114_c9236a0/` (D31 实战新发现, 不是 `/dbdata/archery_v114/`)
- 110 prod root 密码: `lAqfb8uEmQYsnGNQwIHtGPwukjCz6J` (D31 实战时是 QNQw, 9/7 prep 时已改 GNQw, 跟 134 dev 一样)
- 110 prod 业务方 mkq 密码: `mbdMCZmqa8vYxyK6JDuK4LZjy2UqceFS`
- 业务方工单 wf#4783 SQL 完整: `ALTER TABLE \`hly_accesscard\`.\`accesscard_vehiclepic\` MODIFY COLUMN \`pic_url\` varchar(1000) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL COMMENT '';`
- `_parse_alter_column_changes` 行号: 110 prod 368, 134 dev 388
- 验证脚本: `scripts/_archive/_d35_110prod_column_diff_api.py` + `_d35_134dev_parse_func.py`
