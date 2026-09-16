# wf#4841 gh-ost 处理失败业务方通知 (DBA-bug-9)

> **致**: gcl (wf#4841 提交人)
> **抄送**: 马克群 (DBA 团队), [产品/领导] 视情况
> **来自**: mavis (DBA 一条龙)
> **日期**: 2026-09-16 18:50+
> **关联事件**: DBA-bug-9 (gh-ost 多 statement 工单只处理第一张表)
> **关联工单**: wf#4841 (hly_accesscard, 业务风控管理上线)

---

## ⚠️ 紧急: wf#4841 仅部分 SQL 执行成功

### 现状

你的 wf#4841 工单包含 **8 条 SQL**,Archery 平台显示"已正常结束"。但实际只 **1 条 ALTER 执行成功**,**7 条 SQL 没执行**。原因是我们 gh-ost 模式的一个 bug (DBA-bug-9),已经修复但 wf#4841 当时已受损。

### 工单实际包含 (按 statement_index 顺序)

| # | 类型 | 表 / 操作 | 是否执行 |
|---|---|---|---|
| 0 | CREATE TABLE | `vehicle_risk_hit` (主表) | ❌ 未执行 |
| 1 | CREATE TABLE | `vehicle_risk_hit_detail` (明细表) | ❌ 未执行 |
| 2 | CREATE TABLE | `risk_rule_set` (风控规则集表) | ❌ 未执行 |
| 3 | CREATE TABLE | `risk_rule_operation_log` (操作记录表) | ❌ 未执行 |
| 4 | ALTER TABLE | `hly_accesscard.accesscard_licensefront_info` ADD owner_name | ✅ **执行成功 (gh-ost 切流 481463/481463 行)** |
| 5 | ALTER TABLE | `hly_accesscard.vehicle_info_verify` ADD data_source | ❌ 未执行 |
| 6 | ALTER TABLE | `accesscard_vehicle_review` ADD risk_level | ❌ 未执行 |
| 7 | ALTER TABLE | `accesscard_opendcardapply` ADD 3 columns (agency_spread_code / spread_user / ...) | ❌ 未执行 |

**完整 SQL 内容已 dump 到 `docs/changelogs/2026-09-16_wf4841_full.sql` (7.9KB), 请 review 实际内容**

### 业务影响

- ✅ `accesscard_licensefront_info.owner_name` 字段已加 (历史表 481463 行)
- ❌ 风控业务相关 **4 张新表** 全没建 (vehicle_risk_hit / vehicle_risk_hit_detail / risk_rule_set / risk_rule_operation_log)
- ❌ 风控业务相关 **3 条 ALTER** 全没执行 (vehicle_info_verify.data_source / accesscard_vehicle_review.risk_level / accesscard_opendcardapply 3 字段)

**风控业务上线功能基本没生效**,需要业务方决定是否补建/补执行。

### 按 DBA 一条龙原则, **不主动帮业务方补建/补执行**

- 真实数据场景太多可能性,业务方自己 review 最稳
- **请业务方决定**:
  - 哪些表/字段要补建? (例如: `vehicle_risk_hit` 主表先建, INSERT 数据怎么办?)
  - 数据回填需求? (例如: 历史 `accesscard_licensefront_info.owner_name` 是否有业务数据需求,要不要从其他表同步)
  - 是否需要拆分原工单为多个小工单? (DBA-bug-9 修复后类似多表+CREATE 工单会被拒)

### DBA-bug-9 修复

我们已经把 gh-ost 模式升级:
- 134 dev + 110 prod 已部署
- **多 ALTER TABLE** → 自动创建多个 gh-ost task (每个 ALTER 一个)
- **CREATE/INSERT/UPDATE/DELETE** → 预检拒接,要求业务方拆成单独工单
- **poller** 改成"全部 task 终态才改工单状态",**不再误标'已正常结束'**

以后 wf#4841 这种含 CREATE + ALTER 一起的工单,gh-ost 模式会直接 reject 让业务方拆单,不会再丢 SQL。

### 业务方下一步

1. **Review 完整 SQL**: 打开 `docs/changelogs/2026-09-16_wf4841_full.sql` 看 8 条 SQL 详情
2. **确认哪些要补建/补执行**: 上面列表 7 条 ❌ 哪些真的需要?
3. **联系 DBA 团队** (马克群): 一起决定怎么拆分新工单提交 (gh-ost 模式 + 拆 CREATE)
4. **数据回填方案** (如有需要): 例如 `accesscard_licensefront_info.owner_name` 数据回填,业务方提供来源表/规则

---

## DBA 一条龙记录 (本会话)

- ✅ DBA-bug-9 根因定位: `views.py:_parse_first_alter` 只解第一条 + `poller._sync_workflow_status` 立即同步 wf.status,绕过 GoInception 路径
- ✅ D 方案拍板 (用户 17:42) + 7 文件改造 + 1 migration + 1 前端改造
- ✅ 134 dev 演练 5/5 PASS + reload master (HTTP 200)
- ✅ 110 prod 演练 5/5 PASS + reload master (HTTP 200, master 61590)
- ✅ wf#4841 现状排查 + 8 条 SQL 完整 dump
- ⏳ 业务方通知 (本文件) + 业务方实测后续多表 DDL 工单
- ⏳ 月度宣讲材料更新 (DBA-bug-9 加进实战案例)
- ⏳ gh-ost v0.3.0-alpha 排期 (排在 v0.2.3 OA 对账之后)

---

## 附: 实战新发现 (跨项目可复用)

1. **gh-ost 启用 → 工单 execute 路径被绕过**: gh-ost 模式启用后, GoInception.execute_workflow 路径被跳过, 非 gh-ost 处理的 SQL (CREATE/INSERT/UPDATE/DELETE) 全部丢失
2. **Archery poller 设计缺陷**: `_sync_workflow_status` 看到 task success 就改 wf.status, 没检查工单 SQL 是否全执行
3. **业务方实战: 工单含多 DDL 是常态**: CREATE TABLE + ALTER 是常见业务组合 (新表 + 字段调整一起做)
4. **CREATE TABLE 单独事务拆单原则**: CREATE 跟 ALTER 在 gh-ost 模式下必须拆单
5. **DdlGhostTask unique_together 限制**: UniqueConstraint(task_type, workflow) 限制一工单一 task, 必须扩到 (task_type, workflow, statement_index)