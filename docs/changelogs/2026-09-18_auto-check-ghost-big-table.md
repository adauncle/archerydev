# 2026-09-18 大表 DDL 自动勾选 gh-ost

> 阿达叔叔 9/18 15:35 截图反馈: 提交页大表 DDL 弹窗明确写"强烈建议勾选 gh-ost" 但 checkbox 实际空着.
> 业务方经常忘勾, 走原路径"立即执行" 锁表 5-10 分钟.
> 9/18 15:50 阿达叔叔要求: "检测到大表自动选中 ghost".

## 背景

提交页 sqlsubmit.html 3 处大表 alert 弹窗文案都写"强烈建议在上方勾选'启用 gh-ost 无锁变更'",
但 `enable_ghost` checkbox 默认未勾选 (`sqlsubmit.html:92-98` HTML 没有 `checked` 属性).

业务方实战踩坑:
- 9/16 wf#4841 (DBA-bug-9): 业务方 4 CREATE + 4 ALTER 工单, 大表混合, 业务方漏勾 gh-ost
- 9/17 wf#4849 (DBA-bug-10): CREATE INDEX 170 万行表, 业务方根本没注意 checkbox
- 9/18 阿达叔叔 110 prod 实测截图: checkbox 是空, 业务方手动勾

## 根因

1. 旧设计是"建议", 不是"自动" — 业务方主动权过大, 实战漏勾率高
2. `enable_ghost` checkbox 默认 unchecked, 没任何 JS 自动勾选逻辑
3. `gh_ost_mode` 下拉框默认 hidden, 业务方勾 checkbox 才滑出

## 修复

文件: `sql/templates/sqlsubmit.html` (1 文件)

### 1. 新增 `autoCheckGhostCheckbox(data)` 函数 (sqlsubmit.html:863)

```js
function autoCheckGhostCheckbox(data) {
    var bigTables = (data && (data.big_tables || (data.big_table_alert ? [data.big_table_alert] : []))) || [];
    var hasNonAlter = window.__nonAlterData && window.__nonAlterData.has_non_alter;
    if (bigTables.length > 0 && !hasNonAlter) {
        var $cb = $("#enable_ghost");
        if ($cb.length && !$cb.is(':checked')) {
            $cb.prop('checked', true).trigger('change');
            // 联动: trigger('change') 让 $("#div-gh-ost-mode").show() (v0 智能模式联动, line 1502 handler)
        }
    }
}
```

**触发条件**:
- ✅ 检测到大表 (bigTables.length > 0)
- ✅ 工单全 ALTER 类 (has_non_alter=false, 含 CREATE INDEX 9/17 已识别)
- ❌ 不触发: has_non_alter=true (工单含 CREATE/INSERT/UPDATE/DELETE, gh-ost 模式必拒)
- ❌ 不触发: 业务方已勾上 (避免重新触发)

### 2. 改 3 处文案 (sqlsubmit.html:822 / 846 / 1031)

| 旧 (❌)  | 新 (✅)  |
|----------|----------|
| 强烈建议在上方勾选"启用 gh-ost 无锁变更" —— 提交后自动走 5 道预检 | **已自动勾选 "启用 gh-ost 无锁变更"** (业务方可手动取消) —— 提交后自动走 5 道预检 |

### 3. 2 处调用 (sqlsubmit.html:952 + 965)

在 `doFetchColumnDiff` 的 success callback:
- `data.ok && data.big_table_alert` 分支 (line 952): 大表 + 字段变更都触发
- `!data.ok && data.big_table_alert` 分支 (line 965): 大表 + ADD INDEX/DROP INDEX 等非字段变更也触发

## 边界 (产品拍板 9/18 15:51)

| 场景                              | 自动勾选? | 备注                                                                                  |
|-----------------------------------|-----------|---------------------------------------------------------------------------------------|
| 大表 + 全 ALTER (含 CREATE INDEX) | ✅ 自动勾 | 业务方可手动取消, gh_ost_mode 下拉框自动滑出                                            |
| 大表 + 含 CREATE/INSERT/UPDATE/DELETE | ❌ 不勾   | 勾了必拒 (views.py:1049), 不自动勾; 大表警告仍弹, 但建议拆单                              |
| 大小表混合 (≥1 大表 + ≥1 小表)   | ✅ 自动勾 | smart 模式后端自动分流 (大表 gh-ost + 小表原生 ALTER)                                    |
| 没大表                            | ❌ 不勾   | checkbox 保持默认状态                                                                  |
| 业务方手动取消勾选 (后续再检测)   | ❌ 不重复勾 | `$cb.is(':checked')` 已为 false 才会触发, 已取消不重新勾上                              |

## 演练

演练脚本: `scripts/_w3_v0_auto_check_ghost_verify.py` (15 case, 10/10 静态 + 5/5 mock JS)

**134 dev 部署 (9/18 15:55)**:
- 推 sqlsubmit.html
- `systemctl restart archery-prod-gunicorn.service`
- HTTP 200 + grep "已自动勾选" × 3 ✅

**110 prod 部署 (9/18 15:58)**:
- 推 sqlsubmit.html + reload script
- pkill gunicorn + `--daemon --pid /tmp/gunicorn_110.pid` (systemd 仍 failed)
- source `.env` + export 7 个 CAS env vars
- HTTP 200 + grep "已自动勾选" × 3 ✅

## 实战新发现 (3 条入 MEMORY, 跨项目可复用)

1. **大表 DDL 防呆产品设计迭代: 强烈建议 → 自动勾选 (跨项目 SQL 审核平台实战)**: 跨项目写 SQL 提交平台/SQL 审核系统时, "强烈建议业务方勾选" 在实战里漏勾率高, 应该升级成"自动勾选 (业务方可手动取消)". 实战踩坑: 9/16 wf#4841 + 9/17 wf#4849 业务方都漏勾, 走原路径"立即执行" 锁表. 修法: 检测到大表 → 自动 prop('checked', true).trigger('change'), 文案从"强烈建议" 改"已自动勾选 + 业务方可手动取消"

2. **前端自动勾 checkbox + trigger('change') 让联动下拉框显示 (跨项目前端实战, 9/18 实战新发现)**: 跨项目写前端表单, 自动勾 checkbox 后必须 trigger('change') 让联动 UI (下拉框/隐藏域/提示文案) 显示. 实战踩坑: 9/18 大表自动勾 gh-ost 时, gh_ost_mode 下拉框还 hidden, 业务方看不到 smart/all_ghost 选项. 修法: $cb.prop('checked', true).trigger('change'), 让现有 onchange handler 执行 (#div-gh-ost-mode).show()

3. **has_non_alter 边界: 混合 DDL 不自动勾 (跨项目产品边界)**: 自动勾选 gh-ost 时, 工单含 CREATE/INSERT/UPDATE/DELETE 不要自动勾 (gh-ost 模式必拒). 实战踩坑: 业务方混合工单 (CREATE + ALTER) 提交, 自动勾上 gh-ost 后被后端拒, UX 更困惑. 修法: has_non_alter=true 不触发自动勾, 大表警告仍弹但文案改成"建议拆单"

## 关联

- 9/17 commit `0fe77bf` (动画版初版) — 文案"系统自动勾选" 是用户看到的"系统跳过"
- 9/18 commit `881392b` (动画版事实修正) — 修正为"业务方手动勾选"
- 9/18 本 commit (大表自动勾选功能) — 把"手动勾选" 升级成"自动勾选 (业务方可手动取消)"
- `docs/changelogs/2026-09-16_v0-gh-ost-smart-mode.md` (v0 智能模式)
- `docs/changelogs/2026-09-17_dba-bug-10-create-index-bypass-alter-check.md` (CREATE INDEX 识别)
- `docs/changelogs/2026-09-18_animated-facts-fix.md` (动画版事实修正)