# D38 续 10: 一键复制 modal 加"复制"按钮 (user gesture) (2026-09-09 18:00)

## 业务方反馈 (9/9 17:56)
- D38 续 9 (17:45) 推的 showCopyModal 弹了
- 但 modal 里自动 select 没生效, 业务方按 Ctrl+C 时 focus 还在原页面
- 实际粘贴得到: **整个页面文字** (menu, 表单, 检测结果, 工单日志, 重复 31 次的"马克群151009...")
- 而不是 SQL 文本

## 根因
- D38 续 9 的 `setTimeout 50ms` 自动 focus + select 在业务方按 Ctrl+C 之前没生效
- 业务方按 Ctrl+C 时 focus 还在原页面 (不是 modal 内的 textarea)
- 浏览器 Ctrl+C 没选中文字时, **复制整个 body 文字** (不是标准行为, 但 Chrome/Edge 实际如此)
- 业务方得到的是整个 Archery SQL 提交页的 body 文字

## 修法: modal 加一个用户主动点击的"复制"按钮
**关键 insight**: `document.execCommand("copy")` 在 **user gesture** (用户点击/按键) 下不会静默失败. Chrome 95+ 静默失败是针对**自动触发的 copy** (无 user gesture). 

新设计:
1. modal 含可见 readonly textarea (用户可以自己手动 Ctrl+A + Ctrl+C)
2. **textarea 自动 select** (立即, 不 setTimeout)
3. **新增"📋 复制"按钮** - 用户点击 → focus + select + execCommand (user gesture 触发, Chrome 95+ 不会静默失败)
4. 按钮点击成功显示"✓ 已复制" (3 秒后恢复)
5. 关闭按钮保留

## 演练 PASS 计划
- 134 dev force_login 验证 modal 加载 + JS 函数正确
- 110 prod scp 推 + 重启 + 验证
- (无法自动验证剪贴板内容, 因为 Python 没法测浏览器手动操作)

## 改动 1 个文件
1. `sql/templates/sqlsubmit.html` (line 1018-1060) - 重写 showCopyModal 加"复制"按钮

## 实战新发现 (跨项目可复用, 1 条)
**modal 一键复制必用 user gesture 触发** (D38 续 10 实战新发现) - Chrome 95+ 对自动触发的 document.execCommand("copy") 静默失败, 但对**用户主动点击按钮触发**的 execCommand 正常工作. 跨项目做"一键复制"功能, 弹 modal 时不要 setTimeout 自动 select, 而是提供一个**用户主动点击的"复制"按钮**, 这样 execCommand 在 user gesture 下能 work

## 下次推 prod checklist 必加 1 条
**一键复制 modal 必提供"用户主动点击的复制"按钮** — Chrome 95+ 静默失败 execCommand 只针对**自动触发**的 copy, **user gesture 触发的 copy 正常 work**. 弹 modal 时不要 setTimeout 自动 select, 必须提供复制按钮让用户主动点

## W2 状态
D6 → ... → D37 → D38 → D38 补充 → D38 续 → D38 续 2 → D38 续 3 → D38 续 4 → D38 续 5 → D38 续 6 → D38 续 7 → D38 续 8 → D38 续 9 → **D38 续 10 (modal 加"复制"按钮 user gesture 触发, 进行中)**
