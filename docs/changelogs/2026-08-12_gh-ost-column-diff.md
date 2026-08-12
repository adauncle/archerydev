# 2026-08-12 · v0.3.x 字段 diff 检测（创建工单时智能比对）

> **作者**: mavis · **关联**: 设计稿 `docs/designs/2026-08-12_gh-ost-column-diff-mockup.html` (v2)
> **触发场景**: 用户真实生产事故 — 字段类型变更没带字符集, 跨表 JOIN 索引失效, 性能暴跌 + 用户客诉

## 一句话

SQL 检测结果页（同一个框）末尾自动展开"字段变更检测"段，识别 ALTER 的列定义变化（类型/字符集/排序规则/默认值/可空性/自增），按 11 条风险规则给高/中/低评级 + 修复建议 SQL。详情页大表 alert 旁也带"字段 diff"按钮供 DBA 兜底查看。

## 触发场景（生产事故复盘）

```
改前: status VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci
改后: ALTER TABLE x MODIFY COLUMN status VARCHAR(50)   ← 省略 CHARSET/COLLATE
结果: VARCHAR(50) CHARACTER SET <表默认> COLLATE <表默认>   ← 跟原列不一致!
后果: 跨表 JOIN 索引失效 → 性能暴跌 → 用户客诉
```

根因：MySQL `MODIFY COLUMN` 不指定 `CHARACTER SET` / `COLLATE` 时，**用表默认**（不一定跟原列一样）。

## 检测维度（8 维字段属性）

| 维度 | 字段 | 检测什么 |
|---|---|---|
| **类型** | `data_type` + `character_maximum_length` | 长度 / 类型不兼容 |
| **字符集** | `character_set_name` | 跨表 JOIN 索引 |
| **排序规则** | `collation_name` | 排序/大小写敏感 |
| **默认值** | `column_default` | 类型隐式转换 |
| **可空性** | `is_nullable` | 已有 NULL 数据 |
| **备注** | `column_comment` | 文档性, 低风险 |
| **自增** | `extra` | AUTO_INCREMENT 序列 |
| **键** | `column_key` | PRI / UNI |

## 11 条风险规则

| # | 变更 | 风险 | 提示语 |
|---|---|---|---|
| 1 | Charset 变了 | 🟥 高 | 跨表 JOIN 索引可能失效 |
| 2 | Collation 变了 | 🟥 高 | 排序/大小写敏感行为变化 |
| 3 | NULL→NOT NULL 无 DEFAULT | 🟥 高 | 已有 NULL 数据 ALTER 会失败 |
| 4 | 自增被改/删 | 🟥 高 | 序列错乱, 业务数据可能重复 |
| 5 | 改 PK | 🟥 高 | 破坏表结构 |
| 6 | 不兼容类型（VARCHAR→TEXT） | 🟥 高 | 数据格式/索引丢失 |
| 7 | 缩短类型 (200→50) | 🟧 中 | 已有数据可能截断 |
| 8 | NULL→NOT NULL 有 DEFAULT | 🟧 中 | 已有数据被默认值填充 |
| 9 | DEFAULT 数字/字符串互换 | 🟨 低 | 隐式类型转换 |
| 10 | 改 COMMENT | 🟩 无 | 无影响 |
| 11 | 类型变长 (50→200) | 🟩 无 | 兼容 |

## 端点设计

`POST /gh_ost/column_diff/`  
入参：`{instance_id, db_name, sql_content}`  
返回：
```json
{
  "ok": true,
  "table_name": "accesscard_black_detail",
  "columns": [{
    "name": "status",
    "operation": "MODIFY",
    "current": {"type": "varchar(100)", "charset": "utf8mb4", "collation": "utf8mb4_general_ci", "nullable": "YES"},
    "new": {"type": "varchar(50)", "charset": "(table default)", "collation": "(table default)", "nullable": "YES"},
    "diffs": [
      {"field": "type", "old": "varchar(100)", "new": "varchar(50)", "risk": "mid", "reason": "类型缩短 100→50, 已有数据可能截断"},
      {"field": "charset", "old": "utf8mb4", "new": "(table default)", "risk": "high", "reason": "字符集变化, 跨表 JOIN 索引可能失效"}
    ]
  }],
  "high_risk_count": 1,
  "mid_risk_count": 1,
  "summary": "检测到 1 个高风险变更, 强烈建议在 ALTER 中显式指定原 CHARSET"
}
```

## 模板联动（同一个框）

**SQL 检测结果页**（`sqlsubmit.html`）：
- 点 "SQL 检测" 按钮 → 现有 inception 引擎做语法检查
- 末尾自动展开 "字段变更检测" 折叠段
- JS 检测 SQL 是 `ALTER TABLE ... MODIFY/ADD/DROP` 时自动 fetch
- 非 ALTER SQL 不触发
- 失败 fallback：column_diff 报错时静默不显示, 不影响语法检查

**详情页大表 alert**（`detail.html`）：
- 审批通过后大表 alert 文案升级："同时检测到 X 个高风险字段变更"
- "字段 diff" 按钮跟现有三按钮（启用 gh-ost / 立即执行 / 终止工单）并列

## 关键实现要点

### 1. helper 函数（3 个）

```python
def _fetch_current_columns(instance, db_name, table_name) -> dict:
    """查 information_schema.columns 拿当前列定义"""

def _parse_alter_column_changes(sql_content) -> list:
    """解析 ALTER TABLE MODIFY/ADD/DROP COLUMN 子句"""

def _assess_column_risk(field, old_val, new_val) -> tuple:
    """11 条风险规则, 返回 (risk_level, reason)"""
```

### 2. 端点

```python
@login_required
@require_POST
def column_diff(request):
    """字段 diff 检测端点. 入参: {instance_id, db_name, sql_content}"""
```

### 3. JS 联动（sqlsubmit.html）

- 在 SQL 检测成功 callback 里加 column_diff fetch
- ALTER 关键字 + MODIFY/ADD/DROP 触发
- 结果渲染到 `id="column-diff-result"` 折叠区
- 默认折叠, 高风险自动展开

### 4. 详情页大表 alert 联动

- 复用 `gh_ost.task_list.html` 的 diff 渲染（提取成 partial）
- 大表 alert 旁加 `<button data-act="column-diff">字段 diff</button>`
- 点击 fetch 同样端点, 显示 modal 或 inline 展开

## 134 dev 演练

用真表 `archery_dev.accesscard_black_detail` 跑 5 Case 端到端：

| Case | ALTER | 预期结果 |
|---|---|---|
| 1 | `MODIFY status VARCHAR(50)` | 🟥 字符集丢失 + 🟥 排序规则丢失 + 🟧 类型缩短 |
| 2 | `MODIFY operator_id BIGINT NOT NULL` | 🟥 NULL→NOT NULL 无 DEFAULT |
| 3 | `MODIFY id BIGINT` (删自增) | 🟥 自增被删 |
| 4 | `MODIFY name VARCHAR(50) NOT NULL DEFAULT ''` | 🟧 类型缩短 + 🟩 NULL→NOT NULL 有 DEFAULT |
| 5 | `MODIFY remark VARCHAR(500) COMMENT 'x'` | 🟩 全部兼容 |

## 变更文件清单

| 文件 | 变更 |
|---|---|
| `sql/extensions/ddl_gh_ost/views.py` | 新增 `column_diff` 视图 + 3 helper 函数 |
| `sql/extensions/ddl_gh_ost/urls.py` | 加 `path("column_diff/", ...)` |
| `sql/extensions/ddl_gh_ost/services/column_diff.py` | 新建 (11 条风险规则) |
| `sql/templates/sqlsubmit.html` | 检测结果末尾加"字段变更检测"折叠段 + JS 联动 |
| `sql/templates/detail.html` | 大表 alert 旁加"字段 diff"按钮 + JS 渲染 |
| `docs/changelogs/2026-08-12_gh-ost-column-diff.md` | 本 changelog |
| `scripts/drill_column_diff.py` | 5 Case 端到端演练 |

## 110 prod 推 v0.3.x 时同步

- 无 schema 变更
- 无 env var 新增
- 新端点 column_diff + 模板改动 + service 文件
- 134 dev 演练通过 + 浏览器验收后推

## 关联

- `docs/designs/2026-08-12_gh-ost-column-diff-mockup.html` (产品 mockup v2)
- `docs/changelogs/2026-08-11_gh-ost-dba-fallback.md` (大表 DDL 防呆前置)
- `docs/changelogs/2026-08-12_gh-ost-task-list-page.md` (产品级入口)
