"""drill_ghost_task_wf_abort_sync.py

业务: 8/13 用户反馈工单 #38 (status=workflow_abort) 的 DdlGhostTask 还是 queued,
     应该跟 wf 一起变 cancelled。

根因: 钉钉 OA 终止路径 (oa_callback_handler.py:331-333) 直接 .update(wf.status='workflow_abort')
     绕过了 sql_workflow.py:524-545 的清理 DdlGhostTask 逻辑。

修法: 抽公共 helper 到 sql/services/ghost_task_sync.py:
        cleanup_pending_ghost_tasks(workflow, operator, reason) -> int
      cancel() 视图 (sql_workflow.py:510) + OA _apply_abort (oa_callback_handler.py:331) 两处都调。

演练 (134 dev 真实数据库, 4 Case):
  1. 验证工单 #38 实际状态 (sanity check)
  2. 调 helper 修工单 #38 → task #46 应该变 cancelled
  3. 验证 helper 对终态 task 是 noop
  4. 验证 helper 对 enable=False 的 task 不影响
  5. 验证 helper 在 CUSTOM_GH_OST_ENABLED=False 时是 noop
  6. (可选) 验证 _apply_abort 路径会触发清理 (单元测试式)

清理: 演练后还原 (task 状态 = 演练前状态)
"""
import os
import sys
import django

sys.path.insert(0, '/opt/archery/prod')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archery.settings')
django.setup()

from django.conf import settings
from django.utils import timezone

from sql.models import SqlWorkflow
from sql.extensions.ddl_gh_ost.models import DdlGhostTask
from sql.services.ghost_task_sync import cleanup_pending_ghost_tasks


def header(title):
    print(f"\n{'='*60}\n{title}\n{'='*60}")


# === Sanity check 工单 #38 实际状态 ===
header("Sanity check 工单 #38 实际状态")
wf = SqlWorkflow.objects.get(id=38)
print(f"  wf.id={wf.id} status={wf.status} ({wf.get_status_display()})")

task = DdlGhostTask.objects.get(workflow_id=38, task_type="ghost")
print(f"  task.id={task.id} status={task.status} type={task.task_type} enabled={task.enabled}")
print(f"  task.error_message={task.error_message!r}")
print(f"  task.finished_at={task.finished_at}")

# 备份 task 演练前状态
backup_status = task.status
backup_error = task.error_message
backup_finished = task.finished_at
print(f"\n  [BACKUP] task.status={backup_status}, finished_at={backup_finished}")

# === Case 1: 调 helper 修工单 #38 (模拟 OA 终止) ===
header("Case 1: 模拟 OA 终止 - 调 cleanup_pending_ghost_tasks")
cleaned = cleanup_pending_ghost_tasks(wf, operator="oa_tester_1", reason="OA 终止: 演练验证")
print(f"  cleaned={cleaned}")
task.refresh_from_db()
print(f"  task.status: {backup_status} -> {task.status}")
print(f"  task.finished_at: {backup_finished} -> {task.finished_at}")
print(f"  task.error_message: {task.error_message!r}")

# 验证
assert cleaned == 1, f"期望清理 1 个 task, 实际 {cleaned}"
assert task.status == "cancelled", f"期望 task 变 cancelled, 实际 {task.status}"
assert task.finished_at is not None, "期望 finished_at 已填"
assert "[aborted] 工单被 oa_tester_1 OA 终止: 演练验证" in task.error_message, (
    f"error_message 缺 abort 标记: {task.error_message!r}"
)
print(f"  [PASS] Case 1: 清理成功, task 变 cancelled ✓")

# === Case 2: 再调一次 (已终态), 应该是 noop ===
header("Case 2: 已终态的 task 再调 helper, 期望 noop")
cleaned2 = cleanup_pending_ghost_tasks(wf, operator="oa_tester_1", reason="二次")
print(f"  cleaned2={cleaned2}")
assert cleaned2 == 0, f"期望 0 (task 已 cancelled), 实际 {cleaned2}"
print(f"  [PASS] Case 2: 已终态 task 不再清理 ✓")

# === Case 3: 临时改 task 状态回 queued, 模拟其他 wf 终止 ===
header("Case 3: 临时改回 queued, 验 helper 能再次清")
task.status = "queued"
task.finished_at = None
task.error_message = ""
task.save()
print(f"  [SETUP] task.status=queued (重置)")

cleaned3 = cleanup_pending_ghost_tasks(wf, operator="mkq", reason="DBA 兜底")
print(f"  cleaned3={cleaned3}")
task.refresh_from_db()
assert task.status == "cancelled", f"期望 cancelled, 实际 {task.status}"
assert "mkq" in task.error_message, "operator 应写进 error_message"
print(f"  [PASS] Case 3: helper 可重复清理 ✓")

# === Case 4: 临时 patch settings CUSTOM_GH_OST_ENABLED=False, helper 应 noop ===
header("Case 4: 临时关掉 CUSTOM_GH_OST_ENABLED, helper 应 noop")
# 重置 task 状态
task.status = "queued"
task.finished_at = None
task.error_message = ""
task.save()
# patch settings
original_flag = settings.CUSTOM_GH_OST_ENABLED
settings.CUSTOM_GH_OST_ENABLED = False
try:
    cleaned4 = cleanup_pending_ghost_tasks(wf, operator="mkq", reason="settings 关闭测试")
finally:
    settings.CUSTOM_GH_OST_ENABLED = original_flag

print(f"  cleaned4={cleaned4}")
task.refresh_from_db()
assert cleaned4 == 0, f"期望 0 (settings 关闭), 实际 {cleaned4}"
assert task.status == "queued", f"期望 task 保持 queued (settings 关闭), 实际 {task.status}"
print(f"  [PASS] Case 4: settings 关闭时 helper noop ✓")

# === 清理: 还原 task 到演练前状态 ===
header("清理: 还原 task 到演练前状态")
task.refresh_from_db()
task.status = backup_status
task.finished_at = backup_finished
task.error_message = backup_error
task.save()
print(f"  [RESTORE] task.status={task.status}, finished_at={task.finished_at}")
print(f"  [RESTORE] task.error_message={task.error_message!r}")

# 验证还原
task.refresh_from_db()
assert task.status == backup_status
assert task.error_message == backup_error
print(f"  [PASS] 还原成功 ✓")

# === 总结 ===
print(f"\n{'='*60}\n[ALL OK] 4 Case 演练完成\n{'='*60}")
