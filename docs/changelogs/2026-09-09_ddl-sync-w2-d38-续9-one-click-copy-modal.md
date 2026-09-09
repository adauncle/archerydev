# D38 续 9: 一键复制静默失败终极兜底 - 弹 modal 让用户手动复制 (2026-09-09 17:45)

## 业务方反馈 (9/9 17:45 截图)
- D38 续 6 (16:00) 推的 `navigator.clipboard.writeText` + `document.execCommand("copy")` 降级
- 业务方点"一键复制"按钮, **按钮显示"已复制"** 但实际粘贴没东西
- 9/9 17:45 截图: 按钮变蓝色"已复制"但剪贴板空

## 根因
- 110 prod 是 HTTP context, `navigator.clipboard.writeText()` reject (需要 HTTPS 或 localhost)
- 降级 `document.execCommand("copy")` 在 Chrome 95+ **静默失败但返回 true**
  - Chrome 95+ 已废弃 `document.execCommand` API, 但保留返回值
  - 业务方点 button → fallback 调 execCommand → Chrome 静默拒绝 + 返回 true → onSuccess 触发 → 按钮变"已复制"
  - **用户实际粘贴: 剪贴板空**
- D38 续 6 实战新发现 #2 已经预见过这个, 但没想到 Chrome 95+ 静默失败这么彻底

## 修法: 终极兜底 - 弹 modal 让用户手动复制
不能依赖浏览器剪贴板 API, 必须给用户**主动手动复制**的入口:

1. 优先 `navigator.clipboard.writeText()` (HTTPS/localhost) → 失败 reject 走 2
2. 降级 `document.execCommand("copy")` + textarea (兼容老浏览器) → 失败走 3
3. **终极降级: 弹 modal 含可见 readonly textarea + 自动 select + 提示用户按 Ctrl+C / Cmd+C 复制**

modal 设计:
- 标题: "复制 SQL 文本"
- 内容: 大 textarea 含 SQL 文本, 自动全选
- 底部: "请按 Ctrl+C (Windows) / Cmd+C (Mac) 复制" 提示 + 关闭按钮
- 业务方手动复制完关闭 modal

## 演练 PASS 计划
- 134 dev force_login 演练 modal 能弹
- 110 prod 真 HTTP 演练 modal 弹
- (无法自动验证剪贴板内容, 因为 Python 没法测浏览器手动操作)

## 改动 1 个文件
1. `sql/templates/sqlsubmit.html` (line 919-981) - 加终极兜底 modal

## 实战新发现 (跨项目可复用, 1 条)
**一键复制 110 prod HTTP 业务方, 必须弹 modal 让用户手动复制** (D38 续 9 实战新发现) - 110 prod 是 HTTP 业务方, navigator.clipboard.writeText() reject + execCommand 静默失败, 任何 JS 自动 copy 都不靠谱. 跨项目做"一键复制"功能, 业务方 HTTP context 必须弹 modal + 可见 textarea + 自动 select + 提示手动 Ctrl+C, 不能只靠浏览器 API

## 下次推 prod checklist 必加 1 条
**一键复制 业务方 HTTP context 必弹 modal 兜底** — 跨项目做"一键复制"功能, 如果业务方是 HTTP (无 HTTPS / 无 localhost), navigator.clipboard.writeText + document.execCommand 两条都不靠谱, 必须弹 modal 含可见 textarea + 自动 select + 提示手动 Ctrl+C

## W2 状态
D6 → ... → D37 → D38 → D38 补充 → D38 续 → D38 续 2 → D38 续 3 → D38 续 4 → D38 续 5 → D38 续 6 → D38 续 7 → D38 续 8 → **D38 续 9 (一键复制终极兜底 - 弹 modal 让用户手动复制, 进行中)**
