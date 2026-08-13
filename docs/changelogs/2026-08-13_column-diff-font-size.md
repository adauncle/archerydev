# 2026-08-13 字段 diff 检测 UI 调大字号

## 业务背景

8/13 用户反馈, 字段变更检测弹窗 (详情页 modal + SQL 提交页 inline) 字号偏小 (11-12px),
     看着累。要求调大一点。

## 修法

改 2 个文件, 6 个字号档位统一调大 2-3px:

| 元素 | 原字号 | 新字号 |
|------|--------|--------|
| 风险标签 (高/中/低) | 11px | 13px (padding 2x8 → 3x10) |
| 表格整体 | 12px | 14px (padding 8 → 10) |
| 改前/改后代码 (monospace) | 11px | 13px (padding 1x4 → 2x6) |
| 提示文字 | 11px | 13px |
| 建议标题 | 12px | 14px |
| SQL 代码块 (monospace) | 11px | 13px |
| 摘要 banner | 13px | 15px (padding 10x14 → 12x16) |
| SQL 提交页 strong 标题 | 13px | 15px |
| SQL 提交页表名 | 12px | 13px |

涉及文件:
- `sql/templates/detail.html` (line 850-920, `renderColumnDiffModal` 函数)
- `sql/templates/sqlsubmit.html` (line 710-786, `renderColumnDiff` 函数)

## 演练

不需要演练 (纯前端样式调整, 0 业务逻辑改动)。
用 oa_tester_1 / DBA 用户浏览器手验字段 diff 弹窗:
- 详情页 `/detail/<wf_id>/` 大表 alert → "字段 diff" 按钮 → 弹窗
- SQL 提交页 `/sqlsubmit/` 改前后 → 字段 diff 区域

## 验证清单

- [x] 134 dev sync + gunicorn reload 完毕
- [ ] **用户浏览器手动验收** (详情页 / SQL 提交页 都看一遍)

## 同源 entry

- 8/12 commit `1f32976` (v0.3.x 字段 diff 检测) — 初版, 字号偏小
- 8/12 commit `cd683f9` (字段 diff mockup HTML v2)
- 8/13 commit `fba0564` (字段 diff 补全 SQL 一键复制)
