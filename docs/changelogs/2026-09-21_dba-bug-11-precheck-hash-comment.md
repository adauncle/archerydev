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

## 修复

文件: `sql/extensions/ddl_gh_ost/views.py` (1 文件, 1 行)

```python
# 修法 (views.py:152)
if stripped.startswith("--") or stripped.startswith("##") or not stripped:
    continue
```

## 验证

### 演练 `scripts/_w3_dba_bug11_verify.py`

- 6 静态 + 6 mock 演练 (wf#4871 实际 SQL)

```
旧版 (## 注释不跳过): 3 个 OTHER (不是 ALTER) → precheck 返 400 ✅ 复现 bug
新版 (## 注释跳过):  3 个 ALTER (dingding_check_waybill / downstream_waybill / hdj_open) ✅ 修法验证
边界 1: 纯 -- 注释 (MySQL 风格) → 2 个 ALTER (兼容) ✅
边界 2: 混合 ## + -- 注释 → 1 个 ALTER (兼容) ✅
边界 3: ## 注释但没 ALTER (空 cleaned) → 0 个 statement (不抛错) ✅
边界 4: ALTER 之间 ## 注释 → 2 个 ALTER (兼容) ✅
```

### 部署 (DBA 一条龙)

1. **134 dev (9/21 17:50)**: scp + `systemctl restart archery-prod-gunicorn.service` + HTTP 200
2. **110 prod (9/21 17:55)**: scp + reload script (`_reload_110_auto_check_ghost.sh`) + HTTP 200
   - 验证 110 prod views.py:152 已加 `startswith("##")` ✅

## 已知未修 (跨文件 ## 注释审计)

6 个文件都只识别 `--` 注释, 不处理 `##`. **本 commit 只修了 1 个文件 (gh-ost views.py)**, 其他 5 个文件作为待清理:

| 文件 | 行号 | 状态 | 风险 |
|------|------|------|------|
| `sql/extensions/ddl_gh_ost/views.py` | 147 | ✅ 已修 | - |
| `sql/extensions/ddl_sync/services/sync_trigger.py` | 110 | ❌ 待修 | 镜像工单 ## 注释工单同步会失败 |
| `sql/views.py` | 288 | ❌ 待修 | 业务方提交流水 ## 注释解析 |
| `sql/services/ddl_rollback.py` | 167 | ❌ 待修 | DDL 回滚 ## 注释工单解析 |
| `sql/extensions/dingtalk_oa/services/sql_type_detect.py` | 79 | ❌ 待修 | 钉钉 OA 工单类型检测 |
| `sql/extensions/dingtalk_oa/drivers/dingtalk.py` | 281 | ❌ 待修 | 钉钉 OA driver |

**建议下一波统一改**: 跨文件 ## 注释支持, 演练覆盖 6 文件, 一次性 commit.

## 实战新发现 (1 条入 MEMORY, 跨项目可复用)

**SQL 注释跨方言: MySQL `--` / Python `##` / SQL Server `--` / Hash `#` (跨项目 SQL 解析, 9/21 实战新发现)**:
- 跨项目写 SQL 解析器 (审核/gh-ost/回滚/镜像同步/OA 检测), **必须支持多种注释方言**, 不只 MySQL `--`
- 实战踩坑: 9/21 wf#4871 业务方用 Python 风格 `##` 加注释 (习惯), 但 Archery 上下游解析器只识别 `--`,
  cleaned 开头是 `##` 不匹配 ALTER regex → precheck 返 400 "未找到 ALTER TABLE 语句"
- 修法: 注释跳过加 `startswith("##")` (Python 风格) + `startswith("#")` (MySQL `CREATE TABLE # tmp` 临时表常用, 单行 hash 注释 5.7+ 支持)
- 跨文件同步: 6 个文件都只识别 `--`, 改一个文件不够, 9/17 DBA-bug-10 教训 (5 文件改 4 个漏改 column_diff.py) 复用
- 完整修法: 注释行判断用 `re.match(r"^\s*(--|##|#)", stripped)` (一行处理三种注释), 替代多个 startswith 串

## 关联

- 9/17 commit `4119838` (DBA-bug-10 CREATE INDEX 修复, 5 文件改 4 个漏改 column_diff.py 教训)
- 9/17 commit `2884b69` (DBA-bug-10 column_diff 端点补漏)
- `docs/changelogs/2026-09-17_dba-bug-10-create-index-bypass-alter-check.md` (DBA-bug-10 完整记录)
- `sql/extensions/ddl_gh_ost/views.py:120-191` (_parse_all_statements 实现)
- `sql/extensions/ddl_gh_ost/views.py:252-262` (precheck 端点 400 触发链)