"""driver 注册表。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §6.2

未来扩展：
    * 新增飞书 OA driver -> 在此添加 ``"feishu_oa"`` 条目
    * 新增企微 OA driver -> 在此添加 ``"qywx_oa"`` 条目
    * 上游 ``ApprovalFlow.audit_driver`` 的 choices 也要同步扩展
"""

import importlib
from typing import Dict

from .base import AuditDriver


# driver 名称 -> "module.path:ClassName" 形式的可定位符
DRIVER_REGISTRY: Dict[str, str] = {
    "archery": "sql.extensions.audit_drivers.archery:ArcheryDriver",
    ## CUSTOM-MODIFIED: 注册钉钉 OA driver（v0.7 §6.2） @ 2026-07-20 @ coder-agent
    ## 关联 changelog: docs/changelogs/2026-07-20_coder-dingtalk-oa-driver-integration.md
    "dingtalk_oa": "sql.extensions.dingtalk_oa.drivers.dingtalk:DingtalkOaDriver",
}


def get_driver(name: str) -> AuditDriver:
    """根据 name 取出 driver 单例。

    Args:
        name: ``ApprovalFlow.audit_driver`` 字段值。

    Returns:
        driver 实例。调用方负责调用其方法。

    Raises:
        ValueError: driver 名称未注册。
        ImportError: 路径写错或模块不存在。
    """
    if name not in DRIVER_REGISTRY:
        raise ValueError(
            f"Unknown audit_driver: {name!r}. "
            f"Registered: {sorted(DRIVER_REGISTRY)}"
        )
    path = DRIVER_REGISTRY[name]
    module_path, cls_name = path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, cls_name)
    return cls()


def register_driver(name: str, dotted_path: str) -> None:
    """动态注册 driver（用于插件化场景）。

    二次开发中暂时用不到，留作 API。
    """
    DRIVER_REGISTRY[name] = dotted_path
