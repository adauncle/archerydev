"""DDL 跨库同步 —— 数据模型。

## CUSTOM-MODIFIED: v0.5.0-alpha 3 张表 migration @ 2026-09-01 @ mavis

设计参考: docs/designs/2026-09-01_ddl-sync-data-model.md

3 张表 (跟 v0.4.0 ext_ddl_ghost_task 命名空间对齐, 都用 ext_ 前缀):

- **DdlSyncPair** (ext_ddl_sync_pair) — 库对配置 (业务库 ↔ 历史库)
  - 9 字段 + 1 关联: name / source_instance / source_db / target_instance / target_db
                 / sync_mode (whitelist/blacklist, R1 默认 blacklist) / enabled
                 / pending_tables (JSONField, R3 Phase 2) / filter_rule (JSONField, R3 Phase 3)
                 / created_by / created_at / updated_at
  - unique_together: (source_instance, source_db) — 同一业务库 + 库名 唯一

- **DdlSyncTable** (ext_ddl_sync_table) — 同步表清单
  - 5 字段 + 1 关联: pair (FK) / table_name
                  / sync_type (whitelist/blacklist, R2 加)
                  / transform_rule (JSONField) / created_at
  - unique_together: (pair, table_name, sync_type) — R2 加 sync_type 防 race

- **DdlSyncHistory** (ext_ddl_sync_history) — 同步历史审计
  - 7 字段 + 3 关联: pair (FK) / source_workflow (FK PROTECT) / target_workflow (FK SET_NULL)
                   / table_name / ddl_text / transformed_ddl_text (D2 拍板 3A 加)
                   / sync_status (5 选 1) / error_message
                   / created_at / finished_at
  - 5 status 状态机: pending / syncing / synced / skipped / failed
"""

from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class DdlSyncPair(models.Model):
    """DDL 跨库同步库对配置 — 业务库 ↔ 历史库

    ## CUSTOM-MODIFIED: v0.5.0-alpha DdlSyncPair 创建 @ 2026-09-01 @ mavis
    设计参考: docs/designs/2026-09-01_ddl-sync-data-model.md §2
    """

    ## CUSTOM-MODIFIED: R1 改默认 blacklist @ 2026-09-01 @ mavis
    SYNC_MODE_CHOICES = [
        ("blacklist", _("黑名单 (默认, 业务库全同步, 显式排除)")),  # R1 改默认
        ("whitelist", _("白名单 (DBA 显式选要同步的)")),  # R 之前原版默认
    ]

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(_("配对名"), max_length=128, help_text="DBA 自己起, 如 'accesscard 库对'")

    # 源 (业务库) instance + 库名 — 联合唯一
    source_instance = models.ForeignKey(
        "sql.Instance", on_delete=models.CASCADE,
        related_name="sync_pair_source",
        verbose_name=_("业务库实例"),
    )
    source_db = models.CharField(_("业务库名"), max_length=64)

    # 目标 (历史库) instance + 库名
    target_instance = models.ForeignKey(
        "sql.Instance", on_delete=models.CASCADE,
        related_name="sync_pair_target",
        verbose_name=_("历史库实例"),
    )
    target_db = models.CharField(_("历史库名"), max_length=64)

    ## CUSTOM-MODIFIED: D22 target_group 镜像工单走历史库审批流 @ 2026-09-03 @ mavis
    ## 业务: 镜像工单审批流必须走历史库组 (不是业务组, 不是 instance 默认 resource_group)
    ## 根因: D9 实战 group_id=source_workflow.group_id (业务组), Instance 是 M2M ResourceGroup 没 group_id 字段, fallback 用业务组
    ##       → wf#121 走 group 25 "测试组" audit_auth_groups='14,3', 不是用户期望的 group 22 "prod core for 历史库" '3'
    ## 修法: DdlSyncPair 加 target_group (FK ResourceGroup) + target_group_name, DBA 配库对时显式选
    ##      sync_trigger.py create_target_workflow 改用 pair.target_group.group_id (历史库组)
    ## 关联 changelog: docs/changelogs/2026-09-03_ddl-sync-w2-d22-mirror-target-group.md
    target_group = models.ForeignKey(
        "sql.ResourceGroup", on_delete=models.PROTECT,
        related_name="sync_pair_target_group",
        null=True, blank=True,
        verbose_name=_("镜像工单审批组"),
        help_text="DBA 配库对时显式选 (Instance 是 M2M ResourceGroup, 不能自动猜); 走当前 group_id 的 WorkflowAuditSetting (SQL_REVIEW) 拿审流",
    )
    target_group_name = models.CharField(_("镜像工单审批组名"), max_length=100, blank=True, default="")

    ## CUSTOM-MODIFIED: R1 默认 blacklist @ 2026-09-01 @ mavis
    sync_mode = models.CharField(
        _("同步模式"), max_length=16, choices=SYNC_MODE_CHOICES, default="blacklist",
        help_text="R1 改默认 blacklist (业务库 1589 张表全要同步, DBA 显式排除更省事)",
    )

    enabled = models.BooleanField(_("启用"), default=True, help_text="软删, 禁用不影响历史数据")

    # R3 Phase 2 加: 业务库新增表"待确认" 暂存
    pending_tables = models.JSONField(
        _("待确认表"), default=dict, blank=True,
        help_text="R3 Phase 2 用, 业务库新增表自动入'待确认', DBA 1-click 加白/黑名单",
    )
    # R3 Phase 3 加: 过滤规则持久化
    filter_rule = models.JSONField(
        _("过滤规则"), default=dict, blank=True,
        help_text="R3 Phase 3 用, 排除前缀/后缀/ENGINE/空表/最小大小",
    )

    created_by = models.ForeignKey(
        "sql.Users", on_delete=models.PROTECT,
        related_name="created_ddl_sync_pair",
        verbose_name=_("创建人"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        db_table = "ext_ddl_sync_pair"
        verbose_name = _("DDL 跨库同步库对")
        verbose_name_plural = _("DDL 跨库同步库对")
        unique_together = [("source_instance", "source_db")]


class DdlSyncTable(models.Model):
    """DDL 跨库同步表清单 — 跟 ddl_sync_pair 多对一, 一个库对可配多张同步表

    ## CUSTOM-MODIFIED: v0.5.0-alpha DdlSyncTable + R2 sync_type @ 2026-09-01 @ mavis
    设计参考: docs/designs/2026-09-01_ddl-sync-data-model.md §3
    """

    ## CUSTOM-MODIFIED: R2 加 sync_type @ 2026-09-01 @ mavis
    SYNC_TYPE_CHOICES = [
        ("whitelist", _("白名单 (要同步)")),
        ("blacklist", _("黑名单 (不同步)")),
    ]

    id = models.BigAutoField(primary_key=True)
    pair = models.ForeignKey(
        DdlSyncPair, on_delete=models.CASCADE, related_name="tables",
        verbose_name=_("库对"),
    )
    table_name = models.CharField(_("表名"), max_length=128, help_text="业务库表名 (不带 schema, 如 'accesscard_black_detail')")

    ## CUSTOM-MODIFIED: R2 加 sync_type @ 2026-09-01 @ mavis
    sync_type = models.CharField(
        _("同步类型"), max_length=16, choices=SYNC_TYPE_CHOICES, default="whitelist",
        help_text="区分白/黑名单 (跟 pair.sync_mode 配合, R2 加)",
    )

    transform_rule = models.JSONField(
        _("字段级调整规则"), default=dict, blank=True,
        help_text="Phase 3 用, 跳过列/重命名列/字段类型转换",
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)

    class Meta:
        db_table = "ext_ddl_sync_table"
        verbose_name = _("DDL 跨库同步表")
        verbose_name_plural = _("DDL 跨库同步表")
        # CUSTOM-MODIFIED: R2 改 unique_together 加 sync_type @ 2026-09-01 @ mavis
        # 同一对库同一表, 不能既在白名单又在黑名单 (虽然逻辑矛盾, 但允许 1-click 配时重复)
        # 实际不会同时存 (业务逻辑校验), unique_together 加 sync_type 防止 race condition
        unique_together = [("pair", "table_name", "sync_type")]
        indexes = [
            models.Index(fields=["pair", "table_name"]),
        ]


class DdlSyncHistory(models.Model):
    """DDL 跨库同步历史审计 — 业务库 DDL 触发后, 历史库镜像工单执行情况

    ## CUSTOM-MODIFIED: v0.5.0-alpha DdlSyncHistory + D2 拍板 3A transformed_ddl_text @ 2026-09-01 @ mavis
    设计参考: docs/designs/2026-09-01_ddl-sync-data-model.md §4
    """

    ## CUSTOM-MODIFIED: 5 status 状态机 @ 2026-09-01 @ mavis
    SYNC_STATUS_CHOICES = [
        ("pending", _("待执行 (业务库 DDL 已过审, 镜像工单待生成)")),
        ("syncing", _("同步中 (镜像工单已生成, 还没执行)")),
        ("synced", _("同步成功 (历史库镜像工单执行成功)")),
        ("skipped", _("跳过 (白名单不含/黑名单含, 不生成镜像工单)")),
        ("failed", _("失败 (历史库镜像工单执行失败)")),
    ]

    id = models.BigAutoField(primary_key=True)
    pair = models.ForeignKey(
        DdlSyncPair, on_delete=models.CASCADE, related_name="history",
        verbose_name=_("库对"),
    )
    # 业务库工单 (来源) — PROTECT 防止误删源工单导致历史审计断链
    source_workflow = models.ForeignKey(
        "sql.SqlWorkflow", on_delete=models.PROTECT,
        related_name="sync_source",
        verbose_name=_("业务库工单"),
    )
    # 历史库镜像工单 (目标, 可能还没生成或生成失败) — SET_NULL 工单可删, 审计保留
    target_workflow = models.ForeignKey(
        "sql.SqlWorkflow", on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="sync_target",
        verbose_name=_("历史库镜像工单"),
    )
    table_name = models.CharField(_("同步表名"), max_length=128)
    # 原始 DDL (业务库) — 审计完整记录, 不依赖 source_workflow.sql_content 仍存在
    ddl_text = models.TextField(_("原始 DDL"), help_text="业务库工单原始 SQL")
    # 历史库实际执行的 DDL (可能跟业务库不同, 因为 transform_rule) — D2 拍板 3A
    transformed_ddl_text = models.TextField(
        _("转换后 DDL"), blank=True, default="",
        help_text="应用 transform_rule 后的 DDL, 历史库实际执行的 SQL",
    )
    # 同步状态
    sync_status = models.CharField(
        _("同步状态"), max_length=16, choices=SYNC_STATUS_CHOICES, default="pending", db_index=True,
    )
    # 失败信息 (sync_status=failed 时填)
    error_message = models.TextField(_("失败信息"), blank=True, default="")
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(_("完成时间"), null=True, blank=True)

    class Meta:
        db_table = "ext_ddl_sync_history"
        verbose_name = _("DDL 跨库同步历史")
        verbose_name_plural = _("DDL 跨库同步历史")
        indexes = [
            # pending 状态优先展示 (业务 RD 实时跟踪)
            models.Index(fields=["sync_status", "-created_at"]),
            # 按库对查历史
            models.Index(fields=["pair", "-created_at"]),
        ]


# ============================================================
# CUSTOM-MODIFIED: D35-Pending 操作日志 DdlSyncAuditLog 模型 @ 2026-09-09 @ mavis
# 关联: docs/plans/2026-09-04_ddl-sync-w2-d35-pending-audit-log.md
# 业务背景: W1 D8 阶段 2 写 pair_detail.html "操作日志" tab 留了占位符
#          但 W1 D9 阶段 2 没真做, W2 D22-D34 也没补, D35-Pending 拍板方案 A
#          (完整独立 DdlSyncAuditLog 模型, 6 类操作: create/edit/enable/disable/one_click/bulk_import)
# ============================================================
class DdlSyncAuditLog(models.Model):
    """DDL 跨库同步操作日志 — 6 类操作的审计轨迹 (D35-Pending 方案 A)"""

    # CUSTOM-MODIFIED: 6 类 action enum @ 2026-09-09 @ mavis
    # 跟 D35-Pending 拍板 1:1 对应, 业务方一眼看出谁什么时候做了什么操作
    ## CUSTOM-MODIFIED: v0.6.0-alpha-1 9 类 action enum + 3 类同步表增删 @ 2026-09-10 @ mavis
    ## 1.4 同步表增删埋点: add_table / delete_table / transform_change
    ## 关联: docs/plans/2026-09-10_d35-oplog-roadmap.html 阶段 1.4
    ACTION_CHOICES = [
        ("create", _("创建库对")),
        ("edit", _("编辑库对 (非启用/禁用字段)")),
        ("enable", _("启用库对")),
        ("disable", _("禁用库对")),
        ("one_click", _("一键配置 (R2)")),
        ("bulk_import", _("批量导入 (R1)")),
        ("add_table", _("新增同步表")),         # v0.6.0-alpha-1
        ("delete_table", _("删除同步表")),       # v0.6.0-alpha-1
        ("transform_change", _("改 transform_rule")),  # v0.6.0-alpha-1
    ]

    id = models.BigAutoField(primary_key=True)
    # 库对 (PROTECT 防止误删库对导致审计断链)
    pair = models.ForeignKey(
        DdlSyncPair, on_delete=models.PROTECT,
        related_name="audit_logs",
        verbose_name=_("库对"),
    )
    # 操作类型 (6 选 1)
    action = models.CharField(
        _("操作类型"), max_length=16, choices=ACTION_CHOICES, db_index=True,
    )
    # 操作人 (PROTECT 防止误删用户, SET_NULL 留 trace)
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="ddl_sync_audit_logs",
        verbose_name=_("操作人"),
    )
    # 操作人 username (冗余, 用户被删后仍能展示 "DBA某某 启用了库对")
    operator_display = models.CharField(
        _("操作人"), max_length=64, blank=True, default="",
        help_text="冗余 operator 的 username, 用户被删后仍能展示",
    )
    # 详情 JSON (按 action 不同 schema 不同)
    # create / edit:  {"changed_fields": ["sync_mode", "enabled"], "old": {...}, "new": {...}}
    # enable / disable: {"from": false, "to": true}
    # one_click:      {"tables": ["t1", "t2", ...], "sync_type": "whitelist"}
    # bulk_import:    {"sync_type": "whitelist", "count": 50, "tables": [...]}
    ## CUSTOM-MODIFIED: v0.6.0-alpha-1 详情 schema 升级 @ 2026-09-10 @ mavis
    ## 1.3 库对配置前后 diff: edit 加 "changes" 字段, 实际 old/new 值
    ## 1.4 同步表增删: add_table / delete_table / transform_change 加 table_name / sync_type
    ## 关联: docs/plans/2026-09-10_d35-oplog-roadmap.html 阶段 1.2 / 1.3 / 1.4
    # add_table:        {"table_name": "t1", "sync_type": "whitelist", "transform_rule": {...}}
    # delete_table:     {"table_name": "t1", "sync_type": "whitelist"}
    # transform_change: {"table_name": "t1", "old_rule": {...}, "new_rule": {...}}
    detail_json = models.TextField(
        _("详情 JSON"), blank=True, default="",
        help_text="按 action 类型不同 schema 不同, 见模型 docstring",
    )
    ## CUSTOM-MODIFIED: v0.6.0-alpha-1 IP / UA 记录 (合规审计) @ 2026-09-10 @ mavis
    ## 1.5 IP / User-Agent: GenericIPAddressField (支持 IPv4/IPv6) + CharField 256
    ## 关联: docs/plans/2026-09-10_d35-oplog-roadmap.html 阶段 1.5
    client_ip = models.GenericIPAddressField(
        _("客户端 IP"), null=True, blank=True,
        help_text="从 X-Forwarded-For (有反代时) 或 REMOTE_ADDR 拿",
    )
    user_agent = models.CharField(
        _("浏览器 UA"), max_length=256, blank=True, default="",
        help_text="HTTP_USER_AGENT, 截断 256 字符",
    )
    ## CUSTOM-MODIFIED: v0.6.0-alpha-1 补录数据标记 @ 2026-09-10 @ mavis
    ## 1.1 历史数据补录脚本用 (v0.6.0-alpha-2 启用): True=脚本从 Archery LogEntry 补录
    ##      False=DBA 真实操作 (默认)
    is_backfilled = models.BooleanField(
        _("补录数据"), default=False, db_index=True,
        help_text="True=脚本从 Archery LogEntry 补录, False=DBA 真实操作",
    )
    # 时间
    created_at = models.DateTimeField(_("操作时间"), auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ext_ddl_sync_audit_log"
        verbose_name = _("DDL 跨库同步操作日志")
        verbose_name_plural = _("DDL 跨库同步操作日志")
        ordering = ["-created_at"]
        indexes = [
            # 按库对查日志 (D35 模板渲染用, 按时间倒序)
            models.Index(fields=["pair", "-created_at"]),
            # 按操作类型过滤
            models.Index(fields=["pair", "action", "-created_at"]),
        ]

    def __str__(self):
        op = self.operator_display or (self.operator.username if self.operator else "未知")
        return f"{op} {self.get_action_display()} {self.pair.name} @ {self.created_at:%Y-%m-%d %H:%M:%S}"
