"""审批驱动抽象层。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §6

- ``base.AuditDriver``         抽象基类
- ``archery.ArcheryDriver``    默认本地 Group 审批
- ``registry.DRIVER_REGISTRY`` driver 注册表
- ``configurable_auditor``     顶层路由（``ConfigurableAuditor``）

未来新增 driver（如飞书/企微），在本目录下新增 ``<vendor>.py``，
并在 ``registry.DRIVER_REGISTRY`` 注册即可。
"""
