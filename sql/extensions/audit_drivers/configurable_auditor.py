"""根据 ``ApprovalPolicy`` + ``ApprovalFlow`` 路由到不同 driver 的顶层 auditor。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §6.5

激活方式（第二阶段接入时配置）：
    ``archery/settings.py`` 中把 ``CURRENT_AUDITOR`` 环境变量改为::

        CUSTOM_DINGTALK_OA_AUDITOR=sql.extensions.audit_drivers.configurable_auditor:ConfigurableAuditor

    并设置::

        CUSTOM_DINGTALK_OA_ENABLED=True
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
              2. 用 ``policy.flow`` 覆盖默认 ``audit_auth_groups``；
              3. 在 ``create_audit`` 中把 ``flow.audit_driver`` 锁定到工单，
                 并调 ``driver.start()`` 发起外部审批。
        * 任何异常都降级为本地 Group 审批，不阻塞业务（见 v0.7 §10.4）。
    """

    # ----- 特性开关 -----

    def _feature_enabled(self) -> bool:
        """读取 settings 中 ``CUSTOM_DINGTALK_OA_ENABLED``，默认 False。"""
        return bool(getattr(settings, "CUSTOM_DINGTALK_OA_ENABLED", False))

    # ----- 路由 -----

    def generate_audit_setting(self) -> AuditSetting:
        """根据 policy 决定审批流。

        关闭特性 -> 完全走父类。
        开启特性但未命中 policy -> 走父类（保留原行为）。
        命中 policy -> 用 ``policy.flow.audit_auth_groups`` 覆盖。
        """
        if not self._feature_enabled():
            return super().generate_audit_setting()

        # 延迟 import 避免 settings 未配置时启动失败
        from sql.extensions.dingtalk_oa.services.policy import match_policy

        try:
            policy = match_policy(workflow=self.workflow)
        except Exception:  # noqa: BLE001
            # 路由失败不能让工单卡住，落到父类
            logger.exception(
                "match_policy failed, fallback to AuditV2.generate_audit_setting"
            )
            return super().generate_audit_setting()

        if not policy:
            return super().generate_audit_setting()

        flow = policy.flow
        if not flow.is_active:
            return super().generate_audit_setting()

        # 把 flow 的 groups 转换为 AuditSetting
        groups = [g.strip() for g in (flow.audit_auth_groups or "").split(",") if g.strip()]
        if not groups:
            return super().generate_audit_setting()

        return AuditSetting(
            audit_auth_groups=groups,
            auto_pass=False,
            auto_reject=False,
        )

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
