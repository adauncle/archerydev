"""Archery 本地 Group 审批 driver（默认 driver）。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §6.3

本 driver 的存在纯粹是为了和外部 OA driver 接口对齐：
实际的状态推进完全由 ``AuditV2`` 父类完成，
本 driver 的所有方法都是空操作 / 返回占位。
"""

from typing import Optional

from .base import AuditDriver, DriverStartResult


class ArcheryDriver(AuditDriver):
    """默认 driver：本地 Group 审批。"""

    name = "archery"

    def start(self, workflow, audit, flow) -> DriverStartResult:
        """本地 Group 审批：无需任何外部动作。"""
        return DriverStartResult(external_id="")

    def apply_decision(
        self, audit, decision: str, actor, remark: str
    ) -> Optional[object]:
        """本地推进由 AuditV2 完成，本方法为空。"""
        return None

    def terminate(self, audit, actor, remark: str) -> None:
        """本地终止由 AuditV2 完成，本方法为空。"""
        return None

    def get_status(self, audit) -> dict:
        """本地 driver 状态永远跟随 ``WorkflowAudit.current_status``。"""
        return {"status": "local"}
