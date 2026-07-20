"""审批驱动抽象基类。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §6.1
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class Decision:
    """审批结果枚举常量。"""

    PASS = "pass"
    REJECT = "reject"


@dataclass
class DriverStartResult:
    """driver.start() 的返回值。"""

    external_id: str = ""
    extra: Optional[dict] = field(default_factory=dict)


class AuditDriver(ABC):
    """审批驱动抽象基类。

    约束：
        * 所有 driver 都必须实现 ``start`` / ``apply_decision`` /
          ``terminate`` / ``get_status`` 四个方法。
        * ``handle_callback`` 仅对有外部回调的 driver 需要实现
          （Archery 本地 driver 无需重写，会抛 ``NotImplementedError``）。

    调用方约定：
        * ``start`` 在工单创建时调用一次，返回 ``DriverStartResult``；
          若 ``external_id`` 为空字符串表示本地 driver。
        * ``apply_decision`` / ``terminate`` 是幂等操作。
        * ``get_status`` 用于对账（5 分钟轮询）。
    """

    name: str  # driver 标识，对应 ApprovalFlow.audit_driver

    @abstractmethod
    def start(self, workflow, audit, flow) -> DriverStartResult:
        """发起审批，返回 driver 需要的运行时信息。"""
        raise NotImplementedError

    @abstractmethod
    def apply_decision(self, audit, decision: str, actor, remark: str):
        """推进一次审批结果（PASS / REJECT）。"""
        raise NotImplementedError

    @abstractmethod
    def terminate(self, audit, actor, remark: str):
        """终止（用户主动撤回 / 强制关闭）。"""
        raise NotImplementedError

    @abstractmethod
    def get_status(self, audit) -> dict:
        """查询外部状态（用于对账）。"""
        raise NotImplementedError

    def handle_callback(self, request):
        """处理 driver 自己的外部回调。

        Archery 本地 driver 不需要回调；外部 OA driver 必须重写。
        """
        raise NotImplementedError("This driver has no callback")
