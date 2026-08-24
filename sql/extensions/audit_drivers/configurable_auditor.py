"""根据 ``ApprovalPolicy`` + ``ApprovalFlow`` 路由到不同 driver 的顶层 auditor。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §6.5

激活方式（第二阶段接入时配置）：
    ``archery/settings.py`` 中把 ``CURRENT_AUDITOR`` 环境变量改为::

        CUSTOM_DINGTALK_OA_AUDITOR=sql.extensions.audit_drivers.configurable_auditor:ConfigurableAuditor

    并设置::

        CUSTOM_DINGTALK_OA_ENABLED=True

## CUSTOM-MODIFIED: 审批流 source of truth 改为上游 WorkflowAuditSetting @ 2026-08-24 @ mavis
## 关联: docs/changelogs/2026-08-24_approval-flow-source-of-truth.md
## 根因 (8/24): 之前命中 policy 时用 flow.audit_auth_groups 覆盖上游 WorkflowAuditSetting,
##             导致用户在 Archery 上游 config/ 页面改审批流不生效 (被二次开发覆盖)。
## 改法: 命中 policy 时直接走父类, 用 WorkflowAuditSetting.audit_auth_groups。
##       ext_approval_flow.audit_driver (archery / dingtalk_oa) 仍生效, 走 driver 路由。
##       ext_approval_flow.audit_auth_groups 字段保留但不再生效 (历史字段)。
"""

import logging

from django.conf import settings

from sql.utils.workflow_audit import AuditSetting, AuditV2

from .registry import get_driver

logger = logging.getLogger(__name__)


class ConfigurableAuditor(AuditV2):
    """顶层路由 auditor。

    设计目标：
        * 关闭特性（``CUSTOM_DINGTALK_OA_ENABLED=False``）时，行为完全等同
          上游 ``AuditV2``，不引入任何风险。
        * 开启特性时，在 ``generate_audit_setting`` 中：
              1. 调 ``services.policy.match_policy`` 路由到一条 ``ApprovalPolicy``；
              2. **走父类**, 审批组从 Archery 上游 ``WorkflowAuditSetting`` 读
                 (用户在 config/ 页面配的就是 source of truth, 改了立即生效);
              3. 在 ``create_audit`` 中把 ``flow.audit_driver`` 锁定到工单,
                 并调 ``driver.start()`` 发起外部审批 (driver 路由仍生效)。
        * 任何异常都降级为本地 Group 审批，不阻塞业务（见 v0.7 §10.4）。
    """

    # ----- 特性开关 -----

    def _feature_enabled(self) -> bool:
        """读取 settings 中 ``CUSTOM_DINGTALK_OA_ENABLED``，默认 False。"""
        return bool(getattr(settings, "CUSTOM_DINGTALK_OA_ENABLED", False))

    # ----- 路由 -----

    def generate_audit_setting(self) -> AuditSetting:
        """根据 policy 决定审批流 (8/24 改: 不再覆盖上游 WorkflowAuditSetting)。

        关闭特性 -> 完全走父类。
        开启特性但未命中 policy -> 走父类 (保留原行为)。
        命中 policy -> 走父类 (用 Archery 上游 WorkflowAuditSetting, 不再覆盖)。

        业务价值: 用户在 Archery 上游 config/ 页面改审批流是 source of truth,
                  改了立即生效。ext_approval_flow.audit_auth_groups 字段保留但不再生效,
                  业务 RD 不要再被 "配了不生效" 困惑 (8/24 教训)。
        """
        if not self._feature_enabled():
            return super().generate_audit_setting()

        # 延迟 import 避免 settings 未配置时启动失败
        from sql.extensions.dingtalk_oa.services.policy import match_policy

        try:
            policy = match_policy(workflow=self.workflow)
        except Exception:  # noqa: BLE001
            # 路由失败不能让工单卡住, 落到父类
            logger.exception(
                "match_policy failed, fallback to AuditV2.generate_audit_setting"
            )
            return super().generate_audit_setting()

        if not policy:
            return super().generate_audit_setting()

        flow = policy.flow
        if not flow.is_active:
            return super().generate_audit_setting()

        # 8/24 拍板: 走父类, 用 Archery 上游 WorkflowAuditSetting
        # ext_approval_flow.audit_auth_groups 字段保留但不再生效 (仅作历史参考)
        # driver 路由 (archery / dingtalk_oa) 仍通过 flow.audit_driver 在 create_audit 里生效
        return super().generate_audit_setting()

    # ----- driver 协同 -----

    def _get_applied_policy(self):
        """通过 ``audit_auth_groups`` 反查命中的 policy。

        第二阶段（driver 接入阶段）补全：
            * 在 ``create_audit`` 中保存命中的 policy id 到 audit/ workflow 上
            * 回调 / 对账时再调这里反查
        当前阶段只暴露占位实现，调用方应先看 ``policy is None``。
        """
        return None

    def _sync_to_driver(self, decision: str, actor, remark: str) -> None:
        """将本地决策同步给 driver（钉钉加备注 / 终止流程等）。

        第二阶段（driver 接入阶段）补全。
        """
        driver_name = getattr(self.workflow, "audit_driver", "archery")
        try:
            driver = get_driver(driver_name)
        except (ValueError, ImportError) as e:
            logger.warning("driver %r not available: %s", driver_name, e)
            return
        try:
            driver.apply_decision(self.audit, decision, actor, remark)
        except Exception:  # noqa: BLE001
            # 不阻塞本地推进；定时对账兜底
            logger.exception("driver %r apply_decision failed", driver_name)
