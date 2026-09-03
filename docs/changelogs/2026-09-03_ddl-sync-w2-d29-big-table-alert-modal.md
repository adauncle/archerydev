# v0.3.x 字段 diff D29: 大表 DDL alert 弹窗化 (D28 验证)

> 日期: 2026-09-03 17:58
> 阶段: v0.3.x 字段 diff UX 验证
> 模块: `sql/templates/sqlsubmit.html` (无新代码)
> 关联: 9/3 17:54 业务方反馈 (110 prod /editsql/ 大表 alert 在 inline, 想弹窗)

## 背景

业务方演练 110 prod `/editsql/` 页 (截图):
- 提交 `ALTER TABLE accesscard_accountcardinfo ...` 工单
- 触发大表 DDL alert (行数 706407 / 数据大小 166.8 MB, 阈值 100000 行 或 100 MB)
- 业务方反馈: 检测到是大表, **弹窗里把大表的 gh-ost 建议也加上去展示** (之前在 inline 区域, 业务方想看弹窗)

## 症状

业务方截图标 110 prod `/editsql/` 页面 "检测结果" panel 里的 inline alert:
```
⚠ 检测到 accesscard_accountcardinfo 是大表 DDL
  行数 706407 / 数据大小 166.8 MB (阈值: 100000 行 或 100 MB)
  大表 DDL 走原路径"立即执行"会**锁表** (业务写入阻塞几秒到几分钟)。
  **强烈建议在上方勾选"启用 gh-ost 无锁变更"** —— 提交后自动走 5 道预检, gh-ost 走完无需锁表。
```

业务方期望: 这个大表 alert + gh-ost 建议**跟字段 diff 一起**在弹窗里展示 (D28 弹窗化).

## 根因

实际上 110 prod 还没推 D28 (commit 3a59e8b 是 17:35 实战, 110 prod 推 110 在 D28 之后), 
所以 110 prod 看到的是老 sqlsubmit.html (字段 diff + 大表 alert 都在 inline).

D28 实战时 (`/editsql/` 字段 diff 弹窗化, commit 3a59e8b), 我已经写了:
- `bigTableAlertHtml` 拼接到 `html` 变量 (line 897)
- `html` 写到 `$box.html(html)` (line 908)
- `$box = $("#column-diff-modal-body")` (D28 改的)
- `$('#columnDiffModal').modal('show')` (D28 自动弹窗)

即 **D28 实战时已经把大表 alert 集成到 modal body**, 业务方推 110 prod 后演练大表 DDL 就会看到弹窗顶部有大表 alert + gh-ost 建议.

## 验证 (9/3 17:58 134 dev 演练)

`scripts/_archive/_d29_verify_modal.py` 演练 6 项关键检查:

演练结果 (中文乱码是 PowerShell GBK 终端显示, 不是数据问题):
```
[OK] bigTableAlertHtml 拼接到 html 变量
[OK] renderColumnDiff $box 指向 modal body
[OK] fetchColumnDiff success 后自动 modal show
[OK] Modal 元素存在
[OK] modal body 容器存在
[OK] gh-ost 建议文案在源码 (bigTableAlertHtml 源代码)
```

**D29 实战结论: D28 实战时已经实现, 不需要新代码**

## 134 dev 演练限制

134 dev 演练时大表 DDL 验证有局限:
- `accesscard_accountcardinfo` (用户截图里那张 70 万行大表) 在 134 dev **不存在** (D27 演练踩坑)
- 134 dev 业务库 `hly_accesscard` 全部 11 张表都是 0 行 (演练环境是空的)
- 真实大表演练只能在 110 prod 推 D28 后做 (业务方演练 wf 类似工单)

## 改动文件

**无新代码改动**。D29 实战只是**确认** D28 已经实现.

## 同源 entry

- 8/13 v0.3.x 大表 DDL 防呆 (SQL 提交页版) - 9/3 D28 实战时 bigTableAlertHtml 已经拼接到 inline 区域, D29 验证已搬到 modal body
- 8/24 v0.3.x 字段 diff 模态框 8/24 fix
- 8/26 v0.3.x 字段 diff inline 区域 (commit 0a04775)
- 9/3 D22-D27 实战链路
- 9/3 D28 /editsql/ 字段 diff 弹窗化 (commit 3a59e8b) - D29 验证 D28 已经把 bigTableAlertHtml 拼接到 modal body

## D29 实战新发现 (跨项目可复用, 3 条)

1. **D28 实战时 bigTableAlertHtml 已拼接到 modal body** (D29 实战新发现) - D28 改 renderColumnDiff $box 指向 modal body 时, bigTableAlertHtml 早就拼接到 html 变量 (line 897), 一次搬迁 modal body 自动集成
2. **134 dev 演练限制 (D27 实战踩坑复用)** (D29 实战新发现) - 134 dev 演练环境是空的, 大表演练只能 110 prod 推完后业务方演练. 实战必查 pymysql SHOW TABLES 找真实表, 演练用真实表演练才靠谱
3. **D29 业务方反馈是预期错配 (D23 业务方预期错配复用)** (D29 实战新发现) - 业务方看到 110 prod 旧版 inline, 反馈"想弹窗", 实际推 D28 之后就弹窗, 业务方预期跟 D28 实现一致

## D29 实战踩坑 (2 条)

1. **D29 PowerShell GBK 终端 print unicode escape 字符报错** (D21 实战踩坑 3 复用) - \u2713 字符 GBK 不能 encode, 改用 ASCII "[OK]" 替代
2. **D29 134 dev 没大表演练** (D27 实战踩坑 复用) - accesscard_accountcardinfo 134 dev 不存在, 演练 1 ok=False. 改演练 134 dev 真实存在的 11 张 accesscard_* 表 (但都是 0 行, 演练不出 big_table_alert), 改成"演练源码路径确认"代替

## 待办

1. 推 110 prod (D22-D28 攒齐 9 文件 + 1 migration, D29 验证 D28 已经集成大表 alert):
   - 推完 110 prod, 业务方演练 1 个大表 DDL 工单 (如 accesscard_accountcardinfo)
   - 验证弹窗顶部有大表 alert + gh-ost 建议
2. 110 prod 业务方演练 wf 类似工单 + 大表 DDL 工单 验证 D28 + D29 实战生效

## D29 实战后 W2 状态

D6 → D7 → ... → D27 → D28 → **D29 验证 D28 大表 alert 弹窗化** (无新代码)
