"""钉钉 OA 智能工作流 driver。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §6.4 / §10.4

核心方法（继承自 :class:`AuditDriver`）：

* ``start(workflow, audit, flow)``         调 ``topapi.processinstance.create`` 发起审批；
                                            失败按 v0.7 §10.4 重试 + 降级。
* ``apply_decision(audit, decision, ...)``  本地推进后，钉钉加备注 / 终止流程。
* ``terminate(audit, ...)``                  钉钉侧撤回。
* ``get_status(audit)``                      对账用，调 ``topapi.processinstance.get``。
* ``handle_callback(request)``              委托给 :mod:`sql.extensions.dingtalk_oa.callback`。

降级流程见 ``_fallback()``，v0.7 §10.4.3 第 1 款。
"""

import logging
from typing import List, Optional

import requests
from django.conf import settings as django_settings

from sql.extensions.audit_drivers.base import AuditDriver, DriverStartResult

from ..models import DingtalkOaEventLog, WorkflowAuditExternal
from ..security.crypto import DingtalkCrypto
from ..security.guard import get_oa_access_token

logger = logging.getLogger(__name__)


class DingtalkApiError(Exception):
    """钉钉开放平台 API 业务错误（含 errcode != 0）。"""

    def __init__(self, endpoint: str, payload: dict):
        self.endpoint = endpoint
        self.payload = payload
        errcode = payload.get("errcode")
        errmsg = payload.get("errmsg") or payload.get("message")
        super().__init__(f"{endpoint} failed: errcode={errcode} errmsg={errmsg} payload={payload}")


class DingtalkOaDriver(AuditDriver):
    """钉钉 OA 智能工作流 driver。

    关键约束：
        * ``start()`` 失败按 :ref:`v0.7 §10.4` 重试 + 降级，不阻塞业务（除非
          ``CUSTOM_DINGTALK_OA_FALLBACK_ENABLED=False`` 显式要求阻塞）。
        * 所有钉钉 API 调用都吃掉异常记 logger（不能让本地审批被远程故障
          拖垮）。对账失败由 :mod:`sql.extensions.dingtalk_oa.tasks` 兜底。
        * SQL 全文**不**通过表单传给钉钉，只传摘要 + Archery 详情链接。
    """

    name = "dingtalk_oa"

    # ---------- 入口方法 ----------

    def start(self, workflow, audit, flow) -> DriverStartResult:
        """发起钉钉 OA 审批。

        流程：
            1. 构造脱敏表单（不含 SQL 全文）；
            2. 调 ``topapi.processinstance.create``（最多
               ``CUSTOM_DINGTALK_OA_RETRY_TIMES`` 次重试）；
            3. 成功：写 ``WorkflowAuditExternal`` 关联 + 记 ``DingtalkOaEventLog``。
            4. 失败且 ``CUSTOM_DINGTALK_OA_FALLBACK_ENABLED=True``：
               写 FALLBACK 关联、改 ``workflow.audit_driver='archery'``、
               推 DBA 群告警、记 FALLBACK_AT_START 事件。
            5. 失败且 ``CUSTOM_DINGTALK_OA_FALLBACK_ENABLED=False``：
               抛 ``DingtalkApiError``，阻塞业务（高一致性场景）。
        """
        max_retries = int(getattr(django_settings, "CUSTOM_DINGTALK_OA_RETRY_TIMES", 3))
        timeout = int(getattr(django_settings, "CUSTOM_DINGTALK_OA_TIMEOUT_SECONDS", 10))
        fallback_enabled = bool(
            getattr(django_settings, "CUSTOM_DINGTALK_OA_FALLBACK_ENABLED", True)
        )

        if not flow.dingtalk_process_code:
            # 模板编码缺失是配置错误，触发降级而不是死循环重试
            return self._fallback(
                workflow, audit, flow,
                "dingtalk_process_code 为空，无法发起 OA 审批",
            )

        form_components = self._build_form(workflow, audit, flow)
        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                process_instance_id = self._call_dingtalk_api(
                    "topapi.processinstance.create",
                    timeout=timeout,
                    process_code=flow.dingtalk_process_code,
                    originator_user_id=self._get_originator_userid(workflow),
                    form_component_list=form_components,
                )
                if not process_instance_id:
                    raise DingtalkApiError(
                        "topapi.processinstance.create",
                        {"errcode": -1, "errmsg": "process_instance_id 缺失"},
                    )

                # 写关联
                WorkflowAuditExternal.objects.create(
                    audit=audit,
                    source=self.name,
                    external_process_instance_id=process_instance_id,
                    external_process_code=flow.dingtalk_process_code,
                    external_status="RUNNING",
                    payload={"flow_code": flow.code, "attempt": attempt},
                )
                # 锁 driver 到工单
                workflow.audit_driver = self.name
                workflow.audit_fallback_reason = ""
                workflow.save(update_fields=["audit_driver", "audit_fallback_reason"])

                DingtalkOaEventLog.objects.create(
                    audit=audit,
                    event_type="OA_START",
                    event_id=f"start-{audit.audit_id}-{process_instance_id}",
                    payload={
                        "flow": flow.code,
                        "process_instance_id": process_instance_id,
                        "attempt": attempt,
                    },
                    processed=True,
                )
                return DriverStartResult(external_id=process_instance_id)

            except DingtalkApiError as e:
                last_error = e
                logger.warning(
                    "dingtalk OA start attempt %s/%s failed: %s",
                    attempt, max_retries, e,
                )
                if attempt >= max_retries:
                    break
            except (requests.RequestException, ValueError) as e:
                # 网络层 / 数据解析异常 —— 立即降级（重试无意义）
                logger.exception("dingtalk OA start unexpected error: %s", e)
                return self._fallback(workflow, audit, flow, f"unexpected: {e}")

        # 重试耗尽
        return self._fallback(
            workflow, audit, flow,
            f"重试 {max_retries} 次失败：{last_error}",
        )

    def apply_decision(self, audit, decision: str, actor, remark: str):
        """本地推进后，通知钉钉。

        * ``Decision.PASS``   -> 钉钉加备注；
        * ``Decision.REJECT`` -> 钉钉加备注 + 终止流程，本地标记 TERMINATED。

        找不到 ``WorkflowAuditExternal`` 表示本工单**未发**过 OA，no-op 返回。
        """
        try:
            ext = WorkflowAuditExternal.objects.get(audit=audit)
        except WorkflowAuditExternal.DoesNotExist:
            return None

        actor_display = getattr(actor, "display", "") or str(actor)
        if decision == "pass":
            self._add_comment_safe(
                ext,
                f"[Archery] 节点 {actor_display} 通过：{remark}",
            )
        elif decision == "reject":
            self._add_comment_safe(
                ext,
                f"[Archery] {actor_display} 驳回：{remark}",
            )
            self._terminate_safe(ext, f"[Archery] 驳回：{remark}")
            ext.external_status = "TERMINATED"
            ext.save(update_fields=["external_status"])
        else:
            logger.warning("apply_decision: unknown decision=%r", decision)
        return None

    def terminate(self, audit, actor, remark: str):
        """用户主动撤回：钉钉侧终止流程。"""
        try:
            ext = WorkflowAuditExternal.objects.get(audit=audit)
        except WorkflowAuditExternal.DoesNotExist:
            return None

        actor_display = getattr(actor, "display", "") or str(actor)
        self._add_comment_safe(ext, f"[Archery] {actor_display} 撤回：{remark}")
        self._terminate_safe(ext, f"[Archery] 撤回：{remark}")
        ext.external_status = "TERMINATED"
        ext.save(update_fields=["external_status"])

    def get_status(self, audit) -> dict:
        """对账用：调 ``topapi.processinstance.get``。

        失败时返回 ``{"status": "UNKNOWN", "error": "..."}`` 而不是抛异常
        —— 对账 task 需要优雅处理失败。
        """
        try:
            ext = WorkflowAuditExternal.objects.get(audit=audit)
        except WorkflowAuditExternal.DoesNotExist:
            return {"status": "NOT_STARTED"}

        try:
            return self._call_dingtalk_api(
                "topapi.processinstance.get",
                process_instance_id=ext.external_process_instance_id,
            ) or {"status": "UNKNOWN"}
        except (DingtalkApiError, requests.RequestException, ValueError) as e:
            logger.warning("get_status for audit=%s failed: %s", audit.audit_id, e)
            return {"status": "UNKNOWN", "error": str(e)}

    def handle_callback(self, request):
        """钉钉 OA 回调入口（v0.7 §10.5）。

        委托给 :func:`sql.extensions.dingtalk_oa.callback.dingtalk_oa_callback`，
        单独放 callback.py 是为了 URLConf 直接挂载。
        """
        # 延迟 import 避免循环
        from .. import callback as callback_module

        return callback_module.dingtalk_oa_callback(request)

    # ---------- 私有：表单 ----------

    def _build_form(self, workflow, audit, flow) -> List[dict]:
        """构造脱敏后的钉钉表单组件。

        原则（v0.7 §10.5.4）：
            * SQL 全文**不**上传，只传前 200 字符摘要；
            * 数据库密码、token 等敏感字段不出现；
            * 完整 SQL 通过 Archery 链接查看（需要登录态）。
        """
        # 延迟 import 避免 settings 未就绪
        from ..services.sql_type_detect import extract_affected_rows, extract_affected_tables

        content_obj = getattr(workflow, "sqlworkflowcontent", None)
        sql_content = getattr(content_obj, "sql_content", "") or ""
        sql_summary = self._sql_summary(sql_content, max_len=200)

        instance_name = ""
        try:
            instance_name = workflow.instance.instance_name
        except Exception:  # noqa: BLE001
            pass

        archery_base = getattr(
            django_settings,
            "ARCHERY_BASE_URL",
            "http://localhost",
        )
        affected_rows = extract_affected_rows(workflow, mode="total")
        affected_tables = extract_affected_tables(workflow)
        tables_str = ", ".join(
            f"{t.get('db','')}.{t.get('table','')}" for t in affected_tables[:10]
        )

        return [
            {"name": "工单号", "value": str(workflow.id)},
            {"name": "提交人", "value": getattr(workflow, "engineer_display", "") or ""},
            {"name": "目标库", "value": f"{instance_name}/{workflow.db_name or ''}"},
            {"name": "影响表", "value": tables_str or "-"},
            {"name": "影响行数", "value": str(affected_rows)},
            {"name": "SQL 摘要", "value": sql_summary},
            {"name": "命中 flow", "value": flow.code},
            {
                "name": "Archery 详情",
                "value": f"{archery_base.rstrip('/')}/sql/detail/{workflow.id}/",
            },
        ]

    @staticmethod
    def _sql_summary(sql: str, max_len: int = 200) -> str:
        """SQL 摘要：去注释 + 截断 + 多余空白折叠。"""
        if not sql:
            return ""
        # 去掉行注释
        lines = []
        for line in sql.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            lines.append(line)
        cleaned = "\n".join(lines).strip()
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len] + "..."
        return cleaned

    @staticmethod
    def _get_originator_userid(workflow) -> str:
        """取发起人对应的钉钉 userid（无则用 engineer 兜底）。"""
        return (
            getattr(workflow, "engineer", "")
            or ""
        )

    # ---------- 私有：API 调用 ----------

    def _call_dingtalk_api(self, endpoint: str, timeout: int = 10, **kwargs) -> Optional[dict]:
        """调钉钉 topapi 接口通用方法。

        Args:
            endpoint: 形如 ``topapi.processinstance.create`` 或
                ``topapi/processinstance/create``（``_call`` 自动转）。
            timeout: HTTP 超时秒。
            **kwargs: 透传给钉钉的 body 字段。

        Returns:
            接口 ``result`` 字段内容（dict）。无 ``result`` 字段时返回 ``None``。

        Raises:
            DingtalkApiError: 钉钉 errcode != 0。
            requests.RequestException: 网络层失败。
        """
        token = get_oa_access_token()
        if not token:
            raise DingtalkApiError(
                endpoint,
                {"errcode": -1, "errmsg": "access_token unavailable"},
            )
        # 形如 topapi.processinstance.create -> topapi/processinstance/create
        path = endpoint.replace(".", "/")
        url = f"https://oapi.dingtalk.com/{path}?access_token={token}"

        body = {k: v for k, v in kwargs.items() if v is not None}
        resp = requests.post(url, json=body, timeout=timeout)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}

        if not isinstance(data, dict):
            raise DingtalkApiError(
                endpoint,
                {"errcode": -1, "errmsg": f"non-dict response: {type(data).__name__}"},
            )

        # 钉钉 success 接口（如 comment.add）errcode 0 即可
        if data.get("errcode") not in (0, None):
            raise DingtalkApiError(endpoint, data)

        return data.get("result") or data.get("process_instance_id") or None

    def _add_comment_safe(self, ext: WorkflowAuditExternal, comment: str) -> None:
        """加备注，吃掉异常（不让钉钉 API 故障影响本地）。"""
        try:
            self._call_dingtalk_api(
                "topapi.processinstance.comment.add",
                process_instance_id=ext.external_process_instance_id,
                comment=comment,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "add comment to %s failed: %s",
                ext.external_process_instance_id, e,
            )

    def _terminate_safe(self, ext: WorkflowAuditExternal, reason: str) -> None:
        """终止流程，吃掉异常。"""
        try:
            self._call_dingtalk_api(
                "topapi.processinstance.terminate",
                process_instance_id=ext.external_process_instance_id,
                reason=reason[:200],
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "terminate %s failed: %s",
                ext.external_process_instance_id, e,
            )

    # ---------- 私有：降级 ----------

    def _fallback(self, workflow, audit, flow, reason: str) -> DriverStartResult:
        """v0.7 §10.4.3 第 1 款：start() 失败降级到本地 Group 审批。

        副作用：
            * 写一条 ``external_status='FALLBACK'`` 的 ``WorkflowAuditExternal`` 记录；
            * 改 ``workflow.audit_driver='archery'`` + ``audit_fallback_reason``；
            * 记 ``FALLBACK_AT_START`` 事件；
            * 推 DBA 群 webhook（不抛错）。
            * 若 ``CUSTOM_DINGTALK_OA_FALLBACK_ENABLED=False``，改成抛 ``DingtalkApiError``。
        """
        # 若用户显式禁用了降级，阻塞业务
        if not bool(getattr(django_settings, "CUSTOM_DINGTALK_OA_FALLBACK_ENABLED", True)):
            logger.error(
                "dingtalk OA start failed but fallback disabled, raising. reason=%s",
                reason,
            )
            DingtalkOaEventLog.objects.create(
                audit=audit, event_type="OA_START_BLOCKED",
                event_id=f"blocked-{audit.audit_id}",
                payload={"flow": flow.code, "reason": reason[:480]},
                processed=False, error=reason[:1000],
            )
            raise DingtalkApiError(
                "topapi.processinstance.create",
                {"errcode": -1, "errmsg": reason},
            )

        # 1) 写 FALLBACK 关联（不覆盖 RUNNING 已存在的关联）
        WorkflowAuditExternal.objects.get_or_create(
            audit=audit,
            source=self.name,
            defaults=dict(
                external_process_instance_id="",
                external_process_code=flow.dingtalk_process_code or "",
                external_status="FALLBACK",
                oa_failure_reason=reason[:500],
            ),
        )
        # 2) 改 workflow driver 为 archery
        workflow.audit_driver = "archery"
        workflow.audit_fallback_reason = reason[:255]
        workflow.save(update_fields=["audit_driver", "audit_fallback_reason"])

        # 3) 记事件
        DingtalkOaEventLog.objects.create(
            audit=audit, event_type="FALLBACK_AT_START",
            event_id=f"fallback-start-{audit.audit_id}",
            payload={"flow": flow.code, "reason": reason},
            processed=True, error=reason[:1000],
        )

        # 4) 推 DBA 群 webhook（不抛错）
        self._send_admin_alert(
            f"⚠️ 钉钉 OA 启动失败，已降级到本地审批\n"
            f"工单: {workflow.id} (audit_id={audit.audit_id})\n"
            f"flow: {flow.code}\n"
            f"原因: {reason[:200]}"
        )

        return DriverStartResult(
            external_id="",
            extra={"fallback": True, "reason": reason},
        )

    @staticmethod
    def _send_admin_alert(message: str) -> None:
        """推钉钉群 webhook（用 settings.DINGTALK_NOTIFY_WEBHOOK）。"""
        webhook = getattr(django_settings, "DINGTALK_NOTIFY_WEBHOOK", "")
        if not webhook:
            logger.debug("DINGTALK_NOTIFY_WEBHOOK 未配置，跳过 admin alert")
            return
        try:
            requests.post(
                webhook,
                json={"msgtype": "text", "text": {"content": message[:3800]}},
                timeout=5,
            )
        except Exception:  # noqa: BLE001
            logger.exception("send admin alert to dingtalk webhook failed")
