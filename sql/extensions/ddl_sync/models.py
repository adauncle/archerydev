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
