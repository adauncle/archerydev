# 2026-09-18 daily-recap

> 9/18 全天 7 commit / 12 文件 / 累计 60 条实战新发现
> 主题: 月度宣讲 5 迭代 + 动画版事实修正 + 大表自动勾选 gh-ost 新功能

## 9/18 主题

**今天 3 条主线**:
1. **月度宣讲 5 版本迭代** (V1 5 大功能 → V2 6 大功能 → V3 4 场景 → V4 步骤版 → V5 动画版) — 用户驱动, 每次反馈都重做
2. **动画版事实错误修正** (`881392b`) — 4 处"系统自动勾选 gh-ost" 跟实际不符, 阿达叔叔 110 prod 截图发现
3. **大表 DDL 自动勾选 gh-ost 新功能** (`a2c6ab6`) — 弹窗从"建议"升级成"自动勾选 (业务方可手动取消)"

## 9/18 commit 链 (7 commit, 时间倒序)

```
a2c6ab6  17:23 feat(sqlsubmit): 大表 DDL 自动勾选 gh-ost (业务方可手动取消)
881392b  15:46 fix(docs): 动画版修正 4 处"系统自动勾选 gh-ost"事实错误
102fdeb  14:57 fix: 修 resetSlide_2 反模式调用 (重载 + push)
0fe77bf  14:55 docs: 6功能实战指南动画版 (Archery UI mockup + JS 时序控制 7 动画)
68416ae  14:18 docs: 6功能实战指南含操作步骤版 (9 slides, 场景+步骤+反馈三轴展开)
8b2741d  13:50 docs: 月度DBA宣讲 - 开发实战指南 4 场景 (场景驱动版, 替换产品介绍视角)
622603d  13:40 docs: 月度DBA宣讲 6 大新功能 (9/18 更新, 5→6 含 v0 + v1 + DDL-Sync-Bug-A + DBA-bug-10)
```

## 主线 1: 月度宣讲 5 版本迭代 (4 commit, 13:40-14:57)

### V1 (9/16) → V2 (9/18 `622603d`): 5 大功能 → 6 大功能

- 触发: 9/17 实战接龙产出 4 个新功能 (v0 gh-ost 智能 + v1 禁止混合 DDL + DDL-Sync-Bug-A 多 ALTER + DBA-bug-10 CREATE INDEX)
- 修法: 11 slides, 5 → 6 大功能, 时间线 9/11-9/18

### V2 → V3 (9/18 `8b2741d`): 产品视角 → 场景驱动

- 触发: 阿达叔叔反馈"产品介绍视角偏多, 想要开发实战"
- 修法: 7 slides, 按 4 场景驱动 (A 提交瞬间 / B 弹红框 / C 大小表混合 / D 历史库同步)

### V3 → V4 (9/18 `68416ae`): 场景驱动 → 场景+步骤

- 触发: 阿达叔叔反馈"要具体操作步骤, 业务方知道怎么用"
- 修法: 9 slides, 6 功能 × (场景 + 步骤 + 反馈) 三轴

### V4 → V5 (9/18 `0fe77bf` + `102fdeb`): 静态 → 动画

- 触发: 阿达叔叔反馈"要动画, 业务方感受流程"
- 修法: 9 slides, Archery UI mockup + JS 时序控制 7 动画
- 修 `resetSlide_2 && resetSlide_2()` 反模式 → 直接调用 `resetSlide_2()`

### 5 版本产出

| 版本 | 文件                                                            | 视角         | 关键设计                          |
|------|-----------------------------------------------------------------|--------------|-----------------------------------|
| V1   | `2026-09-16_月度DBA宣讲_5大功能_*.{md,html}`                    | 5 大功能     | 9/16 老版本, 5 个功能              |
| V2   | `2026-09-18_月度DBA宣讲_6大新功能_*.{md,html}`                  | 6 大功能     | 5→6 (加 v0 + v1 + DDL-Sync + DBA-bug-10) |
| V3   | `2026-09-18_开发实战指南_4场景_*.{md,html}`                     | 4 场景驱动   | A/B/C/D 4 场景                    |
| V4   | `2026-09-18_6功能实战指南_操作步骤版_*.{md,html}`               | 6 功能 + 步骤 | 场景+步骤+反馈三轴                |
| V5   | `2026-09-18_6功能实战指南_动画版.html`                          | 动画版       | Archery UI mockup + JS 时序       |

## 主线 2: 动画版事实错误修正 (1 commit, 15:46)

### 触发 (9/18 15:35 阿达叔叔 110 prod 实测截图)

- 大表 DDL 弹窗明确写"强烈建议在上方勾选'启用 gh-ost 无锁变更'"
- 但 checkbox 实际是空, 业务方要自己手动勾
- 动画版 4 处写"系统自动勾选 gh-ost" / "smart 自动选中", 跟实际行为不符

### 根因

- 9/18 写动画时, 把"弹窗强烈建议"和"业务方手动勾选"两个动作合并叙述为"系统自动勾选", 让动画节奏显得"系统很聪明"
- 实际代码 (`sqlsubmit.html:1388`) `enable_ghost: $("#enable_ghost").is(':checked')` 是读取不是写入
- smart 是字段默认值 + 下拉框默认, 不是"自动选中"

### 修法 (4 处全改, 不动功能)

| 位置 | 旧 (❌) | 新 (✅) |
|------|---------|---------|
| Slide 2 step 3 (字段 diff 弹窗) | 💡 系统自动勾选 gh-ost | 💡 弹窗强烈建议, 业务方手动勾选 |
| Slide 3 title/subtitle (v0 智能) | 系统自动帮你勾 gh-ost + 默认 smart 模式 | 业务方勾 gh-ost → smart 默认 |
| Slide 3 step 2 | ✓ 系统自动勾选 gh-ost | ✓ 业务方手动勾选 gh-ost |
| Slide 3 step 3 | smart 自动选中 | smart 是字段默认值 |
| Slide 8 subtitle/step 2 (CREATE INDEX) | 自动弹 + 自动勾 gh-ost | 自动弹 alert 对 (✓), 业务方手动勾 gh-ost |

## 主线 3: 大表 DDL 自动勾选 gh-ost (1 commit, 17:23)

### 触发 (9/18 15:35 阿达叔叔截图 → 15:50 要求"自动选中 ghost")

- 业务方实战漏勾率高: 9/16 wf#4841 (DBA-bug-9) + 9/17 wf#4849 (DBA-bug-10) 都漏勾
- 阿达叔叔要求: 把"建议"升级成"自动"

### 产品拍板 (9/18 15:51)

| 场景 | 行为 |
|------|------|
| 大表 + 全 ALTER (含 CREATE INDEX 9/17 已识别) | ✅ 自动勾 |
| 大表 + 含 CREATE/INSERT/UPDATE/DELETE | ❌ 不勾 (gh-ost 必拒) |
| 大小表混合 | ✅ 自动勾 (smart 模式后端自动分流) |
| 没大表 | ❌ 不动 |
| 业务方手动取消 | ❌ 不重复勾上 |

### 修法 (1 文件 sqlsubmit.html)

1. 新增 `autoCheckGhostCheckbox(data)` 函数 (line 863)
2. 3 处文案改"强烈建议在上方勾选" → "已自动勾选 '启用 gh-ost 无锁变更' (业务方可手动取消)"
3. doFetchColumnDiff success 加 2 处调用 (line 952 + 965)

### 演练 (10/10 静态 + 5/5 mock JS)

`scripts/_w3_v0_auto_check_ghost_verify.py`:
- 10 静态: 函数定义 / 判断逻辑 / trigger('change') / 3 处文案 / 2 处调用 / has_non_alter 边界 / onchange handler / 3 个渲染函数
- 5 mock JS: 大表+全ALTER / 大表+has_non_alter / 没大表 / 业务方手动取消 / 多张大表混合

### 部署 (DBA 一条龙)

| 环境    | 操作                                                                    | 结果                          |
|---------|-------------------------------------------------------------------------|-------------------------------|
| 134 dev | scp sqlsubmit.html + `systemctl restart archery-prod-gunicorn.service`  | HTTP 200 + grep "已自动勾选" × 3 ✅ |
| 110 prod | scp + pkill + `--daemon --pid /tmp/gunicorn_110.pid` + CAS env vars     | HTTP 200 + grep "已自动勾选" × 3 ✅ |

## 文件变更统计 (12 文件)

```
docs/changelogs/2026-09-18_animated-facts-fix.md           (5.3KB, 1 文件, 4 处修改)
docs/changelogs/2026-09-18_auto-check-ghost-big-table.md   (6.4KB, 1 文件)
docs/reports/2026-09-18_月度DBA宣讲_6大新功能_*.{md,html}  (V2 报告, 1 md + 1 html)
docs/reports/2026-09-18_开发实战指南_4场景_*.{md,html}      (V3 报告, 1 md + 1 html)
docs/reports/2026-09-18_6功能实战指南_操作步骤版_*.{md,html} (V4 报告, 1 md + 1 html)
docs/reports/2026-09-18_6功能实战指南_动画版.html           (V5 报告, 9 slides, JS 时序)
sql/templates/sqlsubmit.html                                (1 文件, 1 函数 + 3 文案 + 2 调用)
scripts/_w3_v0_auto_check_ghost_verify.py                   (10/10 静态 + 5/5 mock JS 演练)
scripts/_reload_110_auto_check_ghost.sh                     (110 prod gunicorn reload)
```

## 9/18 实战新发现 (4 条入 MEMORY, 累计 60 条)

### 动画版事实修正 (1 条, `881392b`)

1. **docs 事实陈述不能为"好看"而简化, 业务流程描述要严格对应真实代码逻辑 (跨项目 docs 实战, 9/18 实战新发现)**:
   - 写演示文稿 / 操作指南 / 培训材料时, "系统自动" / "无需操作" / "自动选中" 这种词必须 grep 业务代码确认真有自动逻辑才能用
   - 实战踩坑: 9/18 写动画时为了节奏"显得智能", 把"弹窗强烈建议"和"业务方手动勾选"合并成"系统自动勾选", 阿达叔叔 110 prod 实测截图才发现
   - 修法: 每用一次"自动" / "无需", 都 grep 代码确认 (enable_ghost 是读取不是写入 → 不算"自动")

### 大表自动勾选 gh-ost (3 条, `a2c6ab6`)

2. **大表 DDL 防呆产品设计迭代: 强烈建议 → 自动勾选 (跨项目 SQL 审核平台实战, 9/18 实战新发现)**:
   - 跨项目写 SQL 提交平台/SQL 审核系统时, "强烈建议业务方勾选" 在实战里漏勾率高, 应该升级成"自动勾选 (业务方可手动取消)"
   - 实战踩坑: 9/16 wf#4841 + 9/17 wf#4849 业务方都漏勾, 走原路径"立即执行" 锁表
   - 修法: 检测到大表 → 自动 `prop('checked', true).trigger('change')`, 文案从"强烈建议" 改"已自动勾选 + 业务方可手动取消"

3. **前端自动勾 checkbox + trigger('change') 让联动下拉框显示 (跨项目前端实战, 9/18 实战新发现)**:
   - 跨项目写前端表单, 自动勾 checkbox 后必须 trigger('change') 让联动 UI (下拉框/隐藏域/提示文案) 显示
   - 实战踩坑: 9/18 大表自动勾 gh-ost 时, gh_ost_mode 下拉框还 hidden, 业务方看不到 smart/all_ghost 选项
   - 修法: `$cb.prop('checked', true).trigger('change')`, 让现有 onchange handler 执行 `$("#div-gh-ost-mode").show()`

4. **has_non_alter 边界: 混合 DDL 不自动勾 (跨项目产品边界, 9/18 实战新发现)**:
   - 自动勾选 gh-ost 时, 工单含 CREATE/INSERT/UPDATE/DELETE 不要自动勾 (gh-ost 模式必拒)
   - 实战踩坑: 业务方混合工单 (CREATE + ALTER) 提交, 自动勾上 gh-ost 后被后端拒, UX 更困惑
   - 修法: `has_non_alter=true` 不触发自动勾, 大表警告仍弹但文案改成"建议拆单"

## 9/18 文件/数据汇总

- **commit**: 7 个 (1 daily-recap 待 commit + 5 docs 宣讲迭代 + 1 fact fix + 1 大表自动勾选新功能)
- **文件**: 12 个修改 (8 docs 报告/讲义 + 1 sqlsubmit.html + 3 新建脚本/changelog)
- **行数**: +4859 行 (含 5 份宣讲报告)
- **MEMORY 新发现**: 4 条 (累计 60 条)
- **134 dev + 110 prod reload**: 各 1 次 (1 文件 sqlsubmit.html)

## 9/18 vs 9/17 对比

| 维度       | 9/17 (实战接龙 + daily-recap) | 9/18 (宣讲迭代 + 事实修正 + 新功能) |
|------------|--------------------------------|-------------------------------------|
| commit 数  | 8 (7 实战 + 1 daily-recap)     | 7 (5 宣讲 + 1 fact fix + 1 新功能)  |
| 主线       | 7 实战接龙 (v0/v1/DDL-Sync/DBA-bug-10 全闭环) | 月度宣讲 5 迭代 + 1 fact fix + 1 新功能 |
| 新发现     | 24 条 (大表 / CREATE INDEX / e2e mock) | 4 条 (docs 事实 / 自动勾选 UX / trigger 联动 / has_non_alter) |
| MEMORY 累计 | 56 条                          | 60 条                               |
| 部署       | 134 dev 6 reload + 110 prod 5 reload | 134 dev 1 reload + 110 prod 1 reload |

## 9/18 跨日关联 (9/11-9/18 周累计)

- **9/11-9/15 11 事件** (DBA-bug-1 ~ DBA-bug-7) — 入档 v0.1.x 系列
- **9/16 6 事件** (W3 + DBA-bug-8 + DBA-bug-9 + DBA-bug-9.5 + v0 stage 1 + 9.5b 备忘)
- **9/17 8 事件** (v1 备忘 + v0 stage 2 + 9.5b 修复 + v1 禁止 + DDL-Sync-Bug-A Step 1+2 + DDL-Sync-Bug-A 完整落地 + DBA-bug-10 CREATE INDEX 修复 + DBA-bug-10 column_diff 端点补充修复)
- **9/18 7 事件** (动画版 4 迭代 + 1 事实修正 + 本 daily-recap + 大表自动勾选 gh-ost)
- **总**: 32 事件, 26 commit, 80+ files, +14768/-688 行, 60 条 MEMORY

## 9/18 残留 (下次再做)

无 — 今天的 7 commit 都闭环了, 大表自动勾选 gh-ost 新功能已部署 134 dev + 110 prod 实战可测.

## 月度宣讲 (V5 动画版) 实战状态

- 阿达叔叔 9/18 17:30 左右浏览器实战测过 V5 动画版, 反馈"动画节奏 OK, 但要修动画版里的事实错误" → 9/18 15:46 修正 (`881392b`)
- 月度宣讲定稿: V5 动画版 (Archery UI mockup + JS 时序) — 9/18 收尾

## 关联

- 9/16 commit `fda887c` (W3 跨库检测 regex finditer 修复)
- 9/16 commit `c65c93e` (W3 跨库 SQL 检测 + INSERT 主键冲突检测) — D36 入档
- 9/17 commit `fe77c14` (DDL-Sync-Bug-A 完整闭环)
- 9/17 commit `4119838` + `2884b69` (DBA-bug-10 CREATE INDEX 修复)
- 9/17 commit `ad61b3b` (9/17 daily-recap)
- 9/18 commit `622603d` / `8b2741d` / `68416ae` / `0fe77bf` / `102fdeb` (月度宣讲 5 迭代)
- 9/18 commit `881392b` (动画版事实修正)
- 9/18 commit `a2c6ab6` (大表自动勾选 gh-ost)