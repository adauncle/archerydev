"""
钉钉 OA 审批集成 —— 数据模型。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §5

模型清单（共 7 个）：
    1. SqlTypeRegistry        SQL 类型注册表
    2. CoreBusinessTable      核心业务表清单
    3. ApprovalFlow           审批流程定义（核心模型）
    4. ApprovalPolicy         审批策略（路由规则）
    5. GroupDingtalkAuditor   审批权限组 ↔ 钉钉审批人映射
    6. WorkflowAuditExternal  工单与外部 OA 系统关联
    7. DingtalkOaEventLog     钉钉 OA 事件流水
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class SqlTypeRegistry(models.Model):
    """SQL 类型注册表：内置 + 可扩展。

    用于 ``services.sql_type_detect`` 解析用户提交的 SQL 文本，
    提取出本工单涉及的 SQL 类型集合（如 ``{INSERT, DROP}``）。
    """

    code = models.CharField(
        "类型编码", primary_key=True, max_length=32,
        help_text="主键，如 INSERT/DROP/TRUNCATE ...",
    )
    category = models.CharField(
        "分类", max_length=16,
        help_text="DML / DDL / DQL / DCL",
    )
    description = models.CharField("说明", max_length=128)
    pattern = models.CharField(
        "识别正则", max_length=255,
        help_text="用于从 SQL 文本中匹配本类型，区分大小写由调用方控制",
    )
    default_severity = models.CharField(
        "默认风险等级", max_length=16,
        help_text="low / medium / high",
    )
    has_affected_rows = models.BooleanField(
        "是否参与行数维度", default=True,
        help_text="DDL/DQL 类设为 False，不参与行数维度判定",
    )
    is_critical = models.BooleanField(
        "是否高危", default=False,
        help_text="高危类型：DROP/TRUNCATE 等",
    )
    is_active = models.BooleanField("是否启用", default=True)

    class Meta:
        db_table = "ext_sql_type_registry"
        verbose_name = "SQL 类型注册表"
        verbose_name_plural = "SQL 类型注册表"

    def __str__(self):
        return f"{self.code} ({self.category})"


class CoreBusinessTable(models.Model):
    """核心业务表清单：用于业务表维度判定。"""

    id = models.AutoField(primary_key=True)
    instance = models.ForeignKey(
        "sql.Instance", on_delete=models.CASCADE,
        verbose_name="所属实例",
    )
    db_name = models.CharField("数据库名", max_length=64)
    table_name = models.CharField("表名", max_length=128)
    LEVEL_CHOICES = (
        ("L1", "L1"),
        ("L2", "L2"),
        ("L3", "L3"),
    )
    level = models.CharField("等级", max_length=8, choices=LEVEL_CHOICES)
    remark = models.CharField("备注", max_length=255, blank=True)
    is_active = models.BooleanField("是否启用", default=True)
    created_by = models.CharField("创建人", max_length=50)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "ext_core_business_table"
        verbose_name = "核心业务表"
        verbose_name_plural = "核心业务表"
        unique_together = (("instance", "db_name", "table_name"),)
        indexes = [models.Index(fields=["db_name", "table_name"])]

    def __str__(self):
        return f"{self.db_name}.{self.table_name} [{self.level}]"


class ApprovalFlow(models.Model):
    """审批流程定义：用户可在 admin 中任意创建多个。"""

    DRIVER_CHOICES = (
        ("archery", _("Archery 本地 Group 审批")),
        ("dingtalk_oa", _("钉钉 OA 智能工作流")),
    )

    code = models.CharField(
        "流程编码", primary_key=True, max_length=32,
        help_text="如 normal / critical / self_service / default",
    )
    name = models.CharField("流程名称", max_length=100)
    description = models.TextField("说明", blank=True)
    audit_driver = models.CharField(
        "审批驱动", max_length=32, choices=DRIVER_CHOICES,
    )
    audit_auth_groups = models.CharField(
        "审批权限组列表",
        max_length=500,
        help_text="逗号分隔的 Group ID 列表，按审批顺序",
    )
    dingtalk_process_code = models.CharField(
        "钉钉 OA 模板编码",
        max_length=64, blank=True,
        help_text="仅 audit_driver=dingtalk_oa 时填",
    )
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "ext_approval_flow"
        verbose_name = "审批流程"
        verbose_name_plural = "审批流程"

    def __str__(self):
        return f"{self.code} - {self.name}"


class ApprovalPolicy(models.Model):
    """审批策略（路由规则）：触发条件 → 目标流程。"""

    MATCH_MODE_CHOICES = (
        ("any", "任一命中"),
        ("all", "全部命中"),
    )
    AGGREGATE_CHOICES = (
        ("total", "所有 SQL 总和"),
        ("max", "单条 SQL 最大值"),
    )
    SEVERITY_CHOICES = (
        ("low", "低风险"),
        ("medium", "中风险"),
        ("high", "高风险"),
    )

    id = models.AutoField(primary_key=True)
    name = models.CharField("策略名称", max_length=100)
    description = models.TextField("说明", blank=True)
    priority = models.IntegerField(
        "优先级",
        default=0,
        help_text="数字越大优先级越高；按 priority 倒序遍历匹配",
    )
    is_enabled = models.BooleanField("是否启用", default=True)

    # ===== 触发条件：4 个维度 =====
    # 维度 1：SQL 类型
    sql_types = models.ManyToManyField(
        SqlTypeRegistry, blank=True,
        related_name="policies",
        help_text="命中 SQL 类型集合",
    )
    sql_type_match_mode = models.CharField(
        "SQL 类型匹配方式",
        max_length=16, choices=MATCH_MODE_CHOICES, default="any",
    )

    # 维度 2：业务表
    require_core_table = models.BooleanField(
        "要求命中核心业务表", default=False,
        help_text="True 时，工单涉及表必须在 CoreBusinessTable 中",
    )
    table_levels = models.CharField(
        "核心表等级",
        max_length=16, blank=True,
        help_text="L1,L2 多个用逗号分隔；空表示任意等级",
    )

    # 维度 3：影响行数
    min_affected_rows = models.IntegerField(
        "最小影响行数", null=True, blank=True,
    )
    max_affected_rows = models.IntegerField(
        "最大影响行数", null=True, blank=True,
    )
    affected_rows_aggregate = models.CharField(
        "行数聚合方式",
        max_length=16, choices=AGGREGATE_CHOICES, default="total",
    )

    # 兼容层：上游 WorkflowAuditSetting.syntax_type 字段
    legacy_syntax_types = models.CharField(
        "兼容 syntax_type",
        max_length=32, blank=True,
        help_text="逗号分隔：0/1=DDL/2=DML/3=导出；可留空",
    )

    severity = models.CharField(
        "风险等级", max_length=16,
        choices=SEVERITY_CHOICES, default="medium",
    )

    # ===== 命中目标 =====
    flow = models.ForeignKey(
        ApprovalFlow, on_delete=models.PROTECT,
        related_name="policies",
        help_text="命中后跳转到哪个流程（PROTECT 防止误删）",
    )

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "ext_approval_policy"
        verbose_name = "审批策略"
        verbose_name_plural = "审批策略"
        ordering = ["-priority"]

    def __str__(self):
        return f"{self.name} → {self.flow_id}"


class GroupDingtalkAuditor(models.Model):
    """审批权限组 ↔ 钉钉审批人映射。

    同一 (group, resource_group) 只能有一条记录。
    resource_group 为空时表示跨资源组通用。
    """

    id = models.AutoField(primary_key=True)
    group = models.ForeignKey(
        "auth.Group", on_delete=models.CASCADE,
        related_name="dingtalk_auditors",
    )
    resource_group = models.ForeignKey(
        "sql.ResourceGroup", null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="dingtalk_auditors",
        help_text="为空表示跨资源组通用",
    )
    # 二选一：精确 userid 或 按部门拉
    dingtalk_user_ids = models.TextField(
        "钉钉用户 ID 列表",
        blank=True,
        help_text="JSON 数组，如 ['user1','user2']",
    )
    dingtalk_dept_id = models.CharField(
        "钉钉部门 ID", max_length=64, blank=True,
    )
    # 抄送
    dingtalk_cc_user_ids = models.TextField(
        "钉钉抄送用户 ID 列表",
        blank=True,
        help_text="JSON 数组",
    )
    is_active = models.BooleanField("是否启用", default=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "ext_group_dingtalk_auditor"
        verbose_name = "审批人钉钉映射"
        verbose_name_plural = "审批人钉钉映射"
        unique_together = (("group", "resource_group"),)

    def __str__(self):
        target = self.group_id
        if self.resource_group_id:
            target = f"{self.group_id}@{self.resource_group_id}"
        return f"dingtalk auditor for group={target}"


class WorkflowAuditExternal(models.Model):
    """工单与外部 OA 系统的关联记录。"""

    STATUS_CHOICES = (
        ("RUNNING", "RUNNING"),
        ("APPROVED", "APPROVED"),
        ("REJECTED", "REJECTED"),
        ("TERMINATED", "TERMINATED"),
        ("FALLBACK", "FALLBACK"),
    )

    id = models.AutoField(primary_key=True)
    audit = models.OneToOneField(
        "sql.WorkflowAudit", on_delete=models.CASCADE,
        related_name="external_audit",
    )
    source = models.CharField(
        "来源", max_length=32,
        help_text="如 dingtalk_oa；留作未来扩展",
    )
    external_process_instance_id = models.CharField(
        "外部流程实例 ID", max_length=128, db_index=True,
    )
    external_process_code = models.CharField(
        "外部流程模板编码", max_length=64,
    )
    current_external_node = models.CharField(
        "当前外部节点", max_length=64, blank=True,
    )
    external_status = models.CharField(
        "外部流程状态", max_length=32,
        help_text="RUNNING / APPROVED / REJECTED / TERMINATED / FALLBACK",
    )
    oa_failure_reason = models.CharField(
        "OA 失败原因", max_length=500, blank=True,
        help_text="降级时填写，便于排查",
    )
    last_synced_at = models.DateTimeField(
        "最近同步时间", null=True, blank=True,
    )
    fallback_at = models.DateTimeField(
        "降级时间", null=True, blank=True,
    )
    reconcile_failed_count = models.IntegerField(
        "对账失败次数", default=0,
    )
    payload = models.JSONField(
        "外部 OA 透传快照", default=dict, blank=True,
    )

    class Meta:
        db_table = "ext_workflow_audit_external"
        verbose_name = "工单外部 OA 关联"
        verbose_name_plural = "工单外部 OA 关联"

    def __str__(self):
        return f"{self.audit_id} → {self.source} {self.external_status}"


class DingtalkOaEventLog(models.Model):
    """钉钉 OA 事件流水（用于幂等 / 排错 / 审计）。"""

    id = models.BigAutoField(primary_key=True)
    audit = models.ForeignKey(
        "sql.WorkflowAudit", on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="dingtalk_events",
    )
    event_type = models.CharField("事件类型", max_length=32)
    event_id = models.CharField(
        "事件 ID（幂等用）", max_length=64, db_index=True,
    )
    payload = models.JSONField("事件内容", default=dict, blank=True)
    signature = models.CharField("签名", max_length=128, blank=True)
    raw_payload_encrypted = models.TextField(
        "原始密文（截断留存）", blank=True,
    )
    processed = models.BooleanField("已处理", default=False)
    error = models.TextField("错误信息", blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        db_table = "ext_dingtalk_oa_event_log"
        verbose_name = "钉钉 OA 事件流水"
        verbose_name_plural = "钉钉 OA 事件流水"
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["audit", "event_type"]),
        ]

    def __str__(self):
        return f"{self.event_type} @ {self.created_at:%Y-%m-%d %H:%M:%S}"
