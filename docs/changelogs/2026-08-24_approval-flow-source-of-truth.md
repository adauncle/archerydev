# 2026-08-24 审批流 source of truth 改为 Archery 上游 WorkflowAuditSetting

## 摘要

修复 ConfigurableAuditor (8/11 二次开发加的) 命中 policy 时用 `flow.audit_auth_groups` 覆盖 Archery 上游 `WorkflowAuditSetting` 的问题。用户期望 Archery 上游 `config/` 页面配的审批流是 source of truth, 改了立即生效 — 这是基本功能需求。

## 根因

8/11 加的 `ConfigurableAuditor.generate_audit_setting` (代码 `sql/extensions/audit_drivers/configurable_auditor.py:73-86`):

```python
flow = policy.flow
groups = [g.strip() for g in (flow.audit_auth_groups or "").split(",") if g.strip()]
return AuditSetting(
    audit_auth_groups=groups,  # ← 用 ext_approval_flow 的, 覆盖上游
    auto_pass=False,
    auto_reject=False,
)
```

命中 policy 时, `flow.audit_auth_groups` 覆盖上游 `WorkflowAuditSetting.audit_auth_groups`。结果:
- 用户在 Archery 上游 `config/` 页面配的 2 级 (`14,3`) 不生效
- 实际跑的是 ext_approval_flow 配的 3 级 (`14,15,3`)
- 业务 RD 困惑: "我配了不生效"

## 修法

8/24 拍板: ConfigurableAuditor 命中 policy 时直接走父类 (`super().generate_audit_setting()`), 用 Archery 上游 `WorkflowAuditSetting.audit_auth_groups` (用户配的就是 source of truth)。

```python
flow = policy.flow
if not flow.is_active:
    return super().generate_audit_setting()

# 8/24 改: 走父类, 用 Archery 上游 WorkflowAuditSetting
# ext_approval_flow.audit_auth_groups 字段保留但不再生效 (仅作历史参考)
# driver 路由 (archery / dingtalk_oa) 仍通过 flow.audit_driver 在 create_audit 里生效
return super().generate_audit_setting()
```

## 保留不动的功能

- `ext_approval_flow.audit_driver` 字段 (archery / dingtalk_oa) 继续生效 — 走 driver 路由
- 钉钉 OA 通知 (8/11 加的) — 保留
- 3D 路由 (SQL 类型 / 核心业务表 / 影响行数范围) — 保留
- 3 个 flow (default / normal / high_risk) — 保留, `audit_auth_groups` 字段保留但不再生效 (历史字段)

## 影响范围

| 范围 | 状态 |
|---|---|
| SQL 上线申请 (workflow_type=1) | ✅ 改后生效, 改 config/ 立即生效 |
| SQL 查询 (workflow_type=2) | ✅ 一直生效, 走 Archery 上游 AuditV2 |
| SQL 优化 / 工单插件 / 实例管理 | ✅ 一直生效, 走 Archery 上游 |
| 钉钉 OA 通知 (8/11) | ✅ 保留 |
| ext_approval_flow driver 路由 | ✅ 保留 |

## 演练 (134 dev)

提演练工单 #84, 同时跑 `AuditV2.generate_audit_setting()` 和 `ConfigurableAuditor.generate_audit_setting()` 对比:

```
=== 跑 AuditV2.generate_audit_setting (Archery 上游) ===
  audit_auth_groups = ['14', '3']
  审批人 (group name) = 研发组长 -> DBA   ✓ 2 级

=== 跑 ConfigurableAuditor.generate_audit_setting (8/24 改后) ===
  audit_auth_groups = ['14', '3']
  审批人 (group name) = 研发组长 -> DBA   ✓ 2 级
  ✅ 修法生效: ConfigurableAuditor 跟 AuditV2 一致 (都走 WorkflowAuditSetting)

=== 清理: 删演练工单 84 ===
  done
```

HUP gunicorn master 38114 后, 5s 内新 worker 50625 加载新代码, 演练通过。

## 推 110 prod 必做 (补一条)

5 步必做脚本 (commit `035850f` 8/17) 加步骤 13: 部署 configurable_auditor.py 改动 + HUP gunicorn。5.7/8.0 兼容, 无 schema 改动。

## 文件改动

- `sql/extensions/audit_drivers/configurable_auditor.py` (10 行改动, 加 CUSTOM-MODIFIED 注释头)

## 关联

- 8/11 dingtalk-oa-workflow 详设: `docs/designs/2026-07-20_dingtalk-oa-workflow.md` (v0.7 §6.5 ConfigurableAuditor 设计)
- 8/11 ext_approval_flow 配 3 级 fix: `docs/changelogs/2026-07-20_dingtalk-oa-workflow.md`
- 8/18 教训: 业务配置 (审批组 ID) 必须看实际审批日志, 不要从代码脑补
- 8/17 5 步必做脚本: `scripts/deploy/5step_prerequisites_110prod.sh`
- troubleshooting.md: 8/24 这次的事故根因 (WorkflowAuditSetting 被覆盖)
