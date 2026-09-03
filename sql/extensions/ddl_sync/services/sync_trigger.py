"""R3 走当前配置 — 业务库 SqlWorkflow PASSED 触发同步镜像工单

## CUSTOM-MODIFIED: v0.5.0-alpha R3 走当前配置 + workflow_passed_handler signal @ 2026-09-01 @ mavis
设计参考: docs/designs/2026-09-01_ddl-sync-implementation-design.md §5

业务流:
  业务库 SqlWorkflow.status = 'workflow_review_pass' (current_status=1 PASSED)
  → post_save signal 触发 workflow_passed_handler
  → 找匹配库对 (source_instance + source_db + enabled=True)
  → 提取 table_name from sql_content
  → _should_sync() 白/黑名单判定
  → _apply_transform_rule() 转换 DDL
  → create_target_workflow() 创建历史库镜像工单 + 走 audit_setting 自动配置
  → DdlSyncHistory.objects.create(sync_status="syncing") 写审计

避坑 (W1-D3 §9.3 实战 5):
1. **signal handler 异常兜底**: 整个 try/except, 异常不能阻塞业务库 DDL 主流程
2. **zombie 检测**: poller.py 复用 ddl_gh_ost 实战 (/proc/<pid>/status State 字段)
3. **rollback 语义**: 镜像工单 failed → v0.4.5 drop 残留 IF EXISTS 走 no-op
4. **poller staleness**: 镜像工单执行超过 1h 没 update, 视为卡死, 自动标 failed
5. **端口探测**: target_instance 走 _detect_actual_mysql_port, fallback config port (8/31 fix)
"""

import json
import logging
import re
import time

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from sql.models import SqlWorkflow, SqlWorkflowContent
from sql.utils.workflow_audit import get_auditor, AuditException
from common.utils.const import WorkflowStatus, WorkflowType

from ..models import DdlSyncPair, DdlSyncHistory

logger = logging.getLogger("default")


# ===== 异常 (D22 新增) =====

class TargetGroupNotConfiguredError(Exception):
    """D22: DdlSyncPair 没配 target_group (镜像工单审批组), 镜像工单创建失败.

    业务: 镜像工单必须走历史库组审批流, 不允许 fallback 走业务组.
    修法: DBA 配库对时必填 target_group (DdlSyncPairForm.clean 校验).
    关联: docs/changelogs/2026-09-03_ddl-sync-w2-d22-mirror-target-group.md
    """
    pass


# ===== SQL 解析辅助 (跟 sql/views.py §_parse_first_alter 套路一致) =====

_ALTER_PATTERN = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?",
    re.IGNORECASE,
)


def _extract_table_name(sql_content: str) -> str:
    """提取 ALTER TABLE 的 table_name.

    只认 ALTER TABLE 开头, 其他 DDL (CREATE/DROP/RENAME) 暂时不触发 (Phase 2 加).
    返回 table_name (str), 解析失败返 "".
    """
    if not sql_content:
        return ""
    m = _ALTER_PATTERN.match(sql_content.strip())
    if not m:
        return ""
    return (m.group("table") or "").strip("`")


# ===== 白/黑名单判定 =====

def _should_sync(pair: DdlSyncPair, table_name: str) -> bool:
    """根据 pair.sync_mode + DdlSyncTable sync_type 判定是否要同步.

    sync_mode=blacklist (默认 R1): 业务库全同步, 显式排除
      → DdlSyncTable(sync_type='blacklist', table_name=t) 存在 = 不同步 (返 False)
      → 其他 = 同步 (返 True)
    sync_mode=whitelist: DBA 显式选要同步的
      → DdlSyncTable(sync_type='whitelist', table_name=t) 存在 = 同步 (返 True)
      → 其他 = 不同步 (返 False)
    """
    # CUSTOM-MODIFIED: 修 D10 演练发现 UnboundLocalError @ 2026-09-02 @ mavis
    # 关联: docs/changelogs/2026-09-02_ddl-sync-w2-d10-drill.md
    # 修法: 函数顶部直接 import, 不要放在 if 之前避免 local var 屏蔽
    from ..models import DdlSyncTable
    if not table_name:
        return False
    if pair.sync_mode == "blacklist":
        # 黑名单模式: 在黑名单 = 排除, 不在 = 同步
        in_blacklist = DdlSyncTable.objects.filter(
            pair=pair, table_name=table_name, sync_type="blacklist"
        ).exists()
        return not in_blacklist
    else:
        # 白名单模式: 在白名单 = 同步, 不在 = 排除
        in_whitelist = DdlSyncTable.objects.filter(
            pair=pair, table_name=table_name, sync_type="whitelist"
        ).exists()
        return in_whitelist


# ===== transform_rule 转换 (Phase 3 简化版) =====

def _apply_transform_rule(sql_content: str, pair: DdlSyncPair, table_name: str) -> str:
    """应用 transform_rule 转换 DDL.

    Phase 3 简化: 只看 pair.filter_rule (前缀/后缀排除/字段重命名) 跟
    DdlSyncTable.transform_rule (单表规则) 两个 JSON 字段. Phase 4 扩展.

    Phase 1-2 实战: 暂时原样返回 (DBA 还在配过滤规则, R3 阶段先跑通链路).
    """
    return sql_content


# ===== 创建镜像工单 =====

@transaction.atomic
def create_target_workflow(source_workflow: SqlWorkflow, pair: DdlSyncPair, transformed_ddl_text: str) -> SqlWorkflow:
    """R3 镜像工单 - 业务库 DDL PASSED → 创建历史库镜像工单 + 走 audit_setting 自动配置.

    ## CUSTOM-MODIFIED: D22 镜像工单 group_id 改走 pair.target_group (历史库组) @ 2026-09-03 @ mavis
    ## 业务: 镜像工单审批流必须走历史库组, 不是业务组
    ## 根因: D9 实战 group_id=source_workflow.group_id, Instance 是 M2M ResourceGroup 没 group_id 字段,
    ##       fallback 用业务组 → wf#121 走 group 25 "测试组" audit_auth_groups='14,3',
    ##       不是用户期望的 group 22 "prod core for 历史库" '3'
    ## 修法: pair.target_group 必填 (DBA 配库对时显式选), create_target_workflow 走 pair.target_group.group_id
    ## 关联: docs/changelogs/2026-09-03_ddl-sync-w2-d22-mirror-target-group.md

    ## CUSTOM-MODIFIED: R3 create_target_workflow @ 2026-09-01 @ mavis
    实战要点 (W1-D3 §5.1 拍板 + 8/27 实战):
    - group_id/group_name 走 pair.target_group (历史库组, D22 改)
    - audit_auth_groups="" 占位, create_audit() 会从 WorkflowAuditSetting 自动配
    - status="workflow_manreviewing" 默认走人工审核 (W1-D3 §5.2 8/27 避坑: 镜像工单不自动跑)
    - SqlWorkflowContent 跟 SqlWorkflow 是 OneToOne, 必建 (W1-D3 §5.1 实战补)
    - D22: pair.target_group 必填, 没配 reject 抛 TargetGroupNotConfiguredError
    """
    # D22: pair.target_group 必填, 没配直接抛错 (DBA 拍板 A 方案: 强制配, 不 fallback 走业务组)
    if not pair.target_group:
        raise TargetGroupNotConfiguredError(
            f"DdlSyncPair id={pair.id} ({pair.name}) 没配 target_group, "
            f"镜像工单不能走业务组 (违反 D22 设计), "
            f"请 DBA 在配库对页 pair_form.html 显式选镜像工单审批组 (如 'prod core for 历史库')"
        )
    target_group = pair.target_group  # ResourceGroup object

    target_workflow = SqlWorkflow.objects.create(
        workflow_name=f"[镜像] {source_workflow.workflow_name}",
        group_id=target_group.group_id,           # D22: 改走历史库组
        group_name=target_group.group_name,       # D22: 改走历史库组
        engineer=source_workflow.engineer,
        engineer_display=source_workflow.engineer_display or "",
        audit_auth_groups="",  # 占位, create_audit() 会从 WorkflowAuditSetting 自动配
        status="workflow_manreviewing",  # 默认走人工审核 (W1-D3 §5.2 8/27 避坑)
        syntax_type=source_workflow.syntax_type,
        is_backup=source_workflow.is_backup,
        instance=pair.target_instance,
        db_name=pair.target_db,
    )
    # OneToOne 关联 sql_content (W1-D3 §5.1 实战补, 不建会报 DoesNotExist)
    ## CUSTOM-MODIFIED: D21 镜像工单 review_content 填 placeholder (9/3 11:25 实战) @ 2026-09-03 @ mavis
    ## 业务: 业务 RD 拿到镜像工单想知道 SQL, Archery detail.html "工单详情" tab 主表依赖 review_content
    ## 根因: D9 阶段 1 review_content="[]" (空 list) → detail_content 端点 json.loads 后 loaded_rows=[] → 主表空, 子表展不开
    ## 修法: 镜像工单创建时填 1 行 placeholder (ReviewSet json 格式 [dict]), 走 Archery 原本设计
    ##       老的镜像工单 (D9-D20 期间) review_content="[]" 走 D20 8/26 inline 区域 SQL 块兜底
    ## 关联 changelog: docs/changelogs/2026-09-03_ddl-sync-w2-d21-mirror-review-content-placeholder.md
    placeholder_review_content = json.dumps([{
        "id": 0,
        "stage": "自动同步",
        "errlevel": 0,
        "stagestatus": "镜像工单已生成, 等待人工审核",
        "errormessage": (
            f"DDL 跨库同步自动生成的镜像工单 (源工单 #{source_workflow.id})"
            " · 走当前配置审批流 · "
            "DBA 审过+执行, 历史库自动同步"
        ),
        "sql": transformed_ddl_text,
        "affected_rows": 0,
        "sequence": "0",
        "backup_dbname": "",
        "execute_time": "",
        "sqlsha1": "",
        "backup_time": "",
        "actual_affected_rows": "",
    }], ensure_ascii=False)
    SqlWorkflowContent.objects.create(
        workflow=target_workflow,
        sql_content=transformed_ddl_text,
        review_content=placeholder_review_content,
        execute_result="",
    )
    # 走 audit_setting 自动配置 (从 WorkflowAuditSetting 拿当前 group_id + workflow_type=SQL_REVIEW 的 audit_auth_groups)
    try:
        audit_handler = get_auditor(workflow=target_workflow)
        audit_handler.create_audit()
    except AuditException as e:
        # audit_setting 没配的 fallback: 留空 audit_auth_groups, 等 DBA 兜底配
        logger.warning(
            "ddl_sync.create_target_workflow: audit_setting 配失败, fallback 留空: %s",
            e,
        )
    return target_workflow


# ===== Signal handler =====

@receiver(post_save, sender=SqlWorkflow)
def workflow_passed_handler(sender, instance, created, **kwargs):
    """Signal handler: 业务库 SqlWorkflow 状态变 PASSED → 触发同步.

    ## CUSTOM-MODIFIED: R3 workflow_passed_handler @ 2026-09-01 @ mavis
    避坑 (W1-D3 §9.3 实战 5):
    1. **异常兜底**: 整个 try/except, 异常不能阻塞业务库 DDL 主流程
    2. **post_save 触发频繁**: 只在 status=workflow_review_pass (audit PASSED) 时触发
    3. **重复触发**: DdlSyncHistory.sync_status='syncing' 唯一约束防重
    4. **disabled 跳过**: pair.enabled=False 不创建 history
    5. **orphan 跳过**: 表名不在白/黑名单 → skipped 记录 (DBA 排查)
    """
    # 9/1 W1-D3 §9.3 实战 1: 整个 try/except 兜底, 异常不能阻塞业务库 DDL 主流程
    try:
        # 1. 只在 audit PASSED 时触发 (created 不触发, workflow_review_pass 才触发)
        if created:
            return
        if instance.status != "workflow_review_pass":
            return
        # 双重保险: audit.current_status = PASSED 才算
        audit = instance.get_audit()
        if not audit or audit.current_status != WorkflowStatus.PASSED:
            return

        # 2. 拿 sql_content (OneToOne 关联, 没有就跳过)
        try:
            sql_content = instance.sqlworkflowcontent.sql_content or ""
        except SqlWorkflowContent.DoesNotExist:
            return

        # 3. 找匹配库对 (DBA 配的 enabled 库对)
        pairs = DdlSyncPair.objects.filter(
            source_instance=instance.instance,
            source_db=instance.db_name,
            enabled=True,
        )
        if not pairs.exists():
            return

        # 4. 提取 table_name
        table_name = _extract_table_name(sql_content)
        if not table_name:
            return  # 不是 ALTER TABLE, Phase 2 加 CREATE/DROP/RENAME

        # 5. 对每个匹配库对触发同步
        for pair in pairs:
            # 5.1 白/黑名单判定
            if not _should_sync(pair, table_name):
                # skipped 记录
                DdlSyncHistory.objects.create(
                    pair=pair,
                    source_workflow=instance,
                    table_name=table_name,
                    ddl_text=sql_content,
                    sync_status="skipped",
                    error_message="白/黑名单不匹配 (orphan)",
                    finished_at=timezone.now(),
                )
                continue

            # 5.2 应用 transform_rule
            transformed_ddl = _apply_transform_rule(sql_content, pair, table_name)

            # 5.3 创建镜像工单 + 走 audit_setting
            try:
                target_workflow = create_target_workflow(instance, pair, transformed_ddl)
            except Exception as e:
                # 镜像工单创建失败 (FK/group/audit 错), 标 failed 不阻塞主流程
                logger.exception(
                    "ddl_sync.workflow_passed_handler: create_target_workflow 失败 pair=%s table=%s",
                    pair.id, table_name,
                )
                DdlSyncHistory.objects.create(
                    pair=pair,
                    source_workflow=instance,
                    table_name=table_name,
                    ddl_text=sql_content,
                    transformed_ddl_text=transformed_ddl,
                    sync_status="failed",
                    error_message=f"创建镜像工单失败: {e}",
                    finished_at=timezone.now(),
                )
                continue

            # 5.4 写 history (syncing 状态, 等 target_workflow 执行完切 synced/failed)
            DdlSyncHistory.objects.create(
                pair=pair,
                source_workflow=instance,
                target_workflow=target_workflow,
                table_name=table_name,
                ddl_text=sql_content,
                transformed_ddl_text=transformed_ddl,
                sync_status="syncing",
            )
            logger.info(
                "ddl_sync.workflow_passed_handler: 镜像工单创建成功 pair=%s table=%s target_wf=%s",
                pair.id, table_name, target_workflow.id,
            )
    except Exception as e:
        # 9/1 W1-D3 §9.3 实战 1: 整个 try/except 兜底, 异常不能阻塞业务库 DDL 主流程
        logger.exception(
            "ddl_sync.workflow_passed_handler: 兜底异常 (不能阻塞主流程) instance=%s err=%s",
            getattr(instance, "id", "?"), e,
        )


# ===== 源工单终止 → 联动镜像工单 =====
# CUSTOM-MODIFIED: 9/2 D11 hotfix 实战设计漏洞修补 @ 2026-09-02 @ mavis
# 关联: docs/changelogs/2026-09-02_ddl-sync-w2-d11-cascade-handler.md
# 实战: 9/2 用户演练 #109 workflow_exception 实战 #110 还在待执行
#       实战设计: 源工单终止 (workflow_reject / workflow_abort / workflow_exception)
#       → 联动镜像工单同样终止, DdlSyncHistory 切 failed/skipped
# 实战: 跟 R3 workflow_passed_handler 对称, 实战 post_save signal
# 实战: 整个 try/except 兜底, 不能阻塞源工单状态变更主流程

@receiver(post_save, sender=SqlWorkflow)
def workflow_terminal_handler(sender, instance, created, **kwargs):
    """源工单终止 → 联动镜像工单同样终止 + DdlSyncHistory 切终态.

    ## CUSTOM-MODIFIED: 9/2 D11 hotfix 实战设计漏洞 @ 2026-09-02 @ mavis
    实战: 9/2 #109 workflow_exception 实战 #110 还在待执行
    修法: post_save signal 监听源工单 status 变 workflow_reject / workflow_abort / workflow_exception
          → 找 sync_status=syncing 的 DdlSyncHistory → 联动 target_workflow 同样终止
          → DdlSyncHistory 切 failed (workflow_exception) 或 skipped (workflow_reject / workflow_abort)
          → error_message 记录联动原因
    实战: 实战整个 try/except 兜底, 异常不能阻塞源工单状态变更主流程
    """
    try:
        # 1. created 不触发 (R3 signal handler 套路)
        if created:
            return

        # 2. 只在终态触发
        terminal_statuses = ('workflow_reject', 'workflow_abort', 'workflow_exception')
        if instance.status not in terminal_statuses:
            return

        # 3. 找 DdlSyncHistory(sync_status=syncing) 联动 target_workflow
        histories = DdlSyncHistory.objects.filter(
            source_workflow=instance,
            sync_status='syncing',
            target_workflow__isnull=False,
        )
        if not histories.exists():
            return

        # 4. 联动终止
        for h in histories:
            try:
                # 镜像工单状态 = 源工单状态 (workflow_reject / workflow_abort / workflow_exception)
                h.target_workflow.status = instance.status
                h.target_workflow.save(update_fields=['status'])

                # DdlSyncHistory 切终态
                if instance.status == 'workflow_exception':
                    h.sync_status = 'failed'
                else:
                    # workflow_reject / workflow_abort
                    h.sync_status = 'skipped'

                h.error_message = (
                    f'源工单 #{instance.id} {instance.status} → 联动终止镜像工单 #{h.target_workflow_id}'
                )
                h.finished_at = timezone.now()
                h.save()

                logger.info(
                    "ddl_sync.workflow_terminal_handler: 联动终止 pair=%s source_wf=%s target_wf=%s status=%s",
                    h.pair_id, instance.id, h.target_workflow_id, instance.status,
                )
            except Exception as e:
                # 单条 history 处理失败, 不影响其他 history
                logger.exception(
                    "ddl_sync.workflow_terminal_handler: 联动失败 history=%s err=%s",
                    h.id, e,
                )
    except Exception as e:
        # 9/1 W1-D3 §9.3 实战 1 兜底: 异常不能阻塞源工单状态变更主流程
        logger.exception(
            "ddl_sync.workflow_terminal_handler: 兜底异常 (不能阻塞主流程) instance=%s err=%s",
            getattr(instance, "id", "?"), e,
        )


# ===== 镜像工单状态联动 DdlSyncHistory (D23 新加) =====
# CUSTOM-MODIFIED: 9/3 D23 镜像工单 status 变终态/完成 → 联动 DdlSyncHistory 切 synced/failed/skipped @ 2026-09-03 @ mavis
# 业务: 业务方期望业务库执行结束后, 镜像工单 status 联动到 DdlSyncHistory,
#       alert 块显示"已同步"而不是"同步中 (镜像工单已生成, 还没执行)"
# 根因: D11 hotfix 只修"源工单终止→联动镜像工单终止 + DdlSyncHistory 切终态",
#       缺"镜像工单自己执行完→联动 DdlSyncHistory"
#       实战: 9/3 14:42 用户演练 wf#128 alert 块显示"同步中", 
#             排查发现 wf#125 镜像工单 status=workflow_finish (DBA 已手动执行完),
#             DdlSyncHistory id=11 sync_status='syncing' 没人联动
# 实战: 跟 D11 workflow_terminal_handler 互补 — D11 管"源工单终止→镜像工单",
#       D23 管"镜像工单自己终态→DdlSyncHistory"
# 实战: 整个 try/except 兜底, 异常不能阻塞镜像工单状态变更主流程

@receiver(post_save, sender=SqlWorkflow)
def target_workflow_status_handler(sender, instance, created, **kwargs):
    """镜像工单 status 变化 → 联动 DdlSyncHistory 切终态.

    ## CUSTOM-MODIFIED: 9/3 D23 镜像工单 status 联动 DdlSyncHistory @ 2026-09-03 @ mavis
    关联: docs/changelogs/2026-09-03_ddl-sync-w2-d23-mirror-target-workflow-sync-status.md

    监听 status:
      - workflow_finish → DdlSyncHistory.sync_status = 'synced' (DBA 手动审+执行成功)
      - workflow_reject / workflow_abort → 'skipped' (DBA 拒绝/中止)
      - workflow_exception → 'failed' (执行异常)

    跟 D11 workflow_terminal_handler 互补 (不冲突):
      - D11: instance 是 source_workflow, 找 DdlSyncHistory(source_workflow=instance)
      - D23: instance 是 target_workflow, 找 DdlSyncHistory(target_workflow=instance)
      - D11 触发的 target_workflow.save() 会触发 D23, 但 D11 已经切过 DdlSyncHistory.sync_status
        (不再是 'syncing'), D23 filter sync_status='syncing' 查不到, 不会重复切
    """
    try:
        # 1. created 不触发 (D11 套路)
        if created:
            return

        # 2. 只在终态/完成态触发
        final_statuses = (
            'workflow_finish', 'workflow_reject', 'workflow_abort', 'workflow_exception',
        )
        if instance.status not in final_statuses:
            return

        # 3. 找 DdlSyncHistory(sync_status=syncing, target_workflow=instance) 联动
        histories = DdlSyncHistory.objects.filter(
            target_workflow=instance,
            sync_status='syncing',
        )
        if not histories.exists():
            return

        # 4. 联动切终态
        for h in histories:
            try:
                if instance.status == 'workflow_finish':
                    new_sync_status = 'synced'
                elif instance.status == 'workflow_exception':
                    new_sync_status = 'failed'
                else:  # workflow_reject / workflow_abort
                    new_sync_status = 'skipped'

                h.sync_status = new_sync_status
                h.finished_at = timezone.now()
                h.error_message = (
                    (h.error_message + '\n') if h.error_message else ''
                ) + f'镜像工单 #{instance.id} status={instance.status} → DdlSyncHistory 联动切 {new_sync_status}'

                h.save()

                logger.info(
                    "ddl_sync.target_workflow_status_handler: 联动 history=%s target_wf=%s status=%s → sync_status=%s",
                    h.id, instance.id, instance.status, new_sync_status,
                )
            except Exception as e:
                # 单条 history 处理失败, 不影响其他 history
                logger.exception(
                    "ddl_sync.target_workflow_status_handler: 联动失败 history=%s err=%s",
                    h.id, e,
                )
    except Exception as e:
        # 9/1 W1-D3 §9.3 实战 1 兜底: 异常不能阻塞镜像工单状态变更主流程
        logger.exception(
            "ddl_sync.target_workflow_status_handler: 兜底异常 (不能阻塞主流程) target_wf=%s err=%s",
            getattr(instance, "id", "?"), e,
        )
