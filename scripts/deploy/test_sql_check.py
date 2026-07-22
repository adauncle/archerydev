"""模拟前端 /api/v1/workflow/sqlcheck/ 调 MySQLEngine.execute_check
验证整条链路：Archery MySQLEngine → GoInceptionEngine (无 instance) → goInception → 目标 MySQL

前端实际调的是 MySQLEngine.execute_check，不是 GoInceptionEngine。
MySQLEngine 内部用 self.inc_engine = GoInceptionEngine() (无 instance)，
然后传 instance 给 inc_engine.execute_check(instance=..., db_name=..., sql=...)。
"""
import os
import sys

sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()

from sql.engines import get_engine
from sql.models import Instance

# 模拟前端的 get_engine(instance=instance)
inst = Instance.objects.get(instance_name="测试 MySQL 8.0")
print(f"目标实例: {inst.instance_name} ({inst.host}:{inst.port}, db_type={inst.db_type})")

engine = get_engine(instance=inst)
print(f"获取到 engine: {type(engine).__name__}")
print(f"  inc_engine = {type(engine.inc_engine).__name__}")
print(f"  inc_engine has instance: {hasattr(engine.inc_engine, 'instance')}")

# 模拟前端 SQL 检测调用
sql = """CREATE TABLE `test` (
  `id` bigint NOT NULL COMMENT 'id',
  `order_id` bigint DEFAULT NULL COMMENT '订单id',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB COMMENT='test';
"""

print()
print("=" * 70)
print("MySQLEngine.execute_check (Archery -> GoInception -> MySQL 链路)")
print("=" * 70)
print(f"SQL:\n{sql}")
print()

try:
    review_set = engine.execute_check(db_name="archery_dev", sql=sql)
    print(f"✓ ReviewSet: error={review_set.error!r} warning={review_set.warning}")
    print(f"  rows count: {len(review_set.rows)}")
    for i, row in enumerate(review_set.rows):
        print(f"  row[{i}]: stage={row.stage_status} "
              f"error_level={row.error_level} sql={row.sql!r}")
        if row.error_message:
            print(f"          err={row.error_message!r}")
except Exception as e:
    print(f"✗ 异常: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()
print("DONE - 回 /submitsql/ 页面点 SQL检测 → 应该看到 goInception 返回的语法/审核结果")
