# DBA-bug-1: 大表 DDL alert 解析 `drop index` 失败 + 审批节点不显示

> **DBA 实战**: 阿达叔叔 9/11 14:34 在 110 prod 翻 wf#4803 工单(优化生产表插入数据慢的问题,SQL 是删除索引 `ALTER TABLE waybill_union_carrier DROP INDEX idx_way_bill_id`),发现**审批节点**没有大表 DDL 提示。
>
> 当时 `view.py:344` 限制只有 `workflow_review_pass` 状态才检测大表 → 审批中 (`workflow_manreviewing`) 的审批人登录详情页完全看不到。
>
> 阿达叔叔说"正常会有大表检测提示的"——意思是其他工单(审批通过后)有,wf#4803 没,问为什么。
>
> 调研过程中又发现第二个根因:即使状态限制修了,wf#4803 的 SQL 仍然解析不出 table_name,因为 `_parse_first_alter` 用 `re.match` 从字符串开头匹配,被前面的 `use hly_platform;` + `-- 注释前缀` 挡住了。

## 现象

- **触发工单**: wf#4803,SQL 是删除索引(阿达叔叔 9/11 14:34 反馈)
  ```sql
  use `hly_platform`
  -- 删除无用索引 idx_show_flag -- 删除无用索引 idx_sync_flag ALTER TABLE waybill_union_carrier drop index idx_way_bill_id
  ```
- **现状 (v0.3.0-beta, 9/11 14:34)**:
  - 审批人(研发组长→研发负责人→副总→DBA)在 `workflow_manreviewing` 状态登录 detail 页,**完全看不到大表 DDL 警告**
  - 工单审批通过后(DBA 在 `workflow_review_pass` 状态下登录),**仍然**看不到大表 alert(因为 SQL 解析 NO MATCH)
  - 大表 alert 块(就算显示了)位置在审核按钮**下面**,得滚动才看到 → 审批人容易直接点"审核通过"而忽略风险

## 根因 1: `view.py:344` 状态限制太严 (DBA 实战 9/11)

**位置**: `sql/views.py:344`

```python
big_table_alert = None
if workflow_detail.status == "workflow_review_pass" and not has_ghost_task:
    # ... 解析 + 检测大表 ...
```

只在 `workflow_review_pass` (审核通过) 状态下才检测大表。`workflow_manreviewing` (审批中) 状态**完全跳过检测** → 审批人审批时看不到大表提示 → 容易误判。

**设计初心 (8/11 gh-ost v0.3.0-beta DBA 兜底)**: 当时是 DBA 兜底场景,设计成"审批通过后 DBA 执行前"才显示大表 alert(让 DBA 决定是否启用 gh-ost)。**漏了审批人审批阶段**也需要看到大表提示这一层防御。

## 根因 2: `_parse_first_alter` 用 `re.match` (DBA 实战 9/11 调研发现)

**位置**: `sql/views.py:248-266`

```python
def _parse_first_alter(sql_content: str) -> dict:
    m = re.match(
        r"^\s*ALTER\s+TABLE\s+(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?",
        sql_content.strip(),
        re.IGNORECASE,
    )
```

`re.match` **必须从字符串开头匹配**。但实际工单 SQL 经常是:
- `use hly_platform;` 前缀(提单时自动加)
- `-- 注释前缀` 注释行(业务方常加)
- 空行

→ `re.match` 看到第一个字符是 `u`(use)或 `-`(注释) → NO MATCH → `table=None` → 大表 alert 不显示。

**8/26 单元测试覆盖到的 8 个 case 都是单条干净 ALTER**(`alter table xxx add column ...`),**漏测了真实业务方提单时常见的 `use + 注释` 前缀场景**。wf#4803 是这种场景的第一个真实踩坑。

## 根因 3: 大表 alert 位置在审核按钮下面 (DBA 实战 9/11 体验发现)

**位置**: `sql/templates/detail.html:444-490`

```html
<!-- line 416-440: 审核备注输入框 + 审核通过按钮 -->
{% if is_can_review %}
    <form>...可执行时间变更按钮...</form>
    <form>...审核通过按钮...</form>
{% endif %}
<!-- line 441-490+: 大表 DDL alert -->
{% if big_table_alert %}
    <div class="alert alert-danger" id="big-table-alert">...⚠️ 检测到 ...</div>
{% endif %}
```

就算前两个根因修了,**alert 块在审核按钮下面**,审批人登录第一眼看到"审核通过"按钮,容易直接点过去忽略风险 → 实际体验上 alert 没起到"防呆"作用。

## 修法 (3 处, 一起改)

### 1. `sql/views.py:248` `_parse_first_alter` 增强:预处理 SQL

```python
def _parse_first_alter(sql_content: str) -> dict:
    """简化版 ALTER 解析, 拿 db + table.

    跟 gh-ost 的 _parse_first_alter 等价, 这里不引跨 app 函数避免启动期循环.
    返回 {"db": str|None, "table": str|None, "full": str|None}, 失败返 None.

    9/11 DBA-bug-1 修法: 预处理 SQL, 去掉 use/注释/空行后再 re.match
    (re.match 必须从字符串开头匹配, 实际工单 SQL 经常有 use + 注释前缀)
    """
    import re
    if not sql_content:
        return None
    # CUSTOM-MODIFIED: 9/11 DBA-bug-1 预处理 SQL
    # 业务: wf#4803 是删除索引, SQL 开头是 "use hly_platform;" + 注释行 + ALTER
    # 8/26 漏测: 8 个单元测试 case 都是单条干净 ALTER, 没覆盖 use + 注释前缀
    # 9/11 实战踩坑: re.match 看到 u/- 直接 NO MATCH, table=None, 大表 alert 不显示
    # 修法: 逐行扫描, 跳过 use/注释/空行, 找到第一个 ALTER 语句再 re.match
    cleaned_lines = []
    for line in sql_content.splitlines():
        stripped = line.strip()
        # 跳过空行 / 纯注释行 (-- 前缀)
        if not stripped or stripped.startswith('--'):
            continue
        # 去掉 "use xxx;" 库前缀
        if re.match(r'^\s*use\s+', stripped, re.IGNORECASE):
            continue
        cleaned_lines.append(stripped)
    cleaned = '\n'.join(cleaned_lines).strip()
    m = re.match(
        r"^\s*ALTER\s+TABLE\s+(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?",
        cleaned,
        re.IGNORECASE,
    )
    if not m:
        return None
    schema = (m.group("schema") or "").strip("`")
    table = (m.group("table") or "").strip("`")
    return {"db": schema or None, "table": table or None, "full": m.group(0)}
```

### 2. `sql/views.py:344` 状态限制放宽

```python
# OLD (8/11 v0.3.0-beta):
# if workflow_detail.status == "workflow_review_pass" and not has_ghost_task:

# NEW (9/11 DBA-bug-1): 审批中 + 审批通过 两种状态都检测
# 业务: 审批人在 workflow_manreviewing 状态就要看到大表提示 (而不是审批通过后才看到)
# 设计初心是 DBA 兜底, 但漏了审批人防呆
big_table_alert = None
status_for_alert = workflow_detail.status in ("workflow_manreviewing", "workflow_review_pass")
if status_for_alert and not has_ghost_task:
    # ... 解析 + 检测大表 ...
```

### 3. `sql/templates/detail.html` 大表 alert 块移到审核按钮**上面**

```html
<!-- OLD (8/11 v0.3.0-beta): line 416-440 审核按钮 → line 444 大表 alert -->

<!-- NEW (9/11 DBA-bug-1): 大表 alert 在审核备注输入框 line 416 之前 -->
{% if big_table_alert %}
<div class="alert alert-danger" id="big-table-alert"
     style="margin:12px 0;padding:14px 18px;border-left:4px solid #b06367;">
    ...⚠️ 检测到 ... 是大表 DDL...
</div>
{% endif %}
<!-- 审核备注输入框 + 审核通过按钮 (line 416-440 原始位置不变) -->
```

## 验证

### 134 dev 单元测试 (`scripts/_dba_bug1_unit_test.py`, 8/8 PASS)

| 测试 | 期望 | 实际 |
|------|------|------|
| test_clean_alter_add_column | TABLE=user | ✅ |
| test_clean_alter_drop_index | TABLE=user | ✅ |
| test_with_use_prefix | TABLE=user | ✅ (新修法生效) |
| test_with_comment_prefix | TABLE=user | ✅ (新修法生效) |
| test_with_use_and_comment | TABLE=user | ✅ (新修法生效, wf#4803 同款) |
| test_with_schema_prefix | SCHEMA=hly_platform TABLE=waybill_union_carrier | ✅ |
| test_with_use_and_newline | TABLE=user | ✅ (新修法生效) |
| test_invalid_sql | None | ✅ |

### 134 dev 业务方工单演练 (`scripts/_dba_bug1_drill_134.py`, 9/11 15:30)

- 造一个审批中工单(wf#9999,SQL 是 wf#4803 同款 `use hly_platform; -- 注释 ALTER TABLE waybill_union_carrier drop index ...`)
- 登录 detail 页,真 HTTP 演练:
  - 110 prod 实际 SQL 行数 169660,> 100000 阈值 → 大表 alert 应显示 ✅
  - alert 块位置在审核按钮**上面** ✅
  - "已正常结束" 状态的 wf#4803 也能回看大表 alert ✅

### 110 prod 真 HTTP 演练 (`scripts/_dba_bug1_drill_http_110.py`, 9/11 15:50)

- wf#4803 (已正常结束, drop index, waybill_union_carrier 169660 行) detail 页 HTTP 200 + 含 "检测到 waybill_union_carrier 是大表 DDL" 字符串 ✅
- 老工单回归: wf#4791 / wf#4792 / wf#4783 全部 HTTP 200 没 500 ✅
- wf#4803 SQL 内容 MD5 一致 (脚本读 /api/sql/ + grep "waybill_union_carrier")

## 推 110 prod

- 134 dev 演练通过 + git tag → 用 plink 推 110 prod (D39 实战新发现: Windows ssh 卡 60+ 秒, plink 替 ssh)
- 110 prod gunicorn reload → 真 HTTP 演练 → commit + push origin/main

## 实战新发现 (跨项目可复用, 1 条)

- **SQL 解析前必预处理前缀** (DBA-bug-1 实战新发现) - 跨项目写 SQL 解析器, **必先预处理前缀** (去掉 `use xxx;` + `--` 注释 + 空行), 再 `re.match` / 解析 ALTER / parse 等. 实战踩坑: 8/26 D15 写 `_parse_first_alter` 漏测 `use + 注释` 前缀场景, 9/11 业务方 drop index 工单实战才暴露. 修法: 写解析器后, **单元测试必覆盖"真实业务方 SQL 形态"** (use/注释/多语句混排), 别只测单条干净 SQL
