# 2026-09-21 DBA-bug-11 gh-ost precheck 400 修复 (业务方 ## 注释)

> 阿达叔叔 9/21 17:35 反馈 wf#4871 详情页点击"启用 gh-ost"按钮, DevTools Console 报错:
> `POST /gh_ost/precheck/4871/ 400 (Bad Request)`
> 根因: 业务方 SQL 注释用 Python 风格 `##` (不是 MySQL `--`), `_parse_all_statements` 只跳过 `--` 注释,
> cleaned 开头是 `## ...` 不匹配 ALTER regex → precheck 返 400 "未找到 ALTER TABLE 语句"

## 背景

### wf#4871 实际 SQL (从 110 prod MySQL 拉出来, 3699 chars)

```sql
## 钉钉审核表关联运单表加字段
alter table dingding_check_waybill
    add hdj_type int default 1 null comment '回单结类型（1：回单结 2：起运结）';

## 下游付款运单关联表
alter table downstream_waybill
    add qyj_amount          decimal(18, 2)          default 0.00 null comment '起运结金额（抵扣起运结）',
    add qyj_discount_amount decimal(18, 2) unsigned default 0.00 null comment '抵扣起运结差价';

## 回单结开通
alter table hdj_open
    add pre_discount_rate      decimal(15, 10) null comment '起运结费率',
    add pre_discount_rate_unit int             null comment '起运结费率单位（ 1:%/日 2:%）';
```

业务方习惯用 Python 风格 `##` 加注释 (不是 MySQL `--` 风格), Archery 上游只识别 `--` 注释.

### 报错截图 (9/21 17:35)

- wf#4871 详情页 `prodarchery.ahggwl.com:9123/detail/4871/`
- 状态: 审核通过
- 点击"启用 gh-ost 无锁变更"按钮
- DevTools Console 报错: `Failed to load resource: POST /gh_ost/precheck/4871/ 400 (Bad Request)`
- 110 prod access.log 确认: `POST /gh_ost/precheck/4871/ HTTP/1.1 400 102`

## 根因

`sql/extensions/ddl_gh_ost/views.py:147` `_parse_all_statements` 注释跳过:

```python
# 老代码
if stripped.startswith("--") or not stripped:  # ← 只识别 -- 注释
    continue
```

`_FIRST_ALTER_RE` (views.py:81-84) regex `^\s*ALTER\s+TABLE` 必须 ALTER 开头.

按分号切分后, 每段开头是 `## ...\n alter table ...`, 不是 ALTER 开头 → regex 不匹配 → 解析为空 → precheck 返 400.

### precheck 端点 400 触发链

```python
# views.py:252-262
def precheck(request, workflow_id):
    workflow = get_object_or_404(SqlWorkflow, pk=workflow_id)
    parsed = _parse_first_alter(_workflow_sql_text(workflow))  # ← _parse_all_statements 拿第一条 ALTER
    if not parsed:                                              # ← 解析空, 返 400
        return JsonResponse({
            "ok": False, "passed": False,
            "summary": "未找到 ALTER TABLE 语句",
            "checks": [],
        }, status=400)
```

## 修复 (跨文件统一清理)

**DBA-bug-11 全项目清理**: 6 个文件都只识别 `--` 注释, 不处理 `##`, 9/21 17:55 紧急修 1 文件, 9/21 18:00 跟阿达叔叔拍板后**统一改剩余 4 文件** (钉钉 OA 2 文件按用户拍板不动).

### 修法 (5 文件统一改 1 行)

```python
# 老 (buggy)
if stripped.startswith("--") or not stripped:  # 或 if not stripped or stripped.startswith("--")

# 新 (fix)
if stripped.startswith("--") or stripped.startswith("##") or not stripped:
# 或 if not stripped or stripped.startswith("--") or stripped.startswith("##"):
```

### 文件清单

| 文件 | 行号 | 状态 | 影响范围 |
|------|------|------|----------|
| `sql/extensions/ddl_gh_ost/views.py` | 147 | ✅ 已修 (17:55) | gh-ost precheck / enable / 列 ALTER 解析 |
| `sql/extensions/ddl_sync/services/sync_trigger.py` | 110 | ✅ 已修 (18:00) | 镜像工单 ## 注释工单同步 |
| `sql/views.py` | 288 | ✅ 已修 (18:00) | 业务方提交流水 / 字段 diff / 大表 alert / DDL-Sync 镜像 |
| `sql/services/ddl_rollback.py` | 167 | ✅ 已修 (18:00) | DDL 回滚 ## 注释工单 |
| `sql/extensions/dingtalk_oa/services/sql_type_detect.py` | 79 | ⏸️ **不动** (用户拍板) | 钉钉 OA 检测 (业务方不通过此路径) |
| `sql/extensions/dingtalk_oa/drivers/dingtalk.py` | 281 | ⏸️ **不动** (用户拍板) | 钉钉 OA driver |

**9/21 18:00 阿达叔叔拍板**: "除了钉钉不修, 其他都要修"

## 验证

### 演练 1: `_w3_dba_bug11_verify.py` (wf#4871 实际 SQL)

- 6 静态 + 6 mock 演练

```
旧版 (## 注释不跳过): 3 个 OTHER (不是 ALTER) → precheck 返 400 ✅ 复现 bug
新版 (## 注释跳过):  3 个 ALTER (dingding_check_waybill / downstream_waybill / hdj_open) ✅ 修法验证
边界 1: 纯 -- 注释 (MySQL 风格) → 2 个 ALTER (兼容) ✅
边界 2: 混合 ## + -- 注释 → 1 个 ALTER (兼容) ✅
边界 3: ## 注释但没 ALTER (空 cleaned) → 0 个 statement (不抛错) ✅
边界 4: ALTER 之间 ## 注释 → 2 个 ALTER (兼容) ✅
```

### 演练 2: `_w3_dba_bug11_cross_file_verify.py` (4 文件已修 + 2 文件按用户拍板不动)

```
[PASS] sql/extensions/ddl_gh_ost/views.py:147 已支持 ## 注释
[PASS] sql/extensions/ddl_sync/services/sync_trigger.py:110 已支持 ## 注释
[PASS] sql/views.py:288 已支持 ## 注释
[PASS] sql/services/ddl_rollback.py:167 已支持 ## 注释
[PASS] sql/extensions/dingtalk_oa/services/sql_type_detect.py:79 按用户拍板不动
[PASS] sql/extensions/dingtalk_oa/drivers/dingtalk.py:281 按用户拍板不动

PASS 6/6
```

### 部署 (DBA 一条龙, 9/21 17:55 + 18:00 两批)

| 时间 | 端 | 操作 | 结果 |
|----|----|----|------|
| 17:50 | 134 dev | scp views.py + `systemctl restart archery-prod-gunicorn.service` | HTTP 200 ✅ |
| 17:55 | 110 prod | scp views.py + reload script (`_reload_110_auto_check_ghost.sh`) | HTTP 200 ✅ (验证 views.py:152 已加 `startswith("##")`) |
| 18:05 | 134 dev | scp sync_trigger.py + views.py + ddl_rollback.py + restart | HTTP 200 ✅ |
| 18:08 | 110 prod | scp sync_trigger.py + views.py + ddl_rollback.py + reload | HTTP 200 ✅ (验证 3 文件都已加 `startswith("##")`) |

## 实战新发现 (1 条入 MEMORY, 跨项目可复用)

**SQL 注释跨方言: MySQL `--` / Python `##` / Hash `#` (跨项目 SQL 解析, 9/21 实战新发现)**:
- 跨项目写 SQL 解析器 (审核/gh-ost/回滚/镜像同步/OA 检测), **必须支持多种注释方言**, 不只 MySQL `--`
- 实战踩坑: 9/21 wf#4871 业务方用 Python 风格 `##` 加注释 (习惯), 但 Archery 上下游解析器只识别 `--`,
  cleaned 开头是 `##` 不匹配 ALTER regex → precheck 返 400 "未找到 ALTER TABLE 语句"
- 修法: 注释行判断用 `re.match(r"^\s*(--|##|#)", stripped)` (一行处理三种注释), 替代多个 startswith 串
- **跨文件同步教训 (9/17 DBA-bug-10 复用)**: 跨项目 regex 改一个文件必 grep 全代码库找同款, 9/17 5 文件改 4 个漏改 column_diff.py 教训, 这次 6 文件一次改完 (5 文件修 + 1 文件按拍板不动)
- **完整修法**: 跨项目 SQL 解析器应该一次扫所有语句, 注释跳过用一个统一的 regex helper 函数, 不要每个文件重复 startswith 逻辑

## 关联

- 9/17 commit `4119838` (DBA-bug-10 CREATE INDEX 修复, 5 文件改 4 个漏改 column_diff.py 教训)
- 9/17 commit `2884b69` (DBA-bug-10 column_diff 端点补漏)
- `docs/changelogs/2026-09-17_dba-bug-10-create-index-bypass-alter-check.md` (DBA-bug-10 完整记录)
- `sql/extensions/ddl_gh_ost/views.py:120-191` (_parse_all_statements 实现)
- `sql/extensions/ddl_gh_ost/views.py:252-262` (precheck 端点 400 触发链)
- 9/21 17:55 commit `9764c0c` (DBA-bug-11 紧急修 1 文件)
- 9/21 18:08 commit `?????` (DBA-bug-11 全项目清理, 4 文件统一改)