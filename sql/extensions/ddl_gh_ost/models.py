"""
gh-ost 无锁 DDL —— 数据模型。

设计参考：docs/designs/2026-08-05_gh-ost-product-design.html v0.3.0 §5/§6/§9

alpha 阶段只有一个模型 ``DdlGhostTask``，挂在 SqlWorkflow 上（一对一）。
beta 阶段会扩到多表（影子表、cut-over 历史等），但本 alpha 不引入新表。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class DdlGhostTask(models.Model):
    """gh-ost 任务表 —— 记录每个 gh-ost 任务的进度快照 + 控制参数。

    ## CUSTOM-MODIFIED: v0.4.5-alpha 拆 OneToOne 为 ForeignKey @ 2026-08-06 @ mavis
    关联设计: docs/designs/2026-08-05_gh-ost-product-design.html v0.4.5 §3

    - ghost 场景：每个 SQL 工单一条 task（task_type=ghost, workflow=工单）
    - rebuild 场景：每个数据库表一条 task（task_type=rebuild, workflow=NULL,
                  target_table=db.table）
    - Meta.unique_together = (task_type, workflow) 约束：同类型同工单唯一

    v0.3.0 旧设计：OneToOneField（每个工单最多一条）。
    v0.4.5 改造：ForeignKey(null=True) 允许 rebuild 不挂工单；
                唯一性改由 unique_together 保障。
    """

    ## CUSTOM-MODIFIED: v0.4.5-alpha 加 task_type 二选一 @ 2026-08-06 @ mavis
    TASK_TYPE_CHOICES = (
        ("ghost", "gh-ost DDL（v0.3.0 改造，SQL 工单触发）"),
        ("rebuild", "碎片回收（v0.4.5 改造，DBA 手动选表触发）"),
    )

    STATUS_CHOICES = (
        ("pending", _("待预检")),       # 刚勾选 gh-ost，预检未跑
        ("precheck_failed", _("预检未通过")),
        ("queued", _("排队中")),          # 预检通过，等待执行
        ("running", _("执行中")),
        ("cut_over", _("切表阶段")),
        ("success", _("成功")),
        ("failed", _("失败")),
        ("cancelled", _("已取消")),
        ("rolled_back", _("已回滚")),  # beta：DBA 手动 drop 影子表 + 标 rolled_back
    )

    STAGE_CHOICES = (
        # gh-ost 真实阶段（beta 阶段开始用，alpha 全部返回 connecting 占位）
        ("connecting", "connecting"),
        ("copying", "Copying rows"),
        ("waiting_cut_over", "waiting for cut-over"),
        ("cut_over", "cut-over"),
        ("swapped", "swapped"),
        ("done", "done"),
    )

    # ===== 主键 / 关联 =====
    id = models.BigAutoField(primary_key=True)
    ## CUSTOM-MODIFIED: v0.4.5-alpha OneToOne → ForeignKey(null=True) @ 2026-08-06 @ mavis
    ## ghost 场景挂 SqlWorkflow（一对一语义由 unique_together 保障）；
    ## rebuild 场景 workflow=NULL，靠 target_table 定位表。
    workflow = models.ForeignKey(
        "sql.SqlWorkflow", on_delete=models.CASCADE,
        related_name="ghost_task",
        null=True, blank=True,
        verbose_name="SQL 工单（rebuild 场景为 NULL）",
    )
    ## CUSTOM-MODIFIED: v0.4.5-alpha 加 task_type @ 2026-08-06 @ mavis
    task_type = models.CharField(
        "任务类型", max_length=16, choices=TASK_TYPE_CHOICES,
        default="ghost", db_index=True,
        help_text="ghost=gh-ost DDL 工单；rebuild=碎片回收（表级）",
    )
    ## CUSTOM-MODIFIED: v0.4.5-alpha 加 target_table @ 2026-08-06 @ mavis
    target_table = models.CharField(
        "目标表（rebuild 用）", max_length=128, blank=True, db_index=True,
        help_text="rebuild 场景存 db.table（如 archery_dev.accesscard_black_detail）；ghost 场景为空",
    )
    ## CUSTOM-MODIFIED: v0.4.5-alpha 加 related_task_id @ 2026-08-06 @ mavis
    related_task_id = models.BigIntegerField(
        "关联 task id", null=True, blank=True,
        help_text="归档联动时存 ArchiveConfig.id；rebuild 内部队列存前序 task id",
    )
    ## CUSTOM-MODIFIED: v0.4.5-alpha 修 queue 漏洞加 instance 字段 @ 2026-08-10 @ mavis
    ## rebuild 任务 workflow=NULL 没有直接的 instance 字段，
    ## 但 gh-ost 必须知道连哪个 instance。存到 instance 字段（PROTECT 防止误删）。
    ## ghost 场景 nullable（从 task.workflow.instance 拿），rebuild 场景必填。
    instance = models.ForeignKey(
        "sql.Instance", on_delete=models.PROTECT,
        null=True, blank=True, related_name="ghost_tasks",
        verbose_name="实例（rebuild 必填）",
    )
    audit = models.ForeignKey(
        "sql.WorkflowAudit", on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="ghost_tasks",
        verbose_name="审批工单（审批通过后才有）",
    )

    # ===== 用户选择 =====
    enabled = models.BooleanField(
        "启用 gh-ost", default=True,
        help_text="用户勾选 = 走 gh-ost；未勾选 = 走传统 ALTER，task 不创建",
    )
    cut_over_strategy = models.CharField(
        "切表策略", max_length=32,
        choices=(
            ("immediate", "立即切（默认，alpha 阶段）"),
            ("low_traffic_window", "业务低峰期切（02:00-04:00）"),
            ("manual", "DBA 手动触发"),
        ),
        default="immediate",
    )
    cut_over_window_start = models.TimeField(
        "低峰期起始", null=True, blank=True,
    )
    cut_over_window_end = models.TimeField(
        "低峰期结束", null=True, blank=True,
    )
    max_load_threads_running = models.IntegerField(
        "暂停阈值（threads_running）", default=30,
        help_text="超过此值自动暂停 gh-ost 复制（生产保护）",
    )
    timeout_seconds = models.IntegerField(
        "超时熔断（秒）", default=7200,
        help_text="超过此时间未完成自动停止，默认 2h",
    )

    # ===== 预检查 5 道关（提交时固化）=====
    precheck_passed = models.BooleanField("预检通过", default=False)
    precheck_report = models.JSONField(
        "预检报告", default=dict, blank=True,
        help_text="5 道检查每道的 status/evidence/message",
    )
    precheck_at = models.DateTimeField("预检时间", null=True, blank=True)

    # ===== 提取的 ALTER 语句 =====
    alter_statement = models.TextField(
        "ALTER 语句",
        help_text="从 sql_content 提取的第一条 ALTER TABLE 语句",
    )
    db_name = models.CharField("数据库", max_length=64, blank=True)
    table_name = models.CharField("原表名", max_length=128, blank=True)
    ghost_table_name = models.CharField(
        "影子表名", max_length=128, blank=True,
        help_text="gh-ost 生成，格式 _<table>_gho",
    )
    original_table_size_bytes = models.BigIntegerField(
        "原表大小（字节）", null=True, blank=True,
    )
    disk_free_bytes = models.BigIntegerField(
        "磁盘剩余（字节，预检时）", null=True, blank=True,
    )

    # ===== rebuild 场景专属字段 (CUSTOM-MODIFIED: v0.4.5 拍板 3 决策 @ 2026-08-13 @ mavis)
    # 关联: docs/changelogs/2026-08-13_v0405-rebuilt-fields.md
    #       docs/designs/2026-08-13_v0405-ghost-rebuild-design.md §3.2
    # 业务: rebuild 任务在 rebuild_start 时查 information_schema.tables 拿原表属性,
    #       拼出 ENGINE+ROW_FORMAT+CHARSET 形式的 alter 子句 (3 层防护确保 5.7/8.0
    #       都触发物理重写且字符集不漂), 5 字段记录"这次 rebuild 改了什么",
    #       DBA 排查 / 列表页展示都用得上.
    rebuilt_charset = models.CharField(
        "原表 CHARSET", max_length=32, blank=True, null=True,
        help_text="rebuild 场景: 原表 DEFAULT CHARSET (utf8mb4 等), 记录用",
    )
    rebuilt_row_format = models.CharField(
        "原表 ROW_FORMAT", max_length=16, blank=True, null=True,
        help_text="rebuild 场景: 原表 ROW_FORMAT (Dynamic/Compact 等), 记录用",
    )
    rebuilt_collation = models.CharField(
        "原表 COLLATION", max_length=64, blank=True, null=True,
        help_text="rebuild 场景: 原表 DEFAULT COLLATION (utf8mb4_general_ci 等), 记录用",
    )
    rebuilt_alter_full = models.TextField(
        "rebuild 用的完整 alter 子句", blank=True,
        help_text="rebuild 场景: 完整 alter 子句 (不带 ALTER TABLE t 前缀), 列表页 truncated 显示",
    )
    rebuilt_at = models.DateTimeField(
        "rebuild 完成时间", null=True, blank=True,
        help_text="rebuild 场景: 物理重写完成时间 (cut-over 成功时写)",
    )

    # ===== 状态机 =====
    status = models.CharField(
        "状态", max_length=20, choices=STATUS_CHOICES,
        default="pending", db_index=True,
    )
    current_stage = models.CharField(
        "gh-ost 阶段", max_length=32, choices=STAGE_CHOICES,
        blank=True,
    )

    # ===== 进程信息 =====
    ghost_pid = models.IntegerField(
        "gh-ost PID", null=True, blank=True,
    )
    systemd_scope_unit = models.CharField(
        "systemd scope 单元", max_length=128, blank=True,
        help_text="systemd-run --scope=ghost-<audit_id> 创建的临时 unit",
    )

    # ===== 进度快照（每 3s 由后台 poller 更新，beta 启用）=====
    progress_pct = models.IntegerField("进度百分比", default=0)
    progress_rows_copied = models.BigIntegerField(
        "已复制行数", null=True, blank=True,
    )
    progress_rows_total = models.BigIntegerField(
        "总行数", null=True, blank=True,
    )
    progress_speed_rows_per_sec = models.IntegerField(
        "复制速度（行/s）", null=True, blank=True,
    )
    progress_eta_seconds = models.IntegerField(
        "预计剩余（秒）", null=True, blank=True,
    )
    progress_threads_running = models.IntegerField(
        "当前 threads_running", null=True, blank=True,
    )
    progress_message = models.CharField(
        "最后一行 stdout 摘要", max_length=500, blank=True,
    )
    last_heartbeat_at = models.DateTimeField(
        "最后心跳", null=True, blank=True,
    )

    # ===== 错误 / 日志 =====
    stderr_tail = models.TextField(
        "stderr 末尾（最多 50 行）", blank=True,
    )
    error_message = models.TextField("错误信息", blank=True)

    # ===== 时间戳 =====
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    finished_at = models.DateTimeField("结束时间", null=True, blank=True)
    created_by = models.CharField("创建人", max_length=50, blank=True)

    class Meta:
        db_table = "ext_ddl_ghost_task"
        verbose_name = "gh-ost 任务"
        verbose_name_plural = "gh-ost 任务"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]
        ## CUSTOM-MODIFIED: v0.4.5-alpha 加 unique_together @ 2026-08-06 @ mavis
        ## 同 task_type + 同 workflow 唯一（rebuild 场景 workflow=NULL，允许多条）
        constraints = [
            models.UniqueConstraint(
                fields=["task_type", "workflow"],
                name="uniq_task_type_workflow",
            ),
        ]

    def __str__(self):
        return f"gh-ost #{self.id} for workflow={self.workflow_id} [{self.status}]"

    @property
    def is_terminal(self) -> bool:
        """是否终态（成功/失败/取消/回滚）。"""
        return self.status in ("success", "failed", "cancelled", "rolled_back")

    @property
    def duration_seconds(self) -> int:
        """运行耗时（秒）。未启动或未结束返回 0。"""
        if not self.started_at:
            return 0
        end = self.finished_at or self.updated_at
        return max(0, int((end - self.started_at).total_seconds()))
