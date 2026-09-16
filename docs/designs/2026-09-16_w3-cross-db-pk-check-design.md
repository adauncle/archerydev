# W3 跨库限制 + INSERT PK 冲突检测 (业务方实战需求, 9/16 阿达叔叔拍板)

> **DBA 实战背景**:
> - 9/16 09:00 阿达叔叔反馈 wf#4821 (alter table hly_usercenter.accesscard_user_vehicle_change 跨库) + wf#4834 (INSERT 306 重复 PK) 业务方实战工单
> - 阿达叔叔拍板 **A 严格 (跨库 reject 阻止提交 + PK 冲突 reject 阻止提交)**, DBA 一条龙全包
> - 关联: 9/11-9/15 DBA-bug-1/2/3/4/5/6/7 实战接龙, 业务方实战驱动型需求

## 1. 需求评估 (9/16 调研)

|能力项 | Archery 上游 | inception/goinception | 结论 |
|---|---|---|---|
| 跨库 SQL 检测 | ❌ 无 | ❌ 无 (inception 只做语法/语义) | **不能, 二次开发** |
| INSERT PK 冲突预检 | ❌ 无 | ❌ 无 (inception `--real_row_count` 只能拿影响行数, 不查 PK 现有值) | **不能, 二次开发** |

**关键证据**:
- `sql/engines/goinception.py:82-87` execute_check 强制 `use '{db_name}'` 走 inception, inception 检测的是 db_name 库的 SQL
- 业务方 SQL 文本 `alter table hly_usercenter.accesscard_user_vehicle_change` 走 inception 时只检测语法, **不判定是不是 db_name 库**
- inception (https://github.com/hanchuanchuan/goInception) 能力 = SQL 语法 + 语义 + 受影响行数估计, **无"跨库语义"和"PK 现有值查询"**

## 2. 方案设计 (A+A 严格, 9/16 阿达叔叔拍板)

### 2.1 跨库限制 (A 严格: reject + 阻止提交按钮)

**实现位置**: `/api/v1/workflow/sqlcheck/` 端点 (sql_api/api_workflow.py:50-78 ExecuteCheck.post)
- 走 inception 检测**之后**, 附加 cross_db_check
- 前端 sqlsubmit.html 检测后回调: 检测到跨库 → 红框 alert + 阻止提交按钮

**核心逻辑** (sql/utils/cross_db_check.py 新建, ~120 行):
```python
def check_cross_db(sql_content: str, instance, db_name: str) -> dict:
    """扫描所有 SQL 语句, 提取表名前缀, 跟 instance.db_name 比对.

    - 业务方 select 的库 = hly_accesscard
    - SQL 里 ALTER TABLE `hly_usercenter`.`accesscard_user_vehicle_change` → 跨库 ❌
    - SQL 里 ALTER TABLE `hly_accesscard`.`accesscard_vehicle_change` → 同库 ✅
    - SQL 里 ALTER TABLE accesscard_vehicle_change (无库名) → 同库 ✅
    - SQL 里 USE `hly_usercenter` 切换库 → 不算跨库 (DBA-bug-1 已有 use 跳过)
    """
    schemas = _extract_schemas(sql_content)  # 扫所有 DDL/DML 提取 schema 名
    if not schemas:
        return {"ok": True, "schemas": []}  # 没提取到任何 schema, 默认同库
    other_schemas = [s for s in schemas if s.lower() != db_name.lower()]
    if other_schemas:
        return {
            "ok": False,
            "error": (f"⚠️ 跨库 SQL 检测失败: SQL 涉及库 {other_schemas} 跟您选的库 "
                      f"{db_name} 不一致. Archery 工单不允许跨库执行, "
                      f"请选择对应库 (如 hly_usercenter), 或删除库名前缀 (如 "
                      f"`hly_usercenter`.accesscard_vehicle_change → accesscard_vehicle_change). "
                      f"如需跨库变更, 请拆分成多个工单."),
            "schemas": sorted(set(schemas)),
            "expected_db": db_name,
        }
    return {"ok": True, "schemas": sorted(set(schemas))}
```

**SQL 解析场景覆盖**:
- ALTER TABLE `hly_usercenter`.`accesscard_xxx` ← 跨库 ❌ (反引号 schema + table)
- ALTER TABLE hly_usercenter.accesscard_xxx ← 跨库 ❌ (不带反引号)
- ALTER TABLE accesscard_xxx ← 同库 ✅ (无库名)
- ALTER TABLE `hly_accesscard`.accesscard_xxx ← 同库 ✅
- ALTER TABLE `hly_accesscard`.`accesscard_xxx` ← 同库 ✅ (反引号一致)
- INSERT INTO `hly_usercenter`.`output_fee_config` ← 跨库 ❌
- INSERT INTO output_fee_config ← 同库 ✅
- INSERT INTO `hly_accesscard`.`output_fee_config` ← 同库 ✅
- UPDATE hly_usercenter.xxx ← 跨库 ❌
- DELETE FROM hly_usercenter.xxx ← 跨库 ❌
- CREATE TABLE hly_usercenter.xxx ← 跨库 ❌
- DROP TABLE hly_usercenter.xxx ← 跨库 ❌
- USE `hly_usercenter` ← 切换库不算跨库 (DBA-bug-1 已有 use 跳过)
- SELECT ... ← 查询语句不算跨库 (允许, DQL 不写数据)

**SQL 解析算法**:
- 预处理 SQL: 跳过 `USE` / `-- 注释` / 空行 (跟 9/11 DBA-bug-1 套路一致)
- 5 个 DDL/DML regex: `ALTER TABLE`, `INSERT INTO`, `UPDATE`, `DELETE FROM`, `CREATE TABLE`, `DROP TABLE`
- 每个 regex 提取 schema 段: `(?:\`?(?P<schema>[^`\s.()]+)\`?\.)?\`?(?P<table>...)`
- 跨库判定: schema 不空 且 schema != db_name

### 2.2 INSERT PK 冲突检测 (A 严格: reject + 阻止提交按钮)

**实现位置**: `/api/v1/workflow/sqlcheck/` 端点 (sql_api/api_workflow.py:50-78 ExecuteCheck.post)
- 走 inception 检测**之后**, 附加 pk_conflict_check
- 前端 sqlsubmit.html 检测后回调: 检测到 PK 冲突 → 红框 alert + 阻止提交按钮

**核心逻辑** (sql/utils/pk_conflict_check.py 新建, ~150 行):
```python
def check_pk_conflict(sql_content: str, instance, db_name: str) -> dict:
    """扫描所有 INSERT INTO statements, 提取 PK 列 + PK 值, 查 DB 看是否已存在.

    边界:
    - 单条 INSERT: INSERT INTO xxx VALUES (1, 2, 3)
    - 多值 INSERT: INSERT INTO xxx VALUES (1, 2), (4, 5), (7, 8)
    - 多条 INSERT: 多行 INSERT INTO xxx VALUES (...)
    - 表无 PK: skip (用 information_schema.statistics INDEX_TYPE='PRIMARY' 查)
    - 表不存在: skip (inception 已经报错)
    - 表/库 SELECT 权限不够: skip + warning
    """
    inserts = _extract_inserts(sql_content)  # [(table, [(col1_val, col2_val, ...), ...]), ...]
    if not inserts:
        return {"ok": True, "conflicts": []}

    # 合并所有 INSERT 的 (table, pk_values) 用于一次查询
    table_pks = _build_table_pks(inserts, instance, db_name)
    # table_pks = {"output_fee_config": {"pk_col": "id", "pk_values": [306, 307, 308, 309]}}

    conflicts = []
    for table, info in table_pks.items():
        if not info["pk_col"]:
            continue  # 表无 PK 列 (可能没 PK)
        existing = _query_existing_pks(
            instance, db_name, table, info["pk_col"], info["pk_values"]
        )
        # SELECT pk_col FROM table WHERE pk_col IN (306, 307, 308, 309) LIMIT N
        if existing:
            conflicts.append({
                "table": f"{db_name}.{table}",
                "pk_col": info["pk_col"],
                "existing_pks": existing,  # [306, 307]
                "duplicate_count": len(existing),
                "hint":": (f"INSERT 语句中 {info['pk_values']} 这 {len(info['pk_values'])} 个 PK 值"
                            f"在 {db_name}.{table} 表中已存在, 实际 {len(existing)} 个冲突. "
                            f"请修改 VALUES 或拆分成多个工单."),
            })

    return {"ok": not conflicts, "conflicts": conflicts}
```

**关键设计**:
- **不走 inception**, Archery 直接 PyMySQL 连实例查 DB
- **用 `Instance.get_username_password()` 拿 mirage 解密凭据** (跟 gh-ost precheck 同样的方式)
- **一次查询拿所有 PK 冲突**: `SELECT pk_col FROM table WHERE pk_col IN (306, 307, 308, 309) LIMIT 1000`
- **大表 IN 限制**: 一次最多查 1000 个 PK 值, 避免 SQL IN 太大
- **不阻塞提交 (默认 reject, 业务方必须改 VALUES)**

**wf#4834 实战验证**:
- 表: `output_fee_config`, PK: `id`
- 业务方 INSERT 15 条 VALUES (302, 303, ..., 311), 其中 306/307/308/309 重复 INSERT (跟前面 #1-#9 行错位)
- 修法检测: 查 `SELECT id FROM output_fee_config WHERE id IN (302, 303, 304, 305, 306, 307, 308, 309, 310, 311)`
- 实战 wf#4834: 302-305/310/311 没冲突 (首次插入), 306-309 已在表里
- 预期冲突: `conflicts=[{table: "hly_datacenter_mod.output_fee_config", pk_col: "id", existing_pks: [306, 307, 308, 309], duplicate_count: 4}]`

### 2.3 前端 UX (sqlsubmit.html 检测后回调)

```javascript
// 在 inception 检测后, 增加 2 类 alert + 阻止提交按钮
success: function (data) {
    var hasBlockError = false;

    // 1. 跨库检测 alert (红框)
    if (data.cross_db_check && !data.cross_db_check.ok) {
        $("#cross-db-alert").remove();
        var alertHtml = '<div class="alert alert-danger" id="cross-db-alert">' +
                        '<strong>⚠️ 跨库 SQL 检测失败</strong><br>' +
                        data.cross_db_check.error + '</div>';
        $("#inception-result").before(alertHtml);
        hasBlockError = true;
    }

    // 2. PK 冲突检测 alert (红框)
    if (data.pk_conflict_check && !data.pk_conflict_check.ok) {
        $("#pk-conflict-alert").remove();
        var alertHtml = '<div class="alert alert-danger" id="pk-conflict-alert">' +
                        '<strong>⚠️ INSERT 主键冲突</strong><br>' +
                        '<ul>';
        data.pk_conflict_check.conflicts.forEach(function (c) {
            alertHtml += '<li>' + c.table + ' 表 PK 冲突: ' +
                         c.existing_pks.join(', ') + ' (' + c.duplicate_count + ' 个) ' +
                         '<br>' + c.hint + '</li>';
        });
        alertHtml += '</ul></div>';
        $("#inception-result").before(alertHtml);
        hasBlockError = true;
    }

    // 3. 阻止提交按钮 (DBA-bug-6 教训: UI 跟后端判断逻辑必须对齐)
    if (hasBlockError) {
        $("#btn-submit-sql").prop("disabled", true).addClass("disabled")
                            .text("请先修复跨库/PK 冲突");
    } else {
        $("#btn-submit-sql").prop("disabled", false).removeClass("disabled")
                            .text("提交");
    }

    // 4. 检测到错误时弹出 submitConfirm modal (跟原有 UX 一致)
    var CheckWarningCount = data.warning_count || 0;
    var CheckErrorCount = data.error_count || 0;
    if (CheckWarningCount > 0 || CheckErrorCount > 0 || hasBlockError) {
        $('#submitConfirm').modal('show');
    }
}
```

**前端 UX 设计要点** (跨项目实战教训):
- **红框 alert 在 inception-result 上面**, 业务方第一眼看到风险 (DBA-bug-1/2 实战新发现)
- **阻止提交按钮 + 改文案** (DBA-bug-6 UX 教训: UI 跟后端判断逻辑必须对齐)
- **submitConfirm modal 包含跨库/PK 冲突提示** (跟 inception warning 一致 UX)
- **允许改 SQL 后重新检测 + 提交按钮自动解锁**

## 3. 改动清单

| 文件 | 改动 | 行数 |
|---|---|---|
| sql/utils/cross_db_check.py | 新建 (~120 行) | +120 |
| sql/utils/pk_conflict_check.py | 新建 (~150 行) | +150 |
| sql_api/api_workflow.py | ExecuteCheck.post 调 2 个 check (line 73-76) | +20 |
| sql_api/serializers.py | ExecuteCheckResultSerializer 加 2 字段 (line 414) | +2 |
| sql/templates/sqlsubmit.html | autoreview success 回调加 2 类 alert + 阻止提交按钮 (line 573-) | +50 |
| docs/changelogs/2026-09-16_cross-db-pk-check.md | changelog (~8KB) | +200 |

## 4. 134 dev 演练 5 case

| Case | SQL | 预期 |
|---|---|---|
| A 跨库 reject | `ALTER TABLE \`hly_usercenter\`.accesscard_vehicle_change ADD COLUMN xxx` | ok=False, error 含 "hly_usercenter" |
| B 同库 pass | `ALTER TABLE accesscard_vehicle_change ADD COLUMN xxx` | ok=True |
| C 反引号同库 pass | `ALTER TABLE \`hly_accesscard\`.accesscard_vehicle_change ADD COLUMN xxx` | ok=True |
| D 不带反引号跨库 reject | `ALTER TABLE hly_usercenter.accesscard_vehicle_change ADD COLUMN xxx` | ok=False |
| E use 切换库不算跨库 | `use hly_usercenter;\nALTER TABLE accesscard_vehicle_change ADD COLUMN xxx` | ok=True (use 跳过) |
| F PK 冲突 reject | `INSERT INTO output_fee_config VALUES (306, 2, 185, 'Ai通...')` (业务方实战, 306 已存在) | ok=False, existing_pks=[306] |
| G PK 不冲突 pass | `INSERT INTO output_fee_config VALUES (999, 2, 185, '...')` (999 不存在) | ok=True |
| H 多值 INSERT PK 部分冲突 | `INSERT INTO output_fee_config VALUES (306, 1, ...), (999, 2, ...)` | ok=False, existing_pks=[306] |
| I 表无 PK | `INSERT INTO xxx (无 PK 表) VALUES (...)` | ok=True (skip, warning) |
| J 老工单回归 | wf#4791/4792/4783 走 execute_check 不受影响 | ok=True |

## 5. 110 prod 推 + 业务方实测

1. **9/16**: 写设计稿 + 2 个 service + api_workflow.py + serializers.py + sqlsubmit.html (D1)
2. **9/17**: 134 dev 演练 10 case + 老工单回归 (D2)
3. **9/17 下午**: 推 110 prod (D3)
4. **9/18**: 业务方实测 wf#4821 跨库 + wf#4834 PK 冲突 (D4)

## 6. 关联实战新发现 (跨项目可复用)

- **DBA-bug-1/2/3 实战新发现**: SQL 检测覆盖度 + 业务方真实形态 + 状态判断放宽
- **DBA-bug-6 实战新发现**: UI 跟后端判断逻辑必须对齐, 别让用户看到提示还能提交
- **9/11 一条龙实战接龙**: 业务方实战驱动型需求, 5 步 (评估 → 实施 → 演练 → 推 prod → 业务方实测) 闭环

## 7. 同源 entry (D9 一天 DBA-bug 接龙, 9/11-9/15)

- 9/11 17:55 DBA-bug-1 (4b2d19c) drop index + 审批节点不显示
- 9/11 18:50 DBA-bug-2 (7bd988b) 反引号 schema 解析 + 主页面 banner
- 9/11 19:30 DBA-bug-3 (bac9e4f) ADD/DROP INDEX 端点 ok=False 链路 bug
- 9/11 20:10 DBA-bug-3 hotfix (fd7c831) Django 跨行注释 JS 报错
- 9/12 10:50 DBA-bug-4 (软提示) 业务方选错库
- 9/12 10:55 DBA-bug-5 (软提示) DDL 跨库镜像工单 + 历史库表不存在
- 9/12 11:35 DBA-bug-5a (304ba21) sync_trigger.py regex bug
- 9/14 10:11 archery 账号密码被改 (实战)
- 9/15 16:43 DBA-bug-6 (33a966e) 镜像工单取消按钮终态隐藏
- 9/15 17:34 gunicorn reload 事故 (实战新发现)
- 9/15 18:16 DBA-bug-7 (7aa9fb4) 待办列表终态 wf 显示修复
- **9/16 09:23 W3 跨库限制 + INSERT PK 冲突检测 (本 entry, A+A 严格, 立即开干)**

## 8. W3 节奏 (DBA 一条龙全包, 9/16 排期)

| 时间 | 任务 | 状态 |
|---|---|---|
| 9/16 上午 | 写设计稿 | 进行中 (本 entry) |
| 9/16 下午 | W3-D1 实施 2 个 service + api_workflow.py + serializers.py + sqlsubmit.html | 待开干 |
| 9/17 上午 | W3-D2 134 dev 演练 10 case + 老工单回归 | 待开干 |
| 9/17 下午 | W3-D3 推 110 prod (md5 一致性 + reload master + 真 HTTP 演练) | 待开干 |
| 9/18 | W3-D4 业务方实测 wf#4821 跨库 + wf#4834 PK 冲突 | 待业务方实测 |