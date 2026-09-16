# 📣 业务方实测通知：跨库 SQL 检测 + INSERT PK 冲突检测 已上线 (W3)

> 马克群发，麻烦转业务方

---

## 🎉 W3 上线完成（阿达叔叔 9/16 拍板 DBA 一条龙全包）

Archery 现在有两个新的 SQL 检测能力，**业务方重新提交 wf#4821 + wf#4834 实测**：

### 1️⃣ 跨库 SQL 检测
- 一个工单里**只能变更一个库**（业务方 select 哪个库就改哪个库）
- 之前 wf#4821 业务方 select `hly_accesscard` 但 SQL 改 `hly_usercenter.accesscard_user_vehicle_change`，跨库漏检测
- 现在：检测到跨库 → 红框 alert + **提交按钮 disabled + 文案"请先修复跨库/PK 冲突"**

### 2️⃣ INSERT 主键冲突预检
- 提交时就查 DB 现有 PK 值，不再等执行到第 10 条才发现冲突
- 之前 wf#4834 业务方 INSERT 15 条 (id 302-311)，其中 306/307/308/309 重复
- 现在：检测到 PK 冲突 → 红框 alert + **提交按钮 disabled + 文案"请先修复跨库/PK 冲突"**

---

## 📋 业务方实测 2 步

1. **打开** `http://prodarchery.ahggwl.com:9123/submitsql/`
2. **重新提交** wf#4821 / wf#4834 的 SQL：
   - wf#4821：复制 3 条 SQL 到 SQL 编辑框，点"检测"
   - wf#4834：复制 15 条 INSERT 到 SQL 编辑框，点"检测"
3. **期望看到**：红框 alert 在 inception-result 上面 + 提交按钮 disabled + 文案变了

---

## ⚠️ 边界说明（业务方别踩）

- **跨库**：用 `库名.表名` 写的 SQL 跟 select 的库不一致，会被 reject
- **PK 冲突**：INSERT 的 PK 值在 DB 已存在，会被 reject
- **改 SQL 后重新检测**：会重新跑两个 check，alert 自动消失 + 按钮恢复"提交"
- **SELECT 不检测**：纯 SELECT 查询不受影响（archery 不会跑 SELECT，所以本来就不触发）

---

## 🐛 已知 case 已覆盖

- 反引号 + 不带反引号 schema 都识别
- `USE 库名;` 切换库后 ALTER 同库不算跨库（DBA-bug-1 套路）
- 业务方 INSERT 没指定列名时，按 information_schema.columns 列顺序定位 PK
- 业务方多行 SQL 无 `;` 分隔（wf#4821 实战主验证）

---

## 🔧 上线日志

- 9/16 09:23 阿达叔叔拍板（A 严格 reject 阻止提交）
- 9/16 10:30 commit c65c93e（含 finditer 修复 + 16/16 单元测试 PASS + 11/11 端到端演练 PASS）
- 9/16 12:33 110 prod master reload，业务方访问即生效
- changelog: `docs/changelogs/2026-09-16_cross-db-pk-check.md`
- 设计稿: `docs/designs/2026-09-16_w3-cross-db-pk-check-design.md`

---

**有任何问题或边界 case 反馈，群里吼一声即可。**

DBA · 9/16