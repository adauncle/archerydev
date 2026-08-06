"""
gh-ost 影子表 7 天自动清理。

设计参考：docs/designs/2026-08-05_gh-ost-product-design.html §9
"影子表保留 7 天：cut-over 失败时人工回滚的最后机会"

用法：
    python manage.py cleanup_ghost_tables                    # 用默认 7 天
    python manage.py cleanup_ghost_tables --days 3           # 3 天
    python manage.py cleanup_ghost_tables --dry-run          # 只打印不删

django-q2 调度（archery settings 已有 Q_CLUSTER）：
    from django_q.tasks import schedule
    schedule("sql.extensions.ddl_gh_ost.management.commands.cleanup_ghost_tables.cleanup_ghost_tables",
             schedule_type="D",  # 每天
             next_run=...,
             repeats=-1)
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from sql.extensions.ddl_gh_ost.models import DdlGhostTask
from sql.extensions.ddl_gh_ost.services.db import _get_creds
import pymysql

logger = logging.getLogger("default")


class Command(BaseCommand):
    help = "清理 gh-ost 失败/取消后超过 N 天的影子表"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=7,
            help="保留天数（默认 7 天）",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="只扫描不真删",
        )

    def handle(self, *args, **opts):
        days = opts["days"]
        dry_run = opts["dry_run"]
        cutoff = timezone.now() - timedelta(days=days)

        self.stdout.write(f"清理阈值：{cutoff.isoformat()}（{days} 天前）")
        candidates = DdlGhostTask.objects.filter(
            status__in=("failed", "cancelled", "rolled_back"),
            finished_at__lt=cutoff,
            ghost_table_name__gt="",  # not empty
        )
        self.stdout.write(f"候选 task 数: {candidates.count()}")

        total_dropped = 0
        total_errors = 0
        for task in candidates:
            self.stdout.write(
                f"  task #{task.id} db={task.db_name} table={task.table_name} "
                f"ghost={task.ghost_table_name} finished_at={task.finished_at}"
            )
            if dry_run:
                continue
            if not task.workflow_id:
                continue
            instance = task.workflow.instance
            try:
                user, password, (host, port) = _get_creds(instance)
                conn = pymysql.connect(
                    host=host, port=port, user=user, password=password,
                    database=task.db_name, connect_timeout=5, autocommit=True,
                )
                try:
                    with conn.cursor() as cur:
                        for tbl in [task.ghost_table_name, f"_{task.table_name}_del"]:
                            if not tbl:
                                continue
                            try:
                                cur.execute(f"DROP TABLE IF EXISTS `{task.db_name}`.`{tbl}`")
                                self.stdout.write(self.style.SUCCESS(f"    dropped: {tbl}"))
                                total_dropped += 1
                            except Exception as exc:  # noqa: BLE001
                                self.stdout.write(self.style.ERROR(f"    error {tbl}: {exc}"))
                                total_errors += 1
                finally:
                    conn.close()
                # 清空 ghost_table_name 表示清理过
                task.ghost_table_name = ""
                task.save(update_fields=["ghost_table_name"])
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"  task #{task.id} connect failed: {exc}"))
                total_errors += 1

        self.stdout.write(self.style.SUCCESS(
            f"完成：dropped={total_dropped} errors={total_errors}"
        ))
