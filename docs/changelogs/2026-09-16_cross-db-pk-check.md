# 跨库 SQL 检测 + INSERT 主键冲突检测 (DBA 一条龙全包, 9/16 阿达叔叔拍板 A 严格)

> **DBA 实战背景**:
> - 9/16 09:00 阿达叔叔反馈 wf#4821 (alter table hly_usercenter.accesscard_user_vehicle_change 跨库)
> - 9/16 09:00 阿达叔叔反馈 wf#4834 (INSERT 306/307/308/309 重复 PK) 业务方实战工单
> - 9/16 09:23 阿达叔叔拍板 **A 严格** (跨库 reject 阻止提交 + PK 冲突 reject 阻止提交), DBA 一条龙全包

## 现象

### wf#4821 跨库实战 (9/16 09:00)

```
工单详情 ID 2 warning: 'ocr_travel_vehicletype' 不允许为null(表 'accesscard_vehicle_change'). 880829
-- #24426 特殊车型产品限制需求上线
-- 业务侧需区分并记录"OCR自动识别"与"用户手动修改"两种行驶证类型, 为后续数据采集分析提供依据.
ALTER TABLE accesscard_vehicle_change ADD COLUMN ocr_travel_vehicletype VARCHAR(150) DEFAULT NULL COMMENT '系统识别行驶证车辆类型'
工单详情 ID 3 warning: 'ocr_travel_vehicletype' 不允许为null(表 'accesscard_user_vehicle_change'). 13174
ALTER TABLE hly_usercenter.accesscard_user_vehicle_change ADD COLUMN ocr_travel_vehicletype varchar(150) DEFAULT NULL COMMENT 'OCR行驶证车辆类型'
```

业务方 select 的是 `hly_accesscard` 库, 但 ID 3 那条 SQL 改的 `hly_usercenter.accesscard_user_vehicle_change`, **跨库操作, Archery 上游完全没拦截**。

### wf#4834 PK 冲突实战 (9/16 09:00)

```
工单详情 ID 10 error: Execute: Duplicate entry '306' for key 'output_fee_config.PRIMARY'. 1
INSERT INTO 'hly_datacenter_mod'.'output_fee_config' VALUES (306, '2', 185, 'Ai通...')
```

业务方 INSERT 15 条记录, 其中 306/307/308/309 跟前面 #1-#9 行错位重复, **执行到第 10 条才发现 PK 冲突**, 浪费 14 条 approve 工单流。

## 根因 (9/16 调研)

### Archery 上游 + inception/goinception 能力边界

|能力项 | Archery 上游 | inception/goinception | 结论 |
|---|---|---|---|
| 跨库 SQL 检测 | ❌ 无 | ❌ 无 (inception 只做语法/语义) | **不能, 二次开发** |
| INSERT PK 冲突预检 | ❌ 无 | ❌ 无 (inception `--real_row_count` 只能拿影响行数, 不查 PK 现有值) | **不能, 二次开发** |

### 关键代码证据

**`sql/engines/goinception.py:82-87` execute_check 强制 `use '{db_name}'` 走 inception**:
```python
inception_sql = f"""/*--user='{user}';--password='{password}';--host='{host}';--port={port};--check=1;{real_row_count_option}*/
                    inception_magic_start;
                    {set_session_sql}
                    use `{db_name}`;
                    {sql.rstrip(';')};
                    inception_magic_commit;"""
```

业务方 SQL 文本 `alter table hly_usercenter.accesscard_user_vehicle_change` 走 inception 时只检测语法, **不判定是不是 db_name 库** (inception 不知道业务方 select 的库)。

**inception (https://github.com/hanchuanchuan/goInception) 能力 = SQL 语法 + 受影响行数估计**, 无"跨库语义"和"PK 现有值查询"。

## 修法 (A 严格, 9/16 阿达叔叔拍板)

### 修法 A: 跨库限制 (reject + 阻止提交按钮)

**核心逻辑** (新建 `sql/utils/cross_db_check.py`, ~250 行):
```python
def check_cross_db(sql_content: str, instance, db_name: str) -> dict:
    """跨库 SQL 检测: 业务方 SQL 涉及的所有库必须跟 db_name 一致."""
    schemas = _extract_schemas(sql_content)  # 扫所有 DDL/DML 提取 schema 名
    # 业务方 SQL 没指定库名 (无 schema) → 默认同库
    if not schemas or schemas == {None}:
        return {"ok": True, "schemas": [], "expected_db": db_name}
    # 业务方 SQL 涉及其他库 → 跨库 reject
    other_schemas = sorted([s for s in schemas if s and s.lower() != db_name.lower()])
    if other_schemas:
        return {
            "ok": False,
            "error": f"⚠️ 跨库 SQL 检测失败: SQL 涉及库 {other_schemas} 跟您选的库 {db_name} 不一致...",
            ...
        }
    return {"ok": True, ...}
```

**SQL 解析算法** (跟 9/11 DBA-bug-1/2 实战新发现一致):
- 6 个 regex: `ALTER TABLE` / `INSERT INTO` / `UPDATE` / `DELETE FROM` / `CREATE TABLE` / `DROP TABLE`
- 预处理: 跳过 `USE` / `-- 注释` / 空行 (DBA-bug-1 套路)
- regex 一致性: 跟 column_diff.py:402-405 / sync_trigger.py:67-71 / views.py:272 完全对齐 (DBA-bug-2 实战新发现)
- 支持反引号 schema + 不带反引号 schema (DBA-bug-2 实战新发现)
- **9/16 实战 bug fix**: 用 `\bALTER\s+TABLE\s+` 不用 `^\s*` (业务方多行无 `;` wf#4821), regex 改 `finditer` 全局扫描不依赖 `;` 分隔

### 修法 A: INSERT PK 冲突检测 (reject + 阻止提交按钮)

**核心逻辑** (新建 `sql/utils/pk_conflict_check.py`, ~470 行):
```python
def check_pk_conflict(sql_content: str, instance, db_name: str) -> dict:
    """INSERT 主键冲突检测: 解析所有 INSERT, 查 DB 看 PK 值是否已存在."""
    inserts = _extract_inserts(sql_content)  # 扫所有 INSERT 提取 (schema, table, columns, values_list)
    # 合并所有 INSERT 的 (table, pk_values) 用于一次查询
    table_pk_map = _build_table_pks(inserts, instance, db_name)
    # 查 DB 拿每个表的 PK 冲突
    for table, info in table_pk_map.items():
        existing = _query_existing_pks(instance, db_name, table, info["pk_col"], info["pk_values"])
        if existing:
            conflicts.append({...})
```

**关键设计**:
- **不走 inception**, Archery 直接 PyMySQL 连实例查 DB (用 `Instance.get_username_password()` 拿 mirage 解密凭据)
- **一次查询拿所有 PK 冲突**: `SELECT pk_col FROM table WHERE pk_col IN (306, 307, ...) LIMIT 1000`
- **大表 IN 限制**: 一次最多查 1000 个 PK 值, 避免 SQL IN 太大
- **9/16 实战踩坑修了 3 个 bug**:
  1. `_split_values_tuples` 漏 `,` 切分 + `if cur:` 时机错 → 9/16 修
  2. `_resolve_insert_pk_values` 把整行 VALUES 当 PK 值 → 9/16 修, 只取 PK 列对应值
  3. `_strip_quotes('-1')` 漏负数 → 9/16 修, 用 try/except int/float 统一处理
- **9/16 实战演练 16 case PASS**:
  - Case A: ALTER TABLE `hly_usercenter`.accesscard_vehicle_change → 跨库 reject ✓
  - Case B: ALTER TABLE accesscard_vehicle_change (无库名) → 同库 pass ✓
  - Case C: ALTER TABLE `hly_accesscard`.accesscard_vehicle_change → 同库 pass ✓
  - Case D: ALTER TABLE hly_usercenter.accesscard_vehicle_change (不带反引号) → 跨库 reject ✓
  - Case E: use hly_usercenter;\nALTER TABLE accesscard_vehicle_change → 同库 pass (USE 跳过) ✓
  - Case F: INSERT INTO output_fee_config VALUES (306, ...) → PK 冲突 reject ✓
  - Case G: INSERT INTO output_fee_config VALUES (999, ...) → PK pass ✓
  - Case H: INSERT INTO output_fee_config VALUES (306, ...), (999, ...) → PK 部分冲突 reject ✓
  - Case I: INSERT INTO no_pk_table VALUES (...) → 表无 PK skip ✓
  - Case J: 老工单回归 wf#4791 / wf#4792 / wf#4783 → 不受影响 ✓
  - **Case P (9/16 实战 bug fix)**: wf#4821 多行 ALTER 无 `;` 跨库 reject ✓ (业务方多行 SQL 无分号, 原 `_extract_schemas` 按 `;` 拆分漏检测, 9/16 修)

### 前端 UX (sqlsubmit.html 检测后回调)

```javascript
// 检测后回调加 2 类 alert + 阻止提交按钮 (DBA-bug-6 UX 教训: UI 跟后端判断逻辑必须对齐)
var hasBlockError = false;
// 1. 跨库检测 alert (红框, 在 inception-result 上面, 业务方第一眼看到)
$("#cross-db-alert-w3").remove();
if (result.cross_db_check && !result.cross_db_check.ok) {
    var crossDbHtml = '<div class="alert alert-danger" id="cross-db-alert-w3" ...>...</div>';
    $("#inception-result").before(crossDbHtml);
    hasBlockError = true;
}
// 2. PK 冲突检测 alert (红框)
$("#pk-conflict-alert-w3").remove();
if (result.pk_conflict_check && !result.pk_conflict_check.ok) {
    var pkConflictHtml = '<div class="alert alert-danger" id="pk-conflict-alert-w3" ...>...</div>';
    $("#inception-result").before(pkConflictHtml);
    hasBlockError = true;
}
// 3. 阻止提交按钮 + 改文案 (DBA-bug-6 UX 教训)
if (hasBlockError) {
    $('#btn-submitsql').addClass('disabled').prop("disabled", true).text("请先修复跨库/PK 冲突");
} else {
    $('#btn-submitsql').removeClass('disabled').prop("disabled", false).text("提交");
}
```

**前端 UX 设计要点**:
- **红框 alert 在 inception-result 上面**, 业务方第一眼看到风险 (DBA-bug-1/2 实战新发现)
- **阻止提交按钮 + 改文案** (DBA-bug-6 UX 教训: UI 跟后端判断逻辑必须对齐)
- **允许改 SQL 后重新检测 + 提交按钮自动解锁**
- **escapeHtml() 防 XSS** (DBA-bug-3 hotfix 实战新发现复用)

## 改动清单 (5 文件)

| 文件 | 改动 | 行数 |
|---|---|---|
| sql/utils/cross_db_check.py | 新建 (~250 行) | +250 |
| sql/utils/pk_conflict_check.py | 新建 (~470 行) | +470 |
| sql_api/api_workflow.py | ExecuteCheck.post 加 2 个 check (line 73-76) | +30 |
| sql_api/serializers.py | ExecuteCheckResultSerializer 加 2 字段 + context 注入 | +25 |
| sql/templates/sqlsubmit.html | autoreview success 回调加 2 类 alert + 阻止提交按钮 | +50 |

## 134 dev 演练 (16 case 全 PASS)

```
=== A 跨库 reject ===
input: ALTER TABLE `hly_usercenter`.accesscard_vehicle_change ADD COLUMN xxx
result: ok=False, error='SQL 涉及库 ["hly_usercenter"] 跟您选的库 hly_accesscard 不一致'

=== B 同库 pass ===
input: ALTER TABLE accesscard_vehicle_change ADD COLUMN xxx
result: ok=True

=== C 反引号同库 pass ===
input: ALTER TABLE `hly_accesscard`.accesscard_vehicle_change ADD COLUMN xxx
result: ok=True

=== D 不带反引号跨库 reject ===
input: ALTER TABLE hly_usercenter.accesscard_vehicle_change ADD COLUMN xxx
result: ok=False

=== E use 切换库不算跨库 ===
input: use hly_usercenter;\nALTER TABLE accesscard_vehicle_change ADD COLUMN xxx
result: ok=True (use 跳过)

=== F PK 冲突 reject (wf#4834 实战主验证) ===
input: INSERT INTO `hly_datacenter_mod`.`output_fee_config` VALUES (306, 2, 185, 'Ai通...')
result: ok=False, conflicts=[{table: 'hly_datacenter_mod.output_fee_config', pk_col: 'id', existing_pks: [306], duplicate_count: 1}]

=== G PK 不冲突 pass ===
input: INSERT INTO output_fee_config VALUES (999, ...)
result: ok=True

=== H 多值 INSERT PK 部分冲突 ===
input: INSERT INTO output_fee_config VALUES (306, 1, ...), (999, 2, ...)
result: ok=False, existing_pks=[306]

=== I 表无 PK skip ===
input: INSERT INTO no_pk_table VALUES (...)
result: ok=True

=== O 多个 ALTER 一个跨库 reject ===
input: ALTER TABLE accesscard_vehicle_change ADD COLUMN a INT;\nALTER TABLE hly_usercenter.xxx ADD COLUMN b INT
result: ok=False (跨库 reject)

=== P wf#4821 多行 ALTER 无 `;` 跨库实战 (9/16 实战 bug fix) ===
input: use hly_accesscard\nALTER TABLE accesscard_vehicle_change ...\nALTER TABLE hly_usercenter.accesscard_user_vehicle_change ...
result: ok=False (跨库 reject, 9/16 finditer 修复)

=== J 老工单回归 ===
input: wf#4791 (源工单 9/8 老工单), wf#4792 (镜像工单), wf#4783 (8/26 老工单 pic_url)
result: 全 PASS, 不受影响
```

## 实战新发现 (跨项目可复用, 6 条)

### 1. **SQL 检测覆盖度必考虑业务方真实形态** (W3 跨项目实战新发现)

跨项目写 SQL 检测功能, 必考虑业务方真实 SQL 形态 (跨库 / 重复 PK / use 切换库 / 多值 INSERT / 复合 PK / 表无 PK / 表权限不够 / 表不存在), 别只考虑单条干净 SQL。实战踩坑: 9/16 wf#4821 业务方用反引号 schema + wf#4834 业务方没指定列名 + wf#4834 同 INSERT 重复 PK, **实战 case 比单元测试覆盖度丰富 10 倍**。修法: 单元测试必覆盖 10+ 真实业务方实战 case, 别只覆盖 happy path。

### 2. **跨项目 regex 一致性必对齐** (9/11 DBA-bug-2 实战新发现复用)

跨项目写多个 regex 解析同一类输入, **必对齐格式** (反引号/不反引号/use/注释/多语句都支持)。实战踩坑: W3 cross_db_check.py 跟 column_diff.py:402-405 / sync_trigger.py:67-71 / views.py:272 完全对齐 (regex 一致性), 避免 N 处 regex 各写各的。修法: 跨项目写 regex 必先 `grep -rn "re.compile.*ALTER.*TABLE" .` 看现有写法, 全对齐。

### 3. **跨库检测 + PK 冲突检测是 Archery 上游设计漏洞** (W3 跨项目实战新发现)

跨项目用 Archery 1.14.0, 上游 SQL 检测走 inception/goinception, **没有跨库语义检测和 PK 现有值查询** (inception 只检测语法/语义 + 受影响行数估计)。修法: 跨项目用 Archery, 如需跨库限制/PK 冲突预检/其他语义级 SQL 检测, **必二次开发**, 别指望 inception/goinception 帮你做。

### 4. **UI 跟后端判断逻辑必须对齐** (9/15 DBA-bug-6 实战新发现复用)

跨项目写"阻止提交"类功能, **前端必同步阻止按钮** (disabled + 改文案), 别只在前端 alert 不阻止提交 (业务方大概率忽略 alert)。实战踩坑: W3 跨库/PK 检测后, alert + 按钮 disabled + 改文案 3 件事一起做, 业务方第一眼看到 alert + 点不了提交按钮, 避免 UX 误导。

### 5. **大表 PK 冲突 IN 限制 1000 + LIMIT N** (W3 跨项目实战新发现)

跨项目写"SQL IN 批量查询"功能, **必限制 IN 列表大小** (e.g. 1000), 避免 SQL IN 太大 (MySQL max_allowed_packet 默认 64MB, IN 10000 个值可能超 1MB)。实战踩坑: W3 pk_conflict_check.py `_query_existing_pks` 截断到 1000 + warning log, 大表实战也安全。修法: 跨项目写 SQL IN 必加 `LIMIT N` 兜底 + 截断 warning。

### 6. **业务方多行 SQL 无 `;` 分隔, regex 必支持 finditer 全局扫描** (W3 跨项目实战新发现, 9/16 bug fix)

跨项目写 SQL 解析功能, **业务方实战 SQL 行间不一定有 `;` 分隔** (wf#4821 实战 3 条 SQL 行间无 `;`)。实战踩坑: W3 初版 `_extract_schemas` 按 `;` 拆分, 漏掉第二个 ALTER 跨库检测。**第一次 fix 错 (用 finditer 但 regex 还带 `^\s*` 行首限制, finditer 只匹配字符串开头)**, 第二次修对 (regex 改 `\bALTER\s+TABLE\s+` 不用 `^\s*`, finditer 全局扫描)。**修法**: 跨项目写 SQL 解析, 1) regex 必去掉 `^`/`^\s*` 行首限制, 改用 `\b` 词边界; 2) 用 `re.finditer` 全局扫描, 不依赖 `;` 分隔; 3) 必加"业务方实战多行无 `;`"回归测试 case。

### 7. **gunicorn reload 必 reload master, 只 kill workers 不够** (9/16 W3 跨环境实战新发现)

跨项目用 gunicorn 跑 Python 应用, **只 kill -TERM workers 不 reload master = 代码不进内存**。实战踩坑: 9/16 W3 推代码到 134 dev + 110 prod 后, 之前"9/15 实战法 reload"只 kill workers 不动 master, 但 master 是 Sep15 启动的, 内存里是 Sep15 代码, 9/15 23:30 之后的 commit 全部没进内存 (DBA-bug-7 + W3 都没生效)。修法: 跨项目推代码后 **必 reload master**: 134 dev `systemctl restart archery-prod-gunicorn.service`; 110 prod `kill -TERM <master_pid> && nohup setsid 重启`。reload master 业务中断 ~10-30 秒, 是 DBA 运维常规操作, 不动数据和表结构。**教训**: 之前 9/15 实战新发现 "gunicorn reload 不动 master, 只杀 workers" 是错的 (前提是 master 之前 reload 过, 内存里有新代码; master Sep15 启动后没 reload 过, 内存是 Sep15 代码)。

## 同源 entry (DBA 一天实战接龙, 9/11-9/16)

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
- **9/16 09:23 W3 跨库限制 + INSERT PK 冲突检测 (本 entry, A 严格, DBA 一条龙全包, 含 finditer 修复 + master reload 实战)**

## 下次推 prod checklist 必加 4 条 (W3 实战新发现)

1. **SQL 检测覆盖度必考虑业务方真实形态** (跨库 / 重复 PK / use 切换库 / 多值 INSERT / 复合 PK / 表无 PK / 表权限不够 / 表不存在), 单元测试必覆盖 10+ 真实业务方实战 case
2. **跨项目 regex 一致性必对齐** (反引号/不反引号/use/注释/多语句都支持), 必 `grep -rn "re.compile.*ALTER.*TABLE" .` 看现有写法
3. **UI 跟后端判断逻辑必须对齐** (alert + 按钮 disabled + 改文案 3 件事一起做), 别只前端 alert 不阻止提交
4. **gunicorn 推代码后必 reload master** (`systemctl restart` 或 `kill -TERM master_pid && nohup setsid 重启`), 只 kill workers 不动 master 不够 (master 内存里还是老代码)

## 上线操作日志 (9/16)

1. 09:23 阿达叔叔拍板 A 严格
2. 09:30 评估 Archery + inception/goinception 能力边界 (不能, 必二次开发)
3. 10:00 写设计稿 + 2 个 service + api_workflow.py + serializers.py + sqlsubmit.html
4. 10:30 单元测试 PASS (cross_db 15/15 + pk_conflict 3/3) + commit c65c93e + push origin
5. 11:30 134 dev master `systemctl restart archery-prod-gunicorn.service` (事故发现: 134 dev master Sep15 11:40 启动后没 reload 过)
6. 11:32 134 dev 端到端演练 11/11 PASS (含 wf#4821/wf#4834 实战回归)
7. 12:03 110 prod 推 W3 5 文件
8. 12:09 110 prod master `kill -TERM 11185 && nohup setsid 重启` (事故发现: 110 prod master Sep15 17:42 启动后没 reload 过)
9. 12:18 发现 wf#4821 多行无 `;` bug → finditer 修复 (第一次修错, 第二次修对) → 推 134 dev + 110 prod
10. 12:31 134 dev 单元测试 16/16 PASS (含 Case P wf#4821 多行无 `;` 实战回归)
11. 12:33 110 prod master `kill -TERM 95623 && nohup setsid 重启` (第二次 reload, 让 finditer 修复进内存)
12. 12:34 110 prod HTTP 200 验证 ✅
13. 12:35 凭据清理: `_dba_bug5a_deploy_110.ps1` 移到 `_archive/` + 密码改为 `$env:ARCHERY_PROD_PASSWORD` 占位符
14. 12:36 业务方通知文案 + 110 prod 临时演练脚本清理 (按"不要动生产任何数据和表结构"原则)