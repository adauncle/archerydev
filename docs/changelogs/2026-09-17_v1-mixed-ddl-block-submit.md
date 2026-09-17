# v1 优化: 混合 DDL 工单禁止提交 (CREATE + ALTER 拆单)

## 一句话总结

建表 + ALTER 混合提交 → 前端 SQL 检测红框 alert + 阻止提交按钮 + 后端 serializer.create() 兜底 reject,
业务方必须拆分成独立工单。134 dev + 110 prod 演练 8/8 PASS。

## 业务背景

DBA-bug-9 实战 (9/16 17:00+ wf#4841):
- 业务方工单含 **8 条 SQL**: 4 CREATE TABLE + 4 ALTER TABLE
- gh-ost task #26 只处理 ALTER 1 条 (accesscard_licensefront_info ADD owner_name)
- 其他 7 条 SQL 全部丢失 (CREATE 全部, ALTER 3 条)
- 工单状态显示 `workflow_finish` (按时显示), 但实际 1/8 成功, 7/8 失败

旧版提醒模式:
- 9/16 DBA-bug-9.5 阶段前端加 banner: "工单含非 ALTER 语句 (gh-ost 模式不支持)"
- 但只对 gh-ost 工单生效, 且只是提醒, 业务方可以无视继续提交
- 业务方 (wf#4841) 没勾 gh-ost, 但提交时也没拆单, 导致 SQL 部分丢失

v1 优化目标:
- **从"提醒"升级到"禁止"**: SQL 检测到混合 DDL → 阻止提交
- **适用所有工单** (不限于 gh-ost, 普通工单也禁)
- **前后端双层防护**: 前端 disable 按钮 + 后端 serializer.create() 兜底 reject

## 实施 (3 文件 + 1 新演练脚本)

### 1. `sql/views.py` — 加 `_check_mixed_ddl` 函数
- 复用 `_detect_non_alter` 的 SQL 解析逻辑 (按 `;` 分割 + 跳过注释 + 取首 token)
- 检测 SQL 是否同时含 ALTER + CREATE/INSERT/UPDATE/DELETE → 返 `{"ok": False, "error": "...", "types": [...]}`
- USE 跳过 (不算其他 DDL)

```python
def _check_mixed_ddl(sql_content: str) -> dict:
    """扫 SQL 内容检测是否含混合 DDL (CREATE/INSERT/UPDATE/DELETE + ALTER).
    
    Returns:
        {"ok": True} 全 ALTER 或全 CREATE/INSERT/UPDATE/DELETE → 允许
        {"ok": False, "error": str, "alter_count": int, "other_count": int,
         "types": list[str]} 混合 DDL → 拒绝 + 业务方必须拆单
    """
    if not sql_content:
        return {"ok": True}
    types_seen = set()
    for raw_stmt in sql_content.split(";"):
        # ... skip comments + empty
        first_word = cleaned.split()[0].upper()
        if first_word in ("ALTER", "CREATE", "INSERT", "UPDATE", "DELETE"):
            types_seen.add(first_word)
    has_alter = "ALTER" in types_seen
    has_other = bool(types_seen - {"ALTER"})
    if has_alter and has_other:
        return {
            "ok": False,
            "error": f"工单含混合 DDL (ALTER + {', '.join(other_types)}), 请拆分成独立工单...",
            "alter_count": 1,
            "other_count": len(other_types),
            "types": list(types_seen),
        }
    return {"ok": True}
```

### 2. `sql_api/api_workflow.py` + `sql_api/serializers.py` — 后端兜底 + 前端检测字段

**a. `ExecuteCheck.post()`** (sql_api/api_workflow.py):
- SQL 检测时调 `_check_mixed_ddl`, 把结果注入 `mixed_ddl_check` context

**b. `ExecuteCheckResultSerializer`** (sql_api/serializers.py):
- 加 `mixed_ddl_check = serializers.JSONField(read_only=True)` 字段
- `to_representation()` 从 context 拿 `mixed_ddl_check`

**c. `WorkflowContentSerializer.create()`** (sql_api/serializers.py):
- 第一步 `from sql.views import _check_mixed_ddl`
- 调 `_check_mixed_ddl(sql_content)`, `ok=False` → `raise ValidationError({"errors": error})`
- **即使前端绕过 disable 按钮, 后端也 reject**

### 3. `sql/templates/sqlsubmit.html` — 前端检测回调
- SQL 检测回调加 `mixed_ddl_check` alert (跟 cross_db / pk_conflict 一样的红框样式)
- 加 `hasBlockError` 逻辑, mixed → 红框 + 阻止提交按钮
- 按钮文案按错误优先级: "请先拆分工单 (ALTER 与 CREATE 不能混合)" > "请先修复跨库" > "请先修复 PK 冲突"

```javascript
// 3. v1 优化: 混合 DDL 检测 alert
$("#mixed-ddl-alert-v1").remove();
if (result.mixed_ddl_check && !result.mixed_ddl_check.ok) {
    var mixedDdlTypes = (result.mixed_ddl_check.types || []).join(' + ');
    var mixedDdlHtml = '<div class="alert alert-danger" id="mixed-ddl-alert-v1" ...>...
        <strong style="font-size:16px;color:#5a3a3a;">⚠️ 工单含混合 DDL (v1 优化)</strong>
        <div>类型: <strong>ALTER + CREATE</strong></div>
        <div>工单含混合 DDL ..., 请拆分成独立工单: CREATE/INSERT/UPDATE/DELETE 单独提交, ALTER 单独提交</div>
    ...
    $("#inception-result").before(mixedDdlHtml);
    hasBlockError = true;
}
// 4. 阻止提交按钮 (按错误优先级显示文案)
if (hasBlockError) {
    var blockMsg = "请先修复跨库/PK 冲突";
    if (result.mixed_ddl_check && !result.mixed_ddl_check.ok) {
        blockMsg = "请先拆分工单 (ALTER 与 CREATE 不能混合)";
    } else if (result.cross_db_check && !result.cross_db_check.ok) {
        blockMsg = "请先修复跨库";
    } else if (result.pk_conflict_check && !result.pk_conflict_check.ok) {
        blockMsg = "请先修复 PK 冲突";
    }
    $('#btn-submitsql')....prop("disabled", true).text(blockMsg);
} else {
    $('#btn-submitsql')....prop("disabled", false).text("提交");
}
```

## 演练 8/8 PASS (`scripts/_w3_v1_mixed_ddl_drill.py`)

```
Case 1 (纯 ALTER): ok=True ✅
Case 2 (纯 CREATE): ok=True ✅
Case 3 (ALTER + CREATE): ok=False types=['ALTER', 'CREATE'] ✅
Case 4 (wf#4841 实战 4 CREATE + 4 ALTER): ok=False types=['ALTER', 'CREATE'] ✅
Case 5 (USE + ALTER): ok=True (USE 跳过) ✅
Case 6 (ALTER + INSERT): ok=False types=['ALTER', 'INSERT'] ✅
Case 7 (空 SQL): ok=True ✅
Case 8 (注释 + ALTER + 注释 + CREATE): ok=False ✅
```

## 演练后端兜底 reject (DBA 一条龙)

直接 POST `/api/v1/workflow/` mixed DDL 工单:
```
=== POST mixed DDL 工单 ===
  status: 400
  body: {"errors": "工单含混合 DDL (ALTER + CREATE), 请拆分成独立工单..."}
  ✅ 后端兜底 reject OK
```

## 部署 (DBA 一条龙, 不动生产任何数据和表结构)

### 134 dev
- 推 4 文件 (sql/views.py + sql/templates/sqlsubmit.html + sql_api/api_workflow.py + sql_api/serializers.py)
- `systemctl restart archery-prod-gunicorn.service` (业务中断 ~10 秒)
- HTTP 200 + 8 case 演练 PASS

### 110 prod
- 推 5 文件 (134 dev 4 个 + scripts/_w3_v1_mixed_ddl_drill.py 演练脚本)
- 手动 reload master (kill -TERM 77927 + setsid nohup 启动新 master 9387)
- HTTP 200 + 8 case 演练 PASS

## 实战新发现 (2 条, 跨项目可复用)

### 1. 跨项目工单系统: "提醒"升级"禁止"必须前后端双层防护
跨项目写 SQL 平台 / 工作流系统, 检测到必拆单的混合 DDL 时, 不止加 banner 提醒, 还要:
- 前端: 提交按钮 disable + 文案明确 ("请先拆分工单...")
- 后端: serializer.create() 第一步 raise ValidationError (即使前端绕过, 也兜底 reject)
- 实战踩坑: 9/16 wf#4841 业务方工单 4 CREATE + 4 ALTER, 旧提醒无效, 业务方还是提交, 工单显示"成功" 但实际 7/8 失败
- 修法: v1 升级双层防护, 演练 8/8 PASS

### 2. SQL 解析复用 _detect_non_alter 思路 (split + skip comments + first word token)
跨项目 SQL 检测/解析时, 复用简单可靠的方法:
- 按 `;` 分割 SQL
- 跳过注释行 (`--` 开头)
- 取首 token (uppercase) 判断类型
- 实战踩坑: 9/17 v1 _check_mixed_ddl 复用了 _detect_non_alter 的 SQL 解析思路
- 修法: 复用思路而不是全正则, 简单可靠, 处理 8 个 case 都 PASS

## 改动文件清单

### Modified (4)
- `sql/views.py` (+44 行, _check_mixed_ddl 函数)
- `sql_api/api_workflow.py` (+14 行, ExecuteCheck.post 调 _check_mixed_ddl + 注入 context)
- `sql_api/serializers.py` (+13 行, ExecuteCheckResultSerializer 加 mixed_ddl_check 字段 + WorkflowContentSerializer.create 加 mixed_ddl backend 兜底)
- `sql/templates/sqlsubmit.html` (+33 行, 检测回调加 mixed_ddl alert + 阻止提交按钮)

### New (1)
- `scripts/_w3_v1_mixed_ddl_drill.py` (8 case 演练)

## 关联 commit / 实战接龙

- 关联 commit: `c4ca623` (DBA-bug-9) + `4b1e415` (DBA-bug-9.5) + `d3264eb` (v0 阶段 2)
- 关联事件: DBA-bug-9 wf#4841 实战 + 9/17 13:06 阿达叔叔拍板备忘
- 关联实战接龙: 9/11-9/17 21 事件
- 关联实战新发现: 9/17 13:10 DBA-bug-9.5b (detail 警告守卫) — 同一个用户截图触发

## changelog

`docs/changelogs/2026-09-17_v1-mixed-ddl-block-submit.md` (本文件)

@ 2026-09-17 13:50 @ mavis