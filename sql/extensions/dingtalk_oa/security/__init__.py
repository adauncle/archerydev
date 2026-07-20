"""钉钉 OA 安全模块。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §10.5

子模块：
    * ``crypto``   —— 回调签名校验 + AES-256-CBC 加解密
    * ``guard``    —— 限流、IP 封禁、审批人白名单、安全告警
"""
