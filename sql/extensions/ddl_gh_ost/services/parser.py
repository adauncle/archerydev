"""
gh-ost stdout 解析器。

gh-ost 1.1.10 输出格式（每行）：
    2026-08-06 10:30:01 INFO  Migrating archery_dev.accesscard_black_detail
    2026-08-06 10:30:01 INFO  Copy: 1000/10000 10.0%; Applied: Yes; Backlog: 0/100; Time: 1s total, 0s copying; ETA: 9s
    2026-08-06 10:30:11 INFO  Waiting for cut-over
    2026-08-06 10:30:12 INFO  Cut-over complete
    2026-08-06 10:30:12 INFO  Done.
    2026-08-06 10:30:05 FATAL Error: Lost connection to MySQL server

只解析最近一次 poller 时间之后的"新行"（避免每 3s 重复解析整个 log）。
简化版：直接解析整段 log，取最后一条有效信息。
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("default")


@dataclass
class GhostParseResult:
    """gh-ost 单次解析结果。"""
    stage: Optional[str] = None  # connecting/copying/cut_over/done
    progress_pct: Optional[int] = None
    rows_copied: Optional[int] = None
    rows_total: Optional[int] = None
    elapsed_seconds: Optional[int] = None
    eta_seconds: Optional[int] = None
    last_message: Optional[str] = None
    is_failed: bool = False
    is_done: bool = False
    error_message: Optional[str] = None


# 关键正则
# gh-ost 1.1.10 输出格式（更宽松）：
#   Copy: 176000/441558 39.9%; Applied: 0; Backlog: 0/1000;
#   Time: 11s(total), 11s(copy); streamer: ...; Lag: ...; HeartbeatLag: ...; State: migrating; ETA: 16s []
_RE_COPY = re.compile(
    r"Copy:\s*(\d+)/(\d+)\s+([\d.]+)%",
    re.IGNORECASE,
)
_RE_TIME = re.compile(r"Time:\s*(\d+)s", re.IGNORECASE)
_RE_ETA = re.compile(r"ETA:\s*(\d+)s", re.IGNORECASE)
_RE_MIGRATING = re.compile(
    r"Migrating\s+[`]?(\w+)[`]?\.[`]?(\w+)[`]?", re.IGNORECASE
)
_RE_WAITING_CUTOVER = re.compile(r"Waiting for cut-over", re.IGNORECASE)
_RE_CUTOVER_COMPLETE = re.compile(r"Cut-over complete", re.IGNORECASE)
_RE_DONE = re.compile(r"\bDone\.?\s*$", re.IGNORECASE)
_RE_DONE_MIGRATING = re.compile(r"\bDone migrating\b", re.IGNORECASE)
_RE_FATAL = re.compile(r"\bFATAL\b\s*(.*)", re.IGNORECASE)
_RE_ERROR = re.compile(r"\bERROR\b\s*(.*)", re.IGNORECASE)
# 8/25 教训: gh-ost cut-over 后 cleanup 阶段常见 1146 noise (drop _x_ghc 表已不存在)
# 匹配 1146 或 "doesn't exist" 即认为是 cleanup noise, 跳过
_RE_CLEANUP_NOISE_1146 = re.compile(r"1146|doesn't exist", re.IGNORECASE)
_RE_TIMESTAMP = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(\w+)\s+(.*)"
)


def parse_ghost_log(text: str) -> GhostParseResult:
    """解析 gh-ost 输出文本，返回最新状态。

    算法：遍历每一行，取"最后一条"有效的进度/阶段信息。
    """
    result = GhostParseResult()
    if not text:
        return result

    lines = text.splitlines()
    last_progress_line_idx = -1

    for idx, raw in enumerate(lines):
        line = raw.rstrip()
        if not line:
            continue

        # 时间戳 + level
        m = _RE_TIMESTAMP.match(line)
        if not m:
            # 不是标准格式，跳过（可能是 gh-ost 内部 debug 输出）
            continue
        ts, level, msg = m.group(1), m.group(2), m.group(3)

        # FATAL — 立即 failed
        if level == "FATAL":
            fm = _RE_FATAL.search(line)
            err = fm.group(1).strip() if fm else line
            result.is_failed = True
            result.error_message = err[:1000]
            result.last_message = msg.strip()
            result.stage = "failed"
            return result

        # ERROR
        if level == "ERROR":
            em = _RE_ERROR.search(line)
            err = em.group(1).strip() if em else line
            ## CUSTOM-MODIFIED: 8/25 教训过滤 gh-ost cleanup 阶段 1146 noise @ 2026-08-25 @ mavis
            ## 关联: docs/changelogs/2026-08-25_gh-ost-cleanup-1146-noise.md
            ## 业务: gh-ost 1.1.10 cut-over 成功后 cleanup 阶段 (drop _x_ghc changelog 表)
            ##       经常报 1146 "Table 'X' doesn't exist", 不影响主流程 (数据迁移 100% 成功)
            ##       业务 RD 看着别扭, 过滤掉 (跟 FATAL 区分, FATAL 仍报 fail)
            if _RE_CLEANUP_NOISE_1146.search(err):
                continue
            # gh-ost 经常 ERROR 但不 FATAL，记录但不 fail
            if not result.error_message:
                result.error_message = err[:1000]
            result.last_message = msg.strip()
            continue

        # Copy: N/M P%
        cm = _RE_COPY.search(msg)
        if cm:
            result.rows_copied = int(cm.group(1))
            result.rows_total = int(cm.group(2))
            result.progress_pct = int(float(cm.group(3)))
            tm = _RE_TIME.search(msg)
            if tm:
                result.elapsed_seconds = int(tm.group(1))
            em = _RE_ETA.search(msg)
            if em:
                result.eta_seconds = int(em.group(1))
            result.stage = "copying"
            result.last_message = msg.strip()
            last_progress_line_idx = idx
            continue

        # Cut-over complete
        if _RE_CUTOVER_COMPLETE.search(msg):
            result.stage = "done"
            result.progress_pct = 100
            result.is_done = True
            result.last_message = msg.strip()
            return result

        # Done. / Done migrating xxx
        if _RE_DONE.search(msg) or _RE_DONE_MIGRATING.search(msg):
            result.stage = "done"
            result.progress_pct = 100
            result.is_done = True
            result.last_message = msg.strip()
            return result

        # Waiting for cut-over
        if _RE_WAITING_CUTOVER.search(msg):
            result.stage = "cut_over"
            result.last_message = msg.strip()
            continue

        # Migrating x.y
        if _RE_MIGRATING.search(msg):
            if result.stage is None:
                result.stage = "connecting"
            result.last_message = msg.strip()
            continue

        # 其他 INFO 行 — 记录 last_message
        result.last_message = msg.strip()

    return result
