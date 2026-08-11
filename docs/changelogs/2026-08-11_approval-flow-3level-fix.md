# 2026-08-11 · 审批流 3 级配置生效修复

> **作者**: mavis  · **面向 DBA 验收 + 后续 110 PROD 推 v0.2.0/v0.3.0 参考**

## 一句话

修一个真 bug：v0.2.x 钉钉 OA 框架引入的 `ext_approval_flow` 表**覆盖**了上游 `workflow_audit_setting` 表的优先级，导致 `workflow_audit_setting` 里配的 "14,15,3"（3 级审批）走不到。本次把 3 个 flow 的 `audit_auth_groups` 统一改成 14,15,3。

## 问题

8/11 用户浏览器验证发现：提交 `ALTER TABLE accesscard_black_detail add column test3` 走"DBA（Archery Admin (Prod), 马克群）"单级审批，但用户配置的是"研发组长→DBA组长→DBA"3 级。

## 根因

`ConfigurableAuditor.generate_audit_setting`（`sql/extensions/audit_drivers/configurable_auditor.py:48-86`）：

```python
def generate_audit_setting(self):
    if not self._feature_enabled():
        return super().generate_audit_setting()  # 读 workflow_audit_setting
    
    try:
        policy = match_policy(workflow=self.workflow)
    except Exception:
        return super().generate_audit_setting()  # fallback
    
    if not policy:
        return super().generate_audit_setting()  # policy 不命中 → 读 workflow_audit_setting
    
    flow = policy.flow
    # 命中 policy → 用 flow.audit_auth_groups 覆盖
    return AuditSetting(audit_auth_groups=flow.audit_auth_groups.split(","), ...)
```

`flow.audit_auth_groups` 的值来自 `ext_approval_flow` 表，不是 `workflow_audit_setting`。

134 dev 实际状态（修前）：

| code | audit_driver | audit_auth_groups | 含义 |
|------|--------------|--------------------|------|
| default | archery | **"3"** | 所有策略不命中时 fallback |
| normal | archery | **"3"** | 中低风险 DML 走 Archery 内审 |
| high_risk | dingtalk_oa | **"3"** | 高风险 DDL/DML 走钉钉 OA |

3 个 flow 全部是单级 DBA 审批。`workflow_audit_setting.audit_auth_groups="14,15,3"` 完全没被读到。

历史：
- v0.1.4 (2026-07-22) `init_fallback_flow` 命令的占位值是 `"1,2"`，当时上线时手工改成 `"3"` 单级（占位改得不合适）
- 上线后从 7/22 到 8/11 没人改回 3 级，导致 3 周来所有工单都走单级审批

## 触发流程（以 wf#57 为例）

`ALTER TABLE accesscard_black_detail add column test3`：
1. 引擎 review 后 affected_rows=**238275**
2. `match_policy` 命中 `ext_approval_policy.id=1` "高风险 DDL/DML 走钉钉 OA"（min_affected_rows=100，DDL 类型匹配）
3. `flow = ext_approval_flow.high_risk` (audit_auth_groups="3" 单级)
4. 跳过 `workflow_audit_setting`，直接用 flow 的 audit_auth_groups="3"
5. 工单 audit_auth_groups 写成 "3"，current_audit=3 (DBA)，next_audit=-1

## 修法

### 1. 134 dev UPDATE 表（已执行）

```sql
UPDATE ext_approval_flow SET audit_auth_groups='14,15,3', updated_at=NOW()
WHERE code IN ('default', 'normal', 'high_risk');
```

### 2. 加 management command (110 PROD 推时跑)

`sql/extensions/dingtalk_oa/management/commands/fix_approval_flow_3level.py`：
- idempotent UPDATE
- 跑前/跑后 print 对比
- 提示 DBA 实际审批组如果不是 14/15/3 就到 admin 改

### 3. 改 `init_fallback_flow.py` 占位值

`FALLBACK_PLACEHOLDER_GROUPS` 从 `"1,2"` 改成 `"14,15,3"`（下次新装走 3 级）。

## 端到端验证（134 dev）

| 步骤 | 结果 |
|------|------|
| 1. 改前 `ext_approval_flow.high_risk.audit_auth_groups` | "3" |
| 2. 改前 `wf#57 generate_audit_setting()` | `['3']` |
| 3. 改后 `ext_approval_flow.high_risk.audit_auth_groups` | "14,15,3" |
| 4. 改后 `wf#57 generate_audit_setting()` | `['14', '15', '3']` |
| 5. 改后**新工单 wf#58 submit** | `audit_auth_groups='14,15,3'` `current_audit=14 研发组长, next_audit=15 DBA组长` ✅ |
| 6. `manage.py fix_approval_flow_3level` 跑两遍 | 第一次 UPDATE 3 行，第二次 0 行（idempotent）✅ |

## 变更文件清单

| 文件 | 变更 |
|------|------|
| `sql/extensions/dingtalk_oa/management/commands/fix_approval_flow_3level.py` | 新增 (idempotent fix 命令) |
| `sql/extensions/dingtalk_oa/management/commands/init_fallback_flow.py` | 占位 `1,2` → `14,15,3` |
| `docs/changelogs/2026-08-11_approval-flow-3level-fix.md` | 本 changelog |

## 110 PROD 推 v0.2.0/v0.3.0 前必做

```bash
# 110 prod
cd /dbdata/archery_v114_c9236a0
sudo -u archery venv/bin/python manage.py fix_approval_flow_3level
```

输出 `✅ 完成: 更新 3 个 flow 的 audit_auth_groups = '14,15,3'` 即生效。

如果实际审批组不是 14/15/3 (研发组长/DBA组长/DBA)，到 admin / SQL 改：

```sql
UPDATE ext_approval_flow SET audit_auth_groups='<实际组 ID 列表, 逗号分隔>';
```

## 关联设计

- `docs/designs/2026-07-20_dingtalk-oa-workflow.md` v0.7 §11 决策 2（init_fallback_flow）
- `docs/designs/2026-08-10_gh-ost-detail-design.html` §7.3（v0.3.0-beta 审批守卫）
- `docs/changelogs/2026-07-22_v0.1.4-submitsql-audit-setting.md`（v0.1.4 占位 "3" 由来）
- `docs/changelogs/2026-08-11_gh-ost-approval-gating.md`（v0.3.0-beta 审批守卫）
