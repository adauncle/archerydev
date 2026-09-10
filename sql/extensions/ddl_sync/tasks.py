"""DDL 跨库同步 定时任务.

## CUSTOM-MODIFIED: v0.6.0-alpha-1 自动归档 1 年前审计日志 @ 2026-09-10 @ mavis
## 关联: docs/plans/2026-09-10_d35-oplog-roadmap.html 阶段 1.6 (Q2 自动归档)
## 拍板: Q2 选 B 1 年保留周期, 1 年后自动归档 (delete 主表, DBA 手动冷备份)
##       业务方实战: DBA 每月手动 mysqldump ext_ddl_sync_audit_log -> /backup/audit_log/
## 定时: 每天凌晨 3 点跑 (业务方低峰期)

Celery 兼容: 跟 dingtalk_oa/tasks.py 一样 try/except 装饰器兼容
"""

import logging
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.utils import timezone

# 兼容 Celery: 装了 celery 用真 @shared_task, 没装就用 noop
try:
    from celery import shared_task  # type: ignore[import]
except ImportError:
    def shared_task(func):
        func.delay = lambda *a, **kw: func(*a, **kw)
        func.apply_async = lambda *a, **kw: func()
        return func


from .models import DdlSyncAuditLog  # noqa: E402

logger = logging.getLogger(__name__)

# django-q2 schedule 名
ARCHIVE_SCHEDULE_NAME = "ddl_sync_audit_log_archive"


@shared_task
def archive_old_audit_logs() -> int:
    """每天凌晨扫 1 年前 DdlSyncAuditLog, delete (DBA 月度 mysqldump 兜底).

    拍板: Q2 选 B 1 年保留周期
    ## CUSTOM-MODIFIED: v0.6.0-alpha-1 1 年前 delete @ 2026-09-10 @ mavis
    ## 关联: docs/plans/2026-09-10_d35-oplog-roadmap.html Q2
    ## 实战兜底: DBA 每月手动 mysqldump 一次 ext_ddl_sync_audit_log -> /backup/audit_log/

    Returns:
        本次删除的条数 (用于监控 / 单元测试断言)
    """
    keep_days = int(getattr(settings, "CUSTOM_DDL_SYNC_AUDIT_KEEP_DAYS", 365))
    threshold = timezone.now() - timedelta(days=keep_days)

    qs = DdlSyncAuditLog.objects.filter(created_at__lt=threshold)
    count = qs.count()
    if count > 0:
        qs.delete()
        logger.warning(
            "DDL 同步审计日志自动归档: 删除 %s 条 (1 年前) — DBA 兜底 mysqldump /backup/audit_log/",
            count,
        )
    return count


def add_archive_schedule() -> Optional[object]:
    """注册归档 schedule (每天凌晨 3 点).

    Returns:
        django_q.models.Schedule 实例; 未启用 django-q2 时返回 None.

    使用方式 (部署后 ops 跑一次):
        python manage.py shell <<EOF
        from sql.extensions.ddl_sync.tasks import add_archive_schedule
        add_archive_schedule()
        EOF
    """
    try:
        from django_q.models import Schedule
        from django_q.tasks import schedule
    except ImportError:
        logger.warning("django-q2 未安装, 跳过 add_archive_schedule")
        return None

    # 已有则删
    try:
        existing = Schedule.objects.get(name=ARCHIVE_SCHEDULE_NAME)
        Schedule.delete(existing)
    except Schedule.DoesNotExist:
        pass

    return schedule(
        "sql.extensions.ddl_sync.tasks.archive_old_audit_logs",
        name=ARCHIVE_SCHEDULE_NAME,
        schedule_type="I",  # I = interval (避开 croniter 依赖, 134 dev / 110 prod 都没装)
        # 每天跑一次 (24 * 60 = 1440 分钟), 业务方低峰期
        minutes=1440,
        repeats=-1,
        timeout=-1,
    )
