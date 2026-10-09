# 2026-10-09 DBA-bug-15: gh-ost 模式禁用纯非 ALTER 工单

## 背景

10/8 18:32 阿达叔叔 (110 prod 截图) 反馈: `你好，马克群` 登录的 SQL 上线页
含 CREATE TABLE 工单 (`CREATE TABLE hly_accesscard.accesscard_hnfr_infos`),
底部 "启用 gh-ost 无锁变更" checkbox **仍然可点**,但 gh-ost 必拒
(`gh-ost 模式仅支持 ALTER TABLE`,后端 `_enable_ghost_for_workflow` 9/16
DBA-bug-9 已经有 reject 逻辑)。

业务影响: 业务方点了 checkbox → 提交 → 后端 reject 报"工单不含 ALTER" →
业务方一脸懵 (UX 误导,以为 gh-ost 模式能跑)。应该直接在 UX 层 disable
checkbox + 警告,让业务方一眼明白。

## 方案

4 处变更:
1. `sql/extensions/ddl_gh_ost/views.py` `check_non_alter` 端点:
   响应新增 4 字段 `is_pure_alter` / `pure_non_alter` / `is_mixed` /
   `disable_gh_ost` + `block_reason`, `advice` 文案按状态分流
2. `sql_api/api_workflow.py` `WorkflowList` 端点:
   写 `enable_gh_ost=True` 前再次校验 SQL,纯非 ALTER 直接
   `raise serializers.ValidationError` 兜底 (防 curl / postman 绕过前端)
3. `sql/templates/sqlsubmit.html`:
   - 在 `#div-enable-ghost` 下方加 inline 警告 div
     (`#sqlsubmit-ghost-block-warning`),红紫色 + 🚫 icon,默认隐藏
   - 新增 `applyGhostCheckboxState(naData)` JS 函数: 按 `naData.disable_gh_ost`
     决定是否 disable checkbox + 灰化 + 改警告文案 (分 pure_non_alter / mixed)
   - 新增 `debouncedUpdateGhostState()` JS 函数: 500ms debounce → AJAX
     调 `/gh_ost/check_non_alter/` → `applyGhostCheckboxState(naData)`
   - `editor.on('change')` 钩子里加 `debouncedUpdateGhostState()`
     触发实时检测
   - `fetchColumnDiff` AJAX success/error 钩子里加
     `applyGhostCheckboxState(naData/null)` (用户点 SQL 检测时同步)
4. `scripts/_w3_dba_pure_non_alter_drill.py`: 4+2 case drill,验证
   4 字段响应 + /submitsql/ HTML 6 项字符串 + 老工单回归

## 4 处变更细节

### 1. check_non_alter 端点 4 字段

```python
is_pure_alter = alter_count > 0 and len(non_alter_stmts) == 0
pure_non_alter = alter_count == 0 and len(non_alter_stmts) > 0
is_mixed = alter_count > 0 and len(non_alter_stmts) > 0
disable_gh_ost = pure_non_alter or is_mixed
if pure_non_alter:
    block_reason = "pure_non_alter"
elif is_mixed:
    block_reason = "mixed"
else:
    block_reason = ""
```

- `pure_alter` (alter_count>0, non_alter_count==0) → gh-ost 可用
- `pure_non_alter` (alter_count==0, non_alter_count>0) → 整个工单不能 gh-ost
- `mixed` (alter_count>0, non_alter_count>0) → v1 已禁, 防御也禁
- `empty` (alter_count=0, non_alter_count=0) → 默认 enabled, 等用户输入
- `use_only` (USE only) → 等价 empty, enabled

### 2. api_workflow 兜底 reject

```python
if (request.data.get("enable_ghost")
        and getattr(settings, "CUSTOM_GH_OST_ENABLED", False)):
    from sql.extensions.ddl_gh_ost.views import _parse_all_statements
    _na_parsed = _parse_all_statements(full_sql or "")
    _na_alter = sum(1 for s in _na_parsed if s["stmt_type"] == "ALTER")
    _na_other = sum(1 for s in _na_parsed if s["stmt_type"] not in ("ALTER", "USE", "OTHER"))
    if _na_alter == 0 and _na_other > 0:
        raise serializers.ValidationError({
            "errors": (
                f"工单不含 ALTER TABLE 语句 (含 {_na_other} 条 "
                f"CREATE/INSERT/UPDATE/DELETE), gh-ost 模式不支持, "
                f"请改成 ALTER TABLE (或拆分成独立工单)"
            )
        })
```

防御: 前端 disable 之后,业务方可能直接调 API (curl / postman /
浏览器 DevTools) 绕过。后端必在 `wf.enable_gh_ost=True` 写入前再
检查一次 SQL 是否纯非 ALTER。

### 3. sqlsubmit.html inline 警告 + JS 联动

```html
<div id="sqlsubmit-ghost-block-warning"
     style="display: none; margin-top: -8px; padding: 10px 12px;
            background: rgba(176, 99, 103, 0.08);
            border: 1px solid rgba(176, 99, 103, 0.3);
            border-left: 4px solid #b06367; border-radius: 4px;">
    <i class="fa fa-ban" style="color: #b06367"></i>
    <strong id="sqlsubmit-ghost-block-title">⚠️ gh-ost 模式不可用</strong>
    <div id="sqlsubmit-ghost-block-detail">...</div>
</div>
```

```js
function applyGhostCheckboxState(naData) {
    var $cb = $("#enable_ghost");
    var $warn = $("#sqlsubmit-ghost-block-warning");
    if (!naData || !naData.disable_gh_ost) {
        // ALTER 路径: 恢复可用
        $cb.prop('disabled', false).css({cursor:'pointer', opacity:'1'});
        $warn.hide();
        return;
    }
    // pure_non_alter / mixed: disable + 警告
    $cb.prop('checked', false).prop('disabled', true).css({cursor:'not-allowed', opacity:'0.5'});
    $("#div-gh-ost-mode").hide();
    if (naData.pure_non_alter) {
        // 文案 1: 本工单 X 条全是 X 语句
    } else if (naData.is_mixed) {
        // 文案 2: X 条 ALTER + Y 条非 ALTER
    }
    $warn.show();
}

function debouncedUpdateGhostState() {
    // 500ms debounce, SQL 编辑器变就实时检测
}
```

### 4. drill 脚本

4+2 case 测 `check_non_alter` 字段 + 6 项 HTML 字符串 + 老工单回归:
- `pure_alter` / `pure_create_table` / `pure_create_index` / `mixed_alter_create`
- `empty` (期望 400) / `use_only` (期望 disable=false)
- 老工单回归: 134 dev 演练库跳过 / 110 prod 测 wf#4791/4792/4783 + wf#4848/4841

## drill 验证结果

### 134 dev (172.20.2.134, port 9003)

```
check_non_alter drill: PASS  (4+2 case 字段全对)
  [pure_alter]         OK (alter=1, non_alter=0, disable=False, reason='')
  [pure_create_table]  OK (alter=0, non_alter=1, disable=True, reason='pure_non_alter')
  [pure_create_index]  OK (alter=1, non_alter=0, disable=False, reason='')
  [mixed_alter_create] OK (alter=1, non_alter=1, disable=True, reason='mixed')
  [empty]              OK status=400
  [use_only]           OK (alter=0, non_alter=0, disable=False, reason='')

/submitsql/ html drill: PASS  (6 项字符串全在)
  [OK] inline warning div
  [OK] warning title elem
  [OK] warning detail elem
  [OK] applyGhostCheckboxState function
  [OK] debouncedUpdateGhostState function
  [OK] editor.on(change) hookup

regression: SKIP (134 dev 演练库, 跳过 wf 详情页回归)
ALL PASS
```

### 110 prod (172.20.2.110, port 9123)

```
check_non_alter drill: PASS  (4+2 case 字段全对)
  [pure_alter]         OK (alter=1, non_alter=0, disable=False, reason='')
  [pure_create_table]  OK (alter=0, non_alter=1, disable=True, reason='pure_non_alter')
  [pure_create_index]  OK (alter=1, non_alter=0, disable=False, reason='')
  [mixed_alter_create] OK (alter=1, non_alter=1, disable=True, reason='mixed')
  [empty]              OK status=400
  [use_only]           OK (alter=0, non_alter=0, disable=False, reason='')

/submitsql/ html drill: PASS  (6 项字符串全在)
  [OK] inline warning div
  [OK] warning title elem
  [OK] warning detail elem
  [OK] applyGhostCheckboxState function
  [OK] debouncedUpdateGhostState function
  [OK] editor.on(change) hookup

regression: PASS (5 个老工单详情页全 200)
  [wf#4791] OK status=200 (pure ALTER 9/9 字段 diff drill)
  [wf#4792] OK status=200 (pure ALTER mirror DDL-Sync drill)
  [wf#4783] OK status=200 (pure ALTER old 字段 diff drill)
  [wf#4848] OK status=200 (pure CREATE DBA-bug-9.5b drill, enable_gh_ost=False)
  [wf#4841] OK status=200 (mixed ALTER+CREATE DBA-bug-9 drill)

ALL PASS
```

## 真实浏览器验证 (10/9)

- 134 dev: 阿达叔叔在 134 dev 走 5 个 case (pure_alter / pure_create_table /
  pure_create_index / mixed / empty),checkbox 灰化 / 警告框 / 实时检测
  表现符合预期 ✅
- 110 prod: 阿达叔叔 11:33 在 http://prodarchery.ahggwl.com:9123/submitsql/
  验证 5 个 case,均表现符合预期 ✅ (gunicorn master pid 114079 起来了)

## 110 prod 部署同时修复的隐藏 critical 问题

(顺带记录, 跟本 bug 无关但同一 commit 部署触发了)

10/8 推 110 prod 时发现 systemd service `archery-v114-gunicorn.service`
从 **2026-09-08 16:47** 就在 `failed` 状态 (`code=exited, status=1/FAILURE`)。
9/22-10/8 期间业务没中断是因为 daemon 模式手动启的 gunicorn 在跑。
10/9 11:38 我 reload 时把残留也清掉了,导致 110 prod 实际上断了 ~1 小时。

根因两个:
1. `venv/bin/gunicorn` 的 shebang 指向旧 venv
   `/dbdata/archery_v114/venv/bin/python3.9` (旧 venv 缺新依赖)
2. systemd service 没设 `Environment=CAS_SERVER_URL`,
   worker 启动时 KeyError: 'CAS_SERVER_URL'

修法:
- shebang 改成 `/dbdata/archery_v114_c9236a0/venv/bin/python3.9`
- service 加 `Environment=CAS_SERVER_URL=https://cas.example.com`
  + `Environment=CAS_VERSION=3`
- `systemctl daemon-reload + reset-failed + restart`
- service 现在 `Active: active (running)`, master pid 114079, 5 workers

业务中断时长: 11:42 - 12:45 ≈ 1 小时 (其中推送 + 排查 shebang +
修 service env 共 ~25 分钟;剩余时间是诊断 + 写脚本)

老 venv backup: `venv/bin/gunicorn.bak_20261009_1791521126`
service 文件 backup: `/etc/systemd/system/archery-v114-gunicorn.service.bak_*`

## commit

- `feat(sqlsubmit)`: DBA-bug-15 纯非 ALTER 工单禁用 gh-ost checkbox + 警告
  - sql/extensions/ddl_gh_ost/views.py (+4 字段 + advice 分流)
  - sql_api/api_workflow.py (+ValidationError 兜底 reject)
  - sql/templates/sqlsubmit.html (+warning div + 2 JS 函数 + 2 处钩子)
- `chore(drill)`: 4+2 case drill 验证 + 老工单回归
  - scripts/_w3_dba_pure_non_alter_drill.py (新文件)
