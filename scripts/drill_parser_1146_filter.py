"""drill_parser_1146_filter.py — 单元测试 1146 noise 过滤逻辑.

业务: 8/25 task #70 演练时发现 gh-ost cut-over 成功后 cleanup 阶段
     stderr 写 1146 "Table 'X' doesn't exist", parser 写到 task.error_message
     业务 RD 看着别扭 (task 实际成功).

测试 3 个 Case:
  A. 喂带 1146 的 fake log, 验证 error_message 为空 (被过滤)
  B. 喂真错误 (FATAL), 验证 error_message 有内容
  C. 喂混合 log (1146 + FATAL), 验证 error_message 保留 FATAL 信息

跑法 (在 134 dev 端, root):
  cd /opt/archery/prod
  sudo -u archery venv/bin/python scripts/drill_parser_1146_filter.py 2>&1 | tail -50
"""
import os
import sys

sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()

from sql.extensions.ddl_gh_ost.services.parser import parse_ghost_log


def header(title):
    print(f"\n{'='*60}\n{title}\n{'='*60}")


# === Case A: 1146 noise 过滤 (演练时 task #70 实际场景) ===
header("Case A: gh-ost 成功 + cleanup 1146 noise")
fake_log_a = """
2026-08-25 11:38:55 INFO  Migrating `archery_dev`.`accesscard_black_detail`
2026-08-25 11:38:56 INFO  Copy: 1000/241558 0.4%; Applied: 0; Backlog: 0/100; Time: 0s(total)
2026-08-25 11:39:11 INFO  Copy: 241558/241558 100.0%; Applied: 1; Backlog: 0/100; Time: 18s(total)
2026-08-25 11:39:12 INFO  Cut-over complete
2026-08-25 11:39:12 INFO  Done migrating `archery_dev`.`accesscard_black_detail`
2026-08-25 11:39:13 ERROR Error 1146: Table 'archery_dev._accesscard_black_detail_ghc' doesn't exist
"""
result_a = parse_ghost_log(fake_log_a)
print(f"  stage: {result_a.stage}")
print(f"  is_done: {result_a.is_done}")
print(f"  is_failed: {result_a.is_failed}")
print(f"  progress_pct: {result_a.progress_pct}")
print(f"  rows_copied: {result_a.rows_copied}/{result_a.rows_total}")
print(f"  error_message: {result_a.error_message!r}")
print(f"  last_message: {result_a.last_message!r}")

assert result_a.is_done is True, f"期望 done, 实际 {result_a.is_done}"
assert result_a.is_failed is False, f"期望 not failed, 实际 {result_a.is_failed}"
assert result_a.error_message is None, f"期望 error_message 为空 (1146 被过滤), 实际 {result_a.error_message!r}"
print(f"  ✓ Case A PASS (1146 noise 被过滤, error_message 为空)")


# === Case B: 真 FATAL 错误保留 ===
header("Case B: 真 FATAL 错误 (Lost connection) 保留")
fake_log_b = """
2026-08-25 12:00:00 INFO  Migrating `archery_dev`.`accesscard_black_detail`
2026-08-25 12:00:05 INFO  Copy: 1000/241558 0.4%; Applied: 0; Backlog: 0/100
2026-08-25 12:00:10 FATAL Error: Lost connection to MySQL server during query
"""
result_b = parse_ghost_log(fake_log_b)
print(f"  stage: {result_b.stage}")
print(f"  is_done: {result_b.is_done}")
print(f"  is_failed: {result_b.is_failed}")
print(f"  error_message: {result_b.error_message!r}")
print(f"  last_message: {result_b.last_message!r}")

assert result_b.is_failed is True, f"期望 failed, 实际 {result_b.is_failed}"
assert result_b.error_message and "Lost connection" in result_b.error_message, (
    f"期望 error_message 含 'Lost connection', 实际 {result_b.error_message!r}"
)
print(f"  ✓ Case B PASS (FATAL 错误保留)")


# === Case C: 混合 log (1146 noise + FATAL 错误) ===
header("Case C: 混合 log (1146 noise + FATAL 错误)")
fake_log_c = """
2026-08-25 13:00:00 INFO  Migrating `archery_dev`.`test_table`
2026-08-25 13:00:01 ERROR Error 1146: Table 'archery_dev._test_table_ghc' doesn't exist
2026-08-25 13:00:05 FATAL Error: Some real fatal error
"""
result_c = parse_ghost_log(fake_log_c)
print(f"  is_failed: {result_c.is_failed}")
print(f"  error_message: {result_c.error_message!r}")

# FATAL 触发, 1146 之前被过滤
assert result_c.is_failed is True, f"期望 failed (FATAL 触发), 实际 {result_c.is_failed}"
assert "Some real fatal error" in result_c.error_message, (
    f"期望 error_message 含 FATAL, 实际 {result_c.error_message!r}"
)
# 1146 不应在 error_message 里
assert "1146" not in (result_c.error_message or ""), (
    f"1146 应该被过滤, 但 error_message 含 1146: {result_c.error_message!r}"
)
print(f"  ✓ Case C PASS (1146 过滤 + FATAL 保留)")


# === Case D: 其他 ERROR (非 1146, 非 doesn't exist) 保留 ===
header("Case D: 其他 ERROR (非 cleanup noise) 保留")
fake_log_d = """
2026-08-25 14:00:00 INFO  Migrating `archery_dev`.`test_table`
2026-08-25 14:00:05 INFO  Copy: 1000/10000 10.0%
2026-08-25 14:00:10 ERROR Error 1062: Duplicate entry 'xxx' for key 'PRIMARY'
"""
result_d = parse_ghost_log(fake_log_d)
print(f"  error_message: {result_d.error_message!r}")

assert result_d.error_message and "1062" in result_d.error_message, (
    f"1062 (其他 error) 应该保留, 实际 {result_d.error_message!r}"
)
print(f"  ✓ Case D PASS (非 1146 错误保留)")


print(f"\n{'='*60}")
print(f"[ALL OK] 4 Case 单元测试全过")
print(f"  - 1146 noise 过滤 (Case A)")
print(f"  - FATAL 错误保留 (Case B)")
print(f"  - 混合 log 1146 过滤 + FATAL 保留 (Case C)")
print(f"  - 非 1146 错误保留 (Case D)")
print(f"  8/25 教训固化: gh-ost cleanup 1146 noise 不算 fail")
print(f"{'='*60}")
