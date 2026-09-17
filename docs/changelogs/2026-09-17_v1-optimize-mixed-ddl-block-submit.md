# v1 优化备忘: 建表 + ALTER 混合工单禁止提工单

> **状态**: 待优化 (9/17 09:06 阿达叔叔拍板记下来)
> **关联**: DBA-bug-9 (c4ca623) + DBA-bug-9.5 (4b1e415) + v0 智能模式 (7ca2866 WIP)
> **优先级**: P2 (优化项, 不紧急)

---

## 现状

DBA-bug-9.5 (9/16 19:55 commit 4b1e415) 实现了:
- 前端 SQL 检测弹窗显示"建表跟 ALTER 混合, gh-ost 模式不支持, 请拆分" 警告 banner
- 但**只是提醒, 业务方仍能点 SQL 提交按钮提工单**
- 业务方实战可能忽略警告, 提交后才被 backend 拒 (UX 差)

---

## 优化方向 (9/17 09:06 阿达叔叔拍板)

**改成禁止模式**:
- 检测到工单含 CREATE TABLE + ALTER TABLE 混合 (或含 INSERT/UPDATE/DELETE)
- 前端:**SQL 检测弹窗红色 banner + "SQL 提交"按钮 disable (无法提工单)**
- 业务方必须拆分后才能提交

---

## 改造点 (待实施)

1. **`sql/templates/sqlsubmit.html`**:
   - 检测到 `window.__nonAlterData.has_non_alter === true` 时, **SQL 提交按钮 disable + 灰显**
   - 弹窗顶部加红色 banner: "检测到非 ALTER 语句 (CREATE/INSERT/UPDATE/DELETE), 必须拆分独立工单后才能提交"
   - 业务方修改 SQL (把非 ALTER 删掉) 后, 自动重新检测, 按钮恢复可点

2. **`sql/views.py` WorkflowSubmit.post**:
   - backend 兜底: 收到请求先扫 SQL, 含非 ALTER → return 400 "工单含非 ALTER, 必须拆分独立工单"
   - 不依赖前端 disable, 防止业务方绕前端直接 POST

3. **(可选) 表单字段 `gh_ost_mode` 加 "reject_mixed" 选项**:
   - 业务方/DBA 主动选 reject 模式, 整张工单只能含 ALTER, 含其他就拒
   - 默认还是 smart + 警告 (业务方主动决定)

---

## 关联

- **DBA-bug-9**: gh-ost 多 statement 工单支持 (c4ca623) — backend 已经 reject 含非 ALTER
- **DBA-bug-9.5**: 前端可见 bug 修复 (4b1e415) — 前端加了非 ALTER 警告, 但仅提醒
- **本备忘**: 把"提醒"升级为"禁止" (前端按钮 disable + backend 兜底)

---

## 拍板人: 阿达叔叔 (9/17 09:06)

> "建表+ALTER 混合工单检测,目前只是提醒, 但还可以提工单。要优化为提醒和禁止提工单,无法点击提交"

---

## 优先级说明

- 不紧急: 业务方实战可能一两周才碰一次
- 改进价值: 防止业务方忽略警告重复犯错 (跟 DBA-bug-9 wf#4841 业务方实战一样)
- 排期: 等 v0 智能模式 commit 完成后, 再开 v1 优化

---

## 关联实战接龙 (9/11-9/17, 17+ 事件)

- 9/11-9/16: DBA-bug-1..9.5 (16 commit)
- **9/17**: v0 智能模式 (5A 拍板) — 阶段 1/4 commit `7ca2866` (设计稿 + 模型)
- **9/17 待优化**: v1 禁止提交 (本备忘)