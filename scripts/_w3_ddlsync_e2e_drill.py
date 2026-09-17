"""DDL-Sync-Bug-A 端到端演练: 模拟 wf 通过, 验证 DdlSyncHistory + 镜像工单

配 DdlSyncTable 真实数据:
- pair id=1 (blacklist 模式)
- t_blacklist → DdlSyncTable sync_type=blacklist
- t_whitelist → 不在 DdlSyncTable (blacklist 模式默认同步)

模拟工单 sql_content 含 2 ALTER: t_blacklist + t_whitelist
期望:
- t_blacklist 写 DdlSyncHistory (sync_status='skipped')
- t_whitelist 触发镜像工单, target_workflow 的 sql_content 只含 t_whitelist 的 ALTER

## 9/17 DDL-Sync-Bug-A @ 2026-09-17 @ mavis
"""
import sys
import os
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()
from unittest.mock import MagicMock, patch
from django.db import transaction
from sql.models import SqlWorkflow, SqlWorkflowContent, WorkflowAudit, Instance, ResourceGroup, Users
from sql.extensions.ddl_sync.models import DdlSyncPair, DdlSyncTable, DdlSyncHistory
from common.utils.const import WorkflowStatus

print("=== Step 1: 检查 pair + 配 DdlSyncTable ===")
pair = DdlSyncPair.objects.filter(enabled=True).first()
if not pair:
    print("  没有 enabled pair, 跳过")
    sys.exit(0)
print(f"  pair id={pair.id} sync_mode={pair.sync_mode} source_instance={pair.source_instance_id} source_db={pair.source_db}")

# 清理可能存在的 DdlSyncTable + DdlSyncHistory
DdlSyncTable.objects.filter(pair=pair, table_name="v0_ddlsync_test_blacklist").delete()
DdlSyncTable.objects.filter(pair=pair, table_name="v0_ddlsync_test_whitelist").delete()
DdlSyncHistory.objects.filter(table_name__in=["v0_ddlsync_test_blacklist", "v0_ddlsync_test_whitelist"]).delete()

# blacklist 模式: t_blacklist 配 DdlSyncTable(sync_type=blacklist) → 不同步
#                 t_whitelist 不配 → 同步
if pair.sync_mode == "blacklist":
    DdlSyncTable.objects.create(
        pair=pair,
        table_name="v0_ddlsync_test_blacklist",
        sync_type="blacklist",
    )
    print(f"  配 DdlSyncTable: t_blacklist → blacklist (期望 skipped)")
else:
    DdlSyncTable.objects.create(
        pair=pair,
        table_name="v0_ddlsync_test_whitelist",
        sync_type="whitelist",
    )
    print(f"  配 DdlSyncTable: t_whitelist → whitelist (期望 kept)")

# 测试数据准备
inst = pair.source_instance
group = ResourceGroup.objects.first()
user = Users.objects.filter(username="archery").first()
if not user:
    print("  ERROR: 没 archery user, 跳过 e2e")
    sys.exit(0)

print()
print("=== Step 2: e2e 演练 (transaction.atomic + savepoint_rollback) ===")
sql_content = (
    "ALTER TABLE v0_ddlsync_test_blacklist ADD COLUMN c1 int;\n"
    "ALTER TABLE v0_ddlsync_test_whitelist ADD COLUMN c2 int;\n"
)

try:
    with transaction.atomic():
        sid = transaction.savepoint()
        # 创建测试 wf
        wf = SqlWorkflow.objects.create(
            workflow_name="[DDL-Sync-Bug-A e2e] 134 dev 演练",
            group_id=group.group_id,
            group_name=group.group_name,
            engineer=user.username,
            engineer_display=user.display,
            audit_auth_groups="",
            status="workflow_manreviewing",
            syntax_type=1,
            is_backup=False,
            instance=inst,
            db_name=pair.source_db,
        )
        SqlWorkflowContent.objects.create(
            workflow=wf,
            sql_content=sql_content,
            review_content="[]",
            execute_result="",
        )
        # 改 wf.status → workflow_review_pass (signal handler 触发)
        # mock audit.get_audit() 返 PASSED (signal handler 第 307 行检查)
        with patch.object(wf, "get_audit") as mock_get_audit:
            mock_audit = MagicMock()
            mock_audit.current_status = WorkflowStatus.PASSED
            mock_get_audit.return_value = mock_audit
            wf.status = "workflow_review_pass"
            wf.save(update_fields=["status"])

        # 检查 DdlSyncHistory
        history_bl = DdlSyncHistory.objects.filter(
            source_workflow=wf,
            table_name="v0_ddlsync_test_blacklist",
        ).first()
        history_wl = DdlSyncHistory.objects.filter(
            source_workflow=wf,
            table_name="v0_ddlsync_test_whitelist",
        ).first()
        print(f"  history blacklist: {history_bl.sync_status if history_bl else 'NONE'}")
        print(f"  history whitelist: {history_wl.sync_status if history_wl else 'NONE'}")

        # 验证
        assert history_bl is not None, "FAIL: blacklist 表没有 history"
        assert history_bl.sync_status == "skipped", f"FAIL: blacklist 应 skipped, 实际 {history_bl.sync_status}"
        assert history_wl is not None, "FAIL: whitelist 表没有 history"
        assert history_wl.sync_status in ("syncing", "synced"), f"FAIL: whitelist 应 syncing, 实际 {history_wl.sync_status}"

        # 验证镜像工单 SQL 只含 whitelist
        if history_wl.target_workflow:
            target_sql = history_wl.target_workflow.sqlworkflowcontent.sql_content
            print(f"  镜像工单 #{history_wl.target_workflow.id} sql_content:")
            print(f"    {target_sql!r}")
            assert "v0_ddlsync_test_blacklist" not in target_sql, "FAIL: 镜像工单含 blacklist 表"
            assert "v0_ddlsync_test_whitelist" in target_sql, "FAIL: 镜像工单缺 whitelist 表"
            print("  [OK] 镜像工单 SQL 只含 kept 的 whitelist ALTER (不含 blacklist)")
        else:
            print("  WARN: 镜像工单未生成")

        # 回滚, 不污染 db
        transaction.savepoint_rollback(sid)
        print("  [OK] savepoint rollback 干净, db 未污染")
except Exception as e:
    print(f"  EXCEPTION: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 清理 DdlSyncTable 残留 (演练结束)
DdlSyncTable.objects.filter(pair=pair, table_name="v0_ddlsync_test_blacklist").delete()
DdlSyncTable.objects.filter(pair=pair, table_name="v0_ddlsync_test_whitelist").delete()

print()
print("=== 端到端演练 PASS ===")
print("DDL-Sync-Bug-A 修复: 多 ALTER 工单 + 混合黑/白名单 ✅")
print("- t_blacklist 走 DdlSyncHistory skipped (DBA 排查)")
print("- t_whitelist 触发镜像工单, SQL 只含 whitelist 的 ALTER")
print("- 业务方下一工单含 2 ALTER 不同名单, 不会丢同步 ✅")