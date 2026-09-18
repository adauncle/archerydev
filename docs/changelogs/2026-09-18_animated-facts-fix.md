# 2026-09-18 月度宣讲动画版事实错误修正

> 阿达叔叔 9/18 15:35 截图反馈 110 prod 实测:
> 大表 DDL 弹窗明确写 "强烈建议在上方勾选'启用 gh-ost 无锁变更'", 但 checkbox 实际是空,
> 业务方要自己手动勾. 动画版 4 处写"系统自动勾选 gh-ost" / "smart 自动选中", 跟实际行为不符.

## 背景

动画版 (`docs/reports/2026-09-18_6功能实战指南_动画版.html`) 9/18 17:48-18:50 由 commit `0fe77bf` / `102fdeb` 落地,
共 9 slides, Archery UI mockup + JS 时序控制 7 动画.

但 4 处文字描述与实际业务行为不符:

| 位置       | 原文案 (❌ 错)                                | 真实行为 (✅)                                                              |
|------------|-----------------------------------------------|-----------------------------------------------------------------------------|
| Slide 2 step 3 (字段 diff 弹窗) | 💡 系统自动勾选 gh-ost / 系统帮你自动勾选 ☑ | 弹窗明确说"强烈建议", checkbox 是业务方**自己勾的**                          |
| Slide 3 title/subtitle (v0 智能) | 系统自动帮你勾 gh-ost + 默认 smart 模式       | 业务方手动勾 checkbox, smart 是字段默认值, 业务方可改 all_ghost/all_native   |
| Slide 3 step 2                  | ✓ 系统自动勾选 gh-ost                          | 业务方看到大表警告后自己点 checkbox                                           |
| Slide 3 step 3                  | smart 自动选中                                 | smart 是字段默认值 + 下拉框默认, 业务方可改                                  |
| Slide 8 subtitle/step 2 (CREATE INDEX) | 自动弹大表 alert + 自动勾 gh-ost             | 自动弹 alert 对 (DBA-bug-10 修复), 但 gh-ost checkbox 还是业务方自己勾        |

## 根因

- 9/18 写动画时, 把"弹窗强烈建议"和"业务方手动勾选"两个动作合并叙述为"系统自动勾选",
  为了让动画节奏显得"系统很聪明"
- 实际代码 (`sql/templates/sqlsubmit.html:1388`) `enable_ghost: $("#enable_ghost").is(':checked') || false`
  是**读取**业务方勾选状态, 没有任何自动勾选 JS 逻辑
- smart 默认值是 gh_ost_mode 字段默认值 (`views.py:388 gh_ost_mode = getattr(workflow, "gh_ost_mode", "smart") or "smart"`),
  + 下拉框默认选项, 业务方可改, 不是"自动选中"

## 修复

文件: `docs/reports/2026-09-18_6功能实战指南_动画版.html` (1 文件, 4 处修改)

| 位置       | 新文案 (✅)                                                                                  |
|------------|----------------------------------------------------------------------------------------------|
| Slide 2 step 3 | 💡 弹窗强烈建议, 业务方手动勾选 / 弹窗里明确写"强烈建议在上方勾选'启用 gh-ost 无锁变更'", 但 checkbox 是业务方自己勾的 (系统不替业务方决定) |
| Slide 3 title | ② 大表无锁 + v0 智能 — 业务方勾 gh-ost → smart 默认                                            |
| Slide 3 subtitle | 你的表是 170 万行 / 865 MB, 业务方手动勾 "启用 gh-ost" → 模式默认 smart                          |
| Slide 3 step 2 | ✓ 业务方手动勾选 gh-ost / 左侧 UI 模拟: 业务方看到大表警告后, 自己点 ☑ 启用 gh-ost 无锁变更 (checkbox 是业务方的责任, 系统不替勾) |
| Slide 3 step 3 | 🎯 gh-ost 模式: smart (字段默认值) / 勾上 checkbox 后模式选择器才滑出, smart 是默认值 (业务方可改 all_ghost / all_native) |
| Slide 8 subtitle | CREATE INDEX 大表 → 自动弹大表 alert, 业务方手动勾 gh-ost                                       |
| Slide 8 step 2 | ✓ 业务方手动勾选 gh-ost / 左侧 UI 模拟: 业务方看到大表警告后, 自己点 ☑ 启用 gh-ost 无锁变更       |

## 验证

- 134 dev / 110 prod 实测 (阿达叔叔 9/18 截图):
  - 大表 DDL 检测 → 弹窗 "强烈建议在上方勾选'启用 gh-ost 无锁变更'"
  - checkbox 默认空 → 业务方手动点 → 才勾上 → 再点 SQL 提交
- 4 处文案与代码 + 截图 + 弹窗实际行为全部一致

## 实战新发现 (1 条, 跨项目通用)

**docs 事实陈述不能为"好看"而简化, 业务流程描述要严格对应真实代码逻辑 (跨项目 docs 实战)**:
- 跨项目写演示文稿 / 操作指南 / 培训材料时, "系统自动" / "无需操作" / "自动选中" 这种词,
  必须 grep 业务代码确认真有自动逻辑才能用
- 实战踩坑: 9/18 写动画时为了让节奏"显得智能", 把"弹窗强烈建议"和"业务方手动勾选" 合并成
  "系统自动勾选", 阿达叔叔 110 prod 实测截图才发现错
- 修法: 写 docs/reports 时, 每用一次"自动" / "无需", 都 grep 代码确认:
  - `enable_ghost: $("#enable_ghost").is(':checked')` 是读取不是写入 → 不算"自动"
  - `gh_ost_mode = getattr(..., "smart") or "smart"` 是默认值不是"自动选中"

## 关联

- 9/18 commit `0fe77bf` (动画版初版, 引入事实错误)
- 9/18 commit `102fdeb` (修 resetSlide_2 反模式, 仍保留事实错误)
- 9/17 commit `d3264eb` (v0 gh-ost 智能模式阶段 2 完整落地, 真实代码)
- `docs/changelogs/2026-09-16_v0-gh-ost-smart-mode.md` (v0 智能模式功能)