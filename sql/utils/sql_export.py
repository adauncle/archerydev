# -*- coding: utf-8 -*-
"""v0 数据导出工单 (DBA-bug 17) 异步任务: 跑 SQL -> 导出 CSV/XLSX -> 通知.

10/9 v0 拍板: 阿达叔叔按我建议决策
- 导出格式: CSV + XLSX
- 数据量上限: 1 万行 (max_export_rows)
- 文件交付: 邮件附件 (后续 v1 改 OSS 链接)
- 审批流: 复用 SQL 上线 (current_audit 走审批, auto_pass 走 callback)
- 范围: MVP (不含数据脱敏/定时/增量)

CUSTOM-MODIFIED: @ 2026-10-09 @ mavis
关联: docs/changelogs/2026-10-09_v0-sql-export-workflow.md
"""
import os
import csv
import time
import logging
import zipfile
import datetime
import hashlib
import traceback
import tempfile
import shutil

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("default")


def _export_root() -> str:
    """导出文件存储根目录. 跟 offlinedownload.py DynamicStorage 分离, 简化 v0."""
    root = getattr(settings, "CUSTOM_SQL_EXPORT_ROOT", "/opt/archery/prod/exports")
    os.makedirs(root, exist_ok=True)
    return root


def _save_csv(file_path: str, result, columns) -> int:
    """写 CSV (utf-8 + BOM, Excel 友好). 复用 offlinedownload.py save_csv 风格."""
    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        if columns:
            w.writerow(columns)
        for row in result:
            w.writerow(["null" if v is None else v for v in row])
    return os.path.getsize(file_path)


def _save_xlsx(file_path: str, result, columns) -> int:
    """写 XLSX (用 openpyxl). 复用 offlinedownload.py save_xlsx 风格."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    if columns:
        ws.append(columns)
    for row in result:
        ws.append(["" if v is None else v for v in row])
    wb.save(file_path)
    return os.path.getsize(file_path)


def _save_format_file(export, result, columns, temp_dir: str) -> str:
    """按 export.export_format (csv/xlsx) 写文件, 返回文件名."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    hash_value = hashlib.sha256(os.urandom(32)).hexdigest()[:8]
    base = f"{export.db_name}_{timestamp}_{hash_value}"
    ext = export.export_format
    file_name = f"{base}.{ext}"
    file_path = os.path.join(temp_dir, file_name)
    if ext == "csv":
        _save_csv(file_path, result, columns)
    elif ext == "xlsx":
        _save_xlsx(file_path, result, columns)
    else:
        raise ValueError(f"Unsupported export_format: {ext}")
    # 压缩成 zip (跟 offlinedownload.py 一致)
    zip_name = f"{base}.zip"
    zip_path = os.path.join(temp_dir, zip_name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(file_path, os.path.basename(file_path))
    return zip_name


def do_sql_export(export_id: int) -> dict:
    """异步任务: 跑 SqlExportWorkflow 工单的 SQL, 导出 CSV/XLSX, 写 file_path.

    入参: export_id (SqlExportWorkflow.id)
    返回: dict {status, file_path, file_size, row_count, error_msg}
    """
    from sql.models import SqlExportWorkflow
    from common.config import SysConfig
    from sql.engines import get_engine

    export = SqlExportWorkflow.objects.get(id=export_id)
    logger.info(f"[do_sql_export] start export_id={export_id} title={export.title}")

    # 1. 改 status=4 (导出中), 记录开始
    export.status = 4
    export.save(update_fields=["status", "sys_time"])

    config = SysConfig()
    max_rows = int(config.get("max_export_rows") or 10000)

    start_time = time.time()
    try:
        # 2. 跑 SQL
        engine = get_engine(instance=export.instance)
        full_sql = export.sql_content
        result_set = engine.query(
            db_name=export.db_name,
            sql=full_sql,
            max_execution_time=max_rows * 1000,  # ms
        )
        if result_set.error:
            raise Exception(result_set.error)

        columns = result_set.column_list or []
        rows = result_set.rows or []
        actual_rows = result_set.affected_rows or len(rows)

        # 3. 写文件 + 压缩
        with tempfile.TemporaryDirectory() as temp_dir:
            file_name = _save_format_file(export, rows, columns, temp_dir)
            tmp_zip = os.path.join(temp_dir, file_name)
            # 4. 拷贝到 exports 根目录
            export_root = _export_root()
            final_path = os.path.join(export_root, file_name)
            shutil.copy2(tmp_zip, final_path)
            file_size = os.path.getsize(final_path)

        # 5. 写回 SqlExportWorkflow
        export.status = 5  # 导出完成
        export.file_path = final_path
        export.file_size = file_size
        export.row_count = actual_rows
        export.finished_at = timezone.now()
        export.save(update_fields=[
            "status", "file_path", "file_size", "row_count", "finished_at", "sys_time"
        ])

        elapsed = round(time.time() - start_time, 3)
        logger.info(
            f"[do_sql_export] done export_id={export_id} file={final_path} "
            f"size={file_size} rows={actual_rows} elapsed={elapsed}s"
        )

        # 6. 通知申请人 (邮件 + 钉钉, 失败不阻塞)
        try:
            notify_for_sql_export(export.id)
        except Exception as e:
            logger.warning(f"[do_sql_export] notify fail export_id={export_id}: {e}")

        return {
            "status": "ok",
            "file_path": final_path,
            "file_size": file_size,
            "row_count": actual_rows,
            "elapsed": elapsed,
        }

    except Exception as e:
        # 6. 失败 -> status=6 + error_msg
        err = f"{type(e).__name__}: {e}"
        logger.error(
            f"[do_sql_export] fail export_id={export_id}\n{err}\n{traceback.format_exc()}"
        )
        export.status = 6  # 导出失败
        export.error_msg = err[:2000]
        export.finished_at = timezone.now()
        export.save(update_fields=[
            "status", "error_msg", "finished_at", "sys_time"
        ])
        return {"status": "fail", "error": err}


def notify_for_sql_export(export_id: int) -> dict:
    """通知申请人: 邮件附件 (zip) + 钉钉文本 (申请名/链接).

    10/9 v0 拍板: 邮件附件交付 (v0), 钉钉文本通知 (v0 顺手做)
    入参: export_id
    返回: dict {mail_status, dingtalk_status, error}
    """
    from sql.models import SqlExportWorkflow, Users
    from common.config import SysConfig
    from common.utils.sendmsg import MsgSender  # 邮件发送工具, 上游 Archery 提供

    export = SqlExportWorkflow.objects.get(id=export_id)
    user = Users.objects.get(username=export.user_name)
    mail_to = user.email
    dingtalk_webhook = SysConfig().get("dingtalk_webhook", "")

    result = {"mail_status": "skip", "dingtalk_status": "skip"}

    # 1. 邮件附件
    if export.status == 5 and export.file_path and os.path.exists(export.file_path):
        try:
            subject = f"[Archery 数据导出] {export.title} 已就绪"
            body = (
                f"<p>你好 {export.user_display or export.user_name},</p>"
                f"<p>你提交的数据导出工单 <b>{export.title}</b> 已完成, 请查收附件.</p>"
                f"<p>导出格式: {export.export_format.upper()} (含 zip 压缩包)</p>"
                f"<p>导出行数: {export.row_count}</p>"
                f"<p>文件大小: {export.file_size} bytes</p>"
                f"<p>实例: {export.instance.instance_name} / 库: {export.db_name}</p>"
                f"<p>工单 ID: {export.id}  完成时间: {export.finished_at}</p>"
                f"<p>SQL: <pre>{export.sql_content[:500]}</pre></p>"
            )
            mailer = MsgSender()
            # 附件发送: MsgSender.send_email 接受 filename_list 关键字
            mailer.send_email(
                subject=subject,
                body=body,
                to=[mail_to],
                filename_list=[export.file_path],
            )
            result["mail_status"] = "ok"
        except Exception as e:
            result["mail_status"] = f"fail: {e}"
            logger.error(
                f"[notify_for_sql_export] mail fail export_id={export_id}: {e}"
            )
    else:
        result["mail_status"] = "skip (export failed or file missing)"

    # 2. 钉钉文本通知 (跟 sql/notify.py 现有 dingtalk 通知风格一致)
    if dingtalk_webhook and export.status == 5:
        try:
            import requests
            content = (
                f"## 数据导出完成\n"
                f"- 工单: {export.title}\n"
                f"- 实例: {export.instance.instance_name} / 库: {export.db_name}\n"
                f"- 格式: {export.export_format}\n"
                f"- 行数: {export.row_count}\n"
                f"- 大小: {export.file_size} bytes\n"
                f"- 邮件: {result['mail_status']}\n"
                f"- 申请人: {export.user_display or export.user_name}"
            )
            requests.post(
                dingtalk_webhook,
                json={
                    "msgtype": "markdown",
                    "markdown": {"title": f"数据导出 {export.title}", "text": content},
                },
                timeout=10,
            )
            result["dingtalk_status"] = "ok"
        except Exception as e:
            result["dingtalk_status"] = f"fail: {e}"
            logger.warning(
                f"[notify_for_sql_export] dingtalk fail export_id={export_id}: {e}"
            )
    return result
