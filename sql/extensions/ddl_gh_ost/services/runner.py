"""
gh-ost 子进程启停 + 命令行构建。

不走 systemd-run（systemd 219 在 134 dev 上没 --scope 选项），
直接 subprocess.Popen + nohup + 日志到 /var/log/archery/gh_ost/。
"""

import logging
import os
import shlex
import signal
import subprocess
from typing import List, Optional

from django.conf import settings
from django.utils import timezone

from .db import _get_creds

logger = logging.getLogger("default")


def _ensure_log_dir() -> str:
    """确保 log 目录存在，归 archery 用户所有。"""
    log_dir = getattr(settings, "CUSTOM_GH_OST_LOG_DIR", "/var/log/archery/gh_ost")
    try:
        os.makedirs(log_dir, exist_ok=True)
        # 不强制 chown，让 archery 进程自己写（如果 root 启失败就静默）
    except PermissionError:
        # log 目录归 archery 用户，root 写不了，但 archery 进程能写
        pass
    return log_dir


def build_ghost_command(task, instance=None, rebuild_mode: bool = False) -> List[str]:
    """根据 task 构建 gh-ost 命令行参数列表（subprocess 用）。

    ## CUSTOM-MODIFIED: v0.4.5-alpha 加 rebuild_mode 参数 @ 2026-08-06 @ mavis
    关联设计: docs/designs/2026-08-05_gh-ost-product-design.html v0.4.5 §4

    Args:
        task: DdlGhostTask 实例
        instance: SqlWorkflow 对应的 Instance（optional, fallback 用 task.workflow.instance）
        rebuild_mode: True = rebuild 场景，alter 改为空 COMMENT 触发表重建；
                      rebuild 时 task.workflow=NULL，instance 必传。

    Returns:
        list[str] 命令行参数
    """
    ## CUSTOM-MODIFIED: v0.4.5-alpha 区分 ghost / rebuild 取 instance 路径
    if rebuild_mode:
        # rebuild 任务 workflow=NULL，instance 必须从入参拿
        if instance is None:
            raise ValueError("rebuild 模式必须传 instance（task.workflow=NULL）")
        inst = instance
        alter_arg = _make_rebuild_alter(task)
    else:
        inst = instance or (task.workflow.instance if task.workflow_id else None)
        if inst is None:
            raise ValueError("no instance available for gh-ost")
        # 提取 ALTER（去掉 "ALTER TABLE x " 前缀，gh-ost 接收裸子句）。
        ## 业务: gh-ost --alter 期望 **裸子句** (MODIFY / ADD / DROP ...),
        ##      gh-ost 内部拼成 `ALTER TABLE <ghost_table> <alter_subclause>`.
        ## 之前 8/24 fix 写的逻辑 "alter.strip().upper().startswith('ALTER')" 反了:
        ##   - 用户原始 SQL ("alter table\n  test\nmodify\n  ...") 大小写混合+多行+反引号
        ##   - 业务库 8.0.22 Archery 解析保留原始格式, task.alter_statement 存的是原始 SQL
        ##   - 反逻辑保留原值, gh-ost 1.1.10 报 SQL syntax error 1064 near 'table
        ## 134 dev 8/24 演练 16/16 PASS 是 instance 5 (业务库 5.7) Archery 5.7 解析标准化
        ##   存到 task.alter_statement 已经是裸子句, 8/24 反逻辑凑巧 PASS.
        ## 实际用法 (8/27 14:11 task #4 instance 27 历史库 8.0.22): 第一次用就暴露 bug.
        ## 修法 (8/27 14:18): 正则提取子句, 兼容三种格式.
        import re
        alter = task.alter_statement or ""
        m = re.match(
            r"^\s*alter\s+table\s+`?\S+`?\s*(.*)$",
            alter.strip(),
            re.IGNORECASE | re.DOTALL,
        )
        alter_arg = m.group(1) if m else alter.strip()

    user, password, (host, port) = _get_creds(inst)
    bin_path = getattr(settings, "CUSTOM_GH_OST_BIN", "/usr/local/bin/gh-ost")

    cmd = [
        bin_path,
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
        f"--password={password}",
        f"--database={task.db_name}",
        f"--table={task.table_name}",
        f"--alter={alter_arg}",
        # 134 dev 已知 RBR，避免 gh-ost 主动探测
        "--assume-rbr",
        # 单机 dev，无 replica
        "--allow-on-master",
        # 真跑
        "--execute",
        # 行数统计
        "--exact-rowcount",
        "--concurrent-rowcount",
        # 负载阈值（暂停阈值由 poller 主动 SIGSTOP 控制，这里只是 panic 退出）
        f"--max-load=Threads_running={task.max_load_threads_running}",
        # 不抢 CPU
        "--nice-ratio=0",
        # cut-over
        "--cut-over=atomic",
        # 自动清理
        "--initially-drop-ghost-table",
        "--initially-drop-old-table",
        "--ok-to-drop-table",
        # 详细日志
        "--verbose",
        # 重试
        "--default-retries=120",
    ]
    return cmd


## CUSTOM-MODIFIED: v0.4.5-alpha 新增 rebuild 场景空 alter 生成 @ 2026-08-06 @ mavis
## CUSTOM-MODIFIED: v0.4.5-alpha 修 134 dev 演练 bug：去掉 ALTER TABLE 前缀 @ 2026-08-10 @ mavis
## CUSTOM-MODIFIED: v0.4.5 拍板改 ENGINE+ROW_FORMAT+CHARSET @ 2026-08-13 @ mavis
## CUSTOM-MODIFIED: v0.4.5 简化到 ENGINE=InnoDB (1 层) @ 2026-08-25 @ mavis
def _make_rebuild_alter(task) -> str:
    """rebuild 场景的 alter 子句 (8/25 17:30 简化: 1 层 ENGINE=InnoDB).

    ## 简化背景 (8/25 17:30 用户拍板)
    8/13 拍板是 3 层防护 (ENGINE+ROW_FORMAT+CHARSET) 当时以为能让 8.0 触发物理重写.
    8/25 16:50 调研发现 8.0.22 4 种 alter 全 no-op (8.0 INSTANT 优化):
      - ENGINE 改自己 → INSTANT 跳过
      - ROW_FORMAT 改自己 → INPLACE 跳过
      - CHARSET/COLLATION 改自己 → INPLACE/INSTANT 跳过
      - OPTIMIZE TABLE 默认 ALGORITHM=DEFAULT (INSTANT no-op)
    也就是说 8.0.22 加 ROW_FORMAT/CHARSET 也不会真重写, 反而在 5.7 走 COPY 触发整表
    重写时让 gh-ost alter 子句变复杂, 没价值.

    ## 简化方案
    直接 `ALTER TABLE t ENGINE=InnoDB;` (8/25 17:30 用户拍板):
      - **5.7.44**: 改 ENGINE 改自己走 **COPY 触发整表物理重写**, ibd 真收缩 ✓
      - **8.0.22**: 改 ENGINE 改自己走 INSTANT 跳过, **不重写** (架构性限制, 接受)
      - **业务**: 110 prod (5.7) 真 work, DBA 推完后跑 rebuild 看到 ibd 真收缩

    ## 5.7 vs 8.0 触发行为
    - MySQL 5.7.44: ALTER TABLE t ENGINE=InnoDB (原表就是 InnoDB) 强制走 COPY, 整表重写 ✓
    - MySQL 8.0.22: 改 ENGINE 改自己走 INSTANT, **跳过重写** (8.0 INSTANT 优化) ✗
    - 8.0.22 走 INSTANT 跳过是 MySQL 自身优化, gh-ost 控制不了, 不在 v0.4.5 范围

    ## gh-ost --alter 参数规则
    gh-ost 期望 ``--alter`` 是**裸子句**, gh-ost 内部拼成
    ``ALTER TABLE <ghost_table> <alter_subclause>``.
    之前踩坑: 传完整 SQL `ALTER TABLE x COMMENT '...'` → gh-ost 拆掉后剩
    `x COMMENT '...'` → 拼到 ghost table → SQL syntax error 1064.
    修复: 传裸子句, gh-ost 拼成 `ALTER TABLE _x_gho ENGINE=InnoDB` → 正确.

    ## 数据来源
    rebuild_start 视图在写 task 之前查 information_schema.tables 拿原表属性,
    填到 task.rebuilt_charset / rebuilt_row_format / rebuilt_collation,
    拼出 rebuilt_alter_full 存到 task. 这里 _make_rebuild_alter 直接读
    task.rebuilt_alter_full, 不再查 schema (避免重复 IO + 保持 alter 决定的一致性).

    ## 关联
    - 8/13 拍板 3 决策: docs/changelogs/2026-08-13_v0405-rebuilt-fields.md
    - 8/25 16:55 撤方案 C 改字符集: docs/changelogs/2026-08-25_v0405-fragmentation-algorithm-fix.md
    - 8/25 17:30 简化到 1 层防护: docs/changelogs/2026-08-25_v0405-rebuild-8p0-instant-caveat.md
    """
    if not getattr(task, "rebuilt_alter_full", ""):
        # fallback: 8/13 之前的旧 task 还没填 rebuilt_alter_full, 用 COMMENT 兜底
        # (避免老 task 全部坏掉, 新 task 不会走这里)
        today = timezone.now().strftime("%Y%m%d")
        logger.warning(
            "rebuild task #%s rebuilt_alter_full 为空, fallback 到 COMMENT 触发 (8/13 旧版行为)",
            task.id,
        )
        return f"COMMENT 'archery-auto-rebuild-{today}'"
    return task.rebuilt_alter_full


def _cleanup_stale_socket(sock_path: str, task_id: int = None) -> None:
    """CUSTOM: 启动 gh-ost 前清 zombie socket (CUSTOM-MODIFIED: v0.3.0-beta @ 2026-08-10 @ mavis)。

    探测 sock 路径:
      - 不存在 → 无事可做
      - 存在 + 进程死了 (无法连上) → unlink 掉
      - 存在 + 进程活着 → 抛 RuntimeError (拒绝启动, 防双跑)
    """
    if not os.path.exists(sock_path):
        return
    # 探测: 尝试 connect 一次, 失败说明僵尸 socket
    import socket as _socket
    is_alive = False
    try:
        s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(sock_path)
        s.close()
        is_alive = True
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        is_alive = False
    if is_alive:
        # 端口被占, 拒绝启动
        raise RuntimeError(
            f"gh-ost socket 端口被占 ({sock_path}) — 可能有同表任务在跑, "
            f"或上次启动的 gh-ost 进程仍在。先检查并清理再重试。task_id={task_id}"
        )
    try:
        os.unlink(sock_path)
        logger.warning("清理 zombie gh-ost socket: %s (task_id=%s)", sock_path, task_id)
    except OSError as exc:
        logger.warning("清理 zombie gh-ost socket 失败 %s: %s", sock_path, exc)


def start_ghost_process(task, instance=None) -> int:
    """启动 gh-ost 子进程（Popen + nohup）。

    ## CUSTOM-MODIFIED: v0.4.5-alpha 修 bug：从 task_type 推断 rebuild_mode @ 2026-08-10 @ mavis
    rebuild 任务调 start_ghost_process 时，自动 rebuild_mode=True。
    bug 背景：原代码 build_ghost_command(task, instance) 不传 rebuild_mode，
    内部走 ghost 分支取 task.alter_statement，rebuild 任务 alter_statement 为空
    → alter_arg = "ALTER TABLE "（空表名）→ gh-ost 报 SQL syntax error 1064

    ## CUSTOM-MODIFIED: v0.3.0-beta 启动前自动清 zombie socket @ 2026-08-10 @ mavis
    bug 背景: 上次 cut-over 成功后 gh-ost 子进程被 SIGTERM 但 socket 文件残留，
    新启动 gh-ost 撞同路径 socket → FATAL bind: address already in use。
    修法: 启动前探测 socket 路径 (默认 /tmp/gh-ost.<db>.<table>.sock),
          如果存在 + 对应进程死了 → unlink；存在 + 进程活着 → 报错拒绝启动 (防双跑)
    关联设计: docs/designs/2026-08-10_gh-ost-detail-design.html §7.4

    Returns:
        gh-ost PID（成功）

    Raises:
        RuntimeError 启失败 (含 zombie socket 端口被占)
    """
    log_dir = _ensure_log_dir()
    log_path = os.path.join(log_dir, f"ghost-{task.id}.log")

    rebuild_mode = (getattr(task, "task_type", None) == "rebuild")
    cmd = build_ghost_command(task, instance, rebuild_mode=rebuild_mode)

    # ===== 1) 自动清 zombie socket =====
    db_name = getattr(task, "db_name", None) or (instance.db_name if instance else None)
    table_name = getattr(task, "table_name", None)
    if db_name and table_name:
        sock_path = f"/tmp/gh-ost.{db_name}.{table_name}.sock"
        _cleanup_stale_socket(sock_path, task_id=task.id)

    logger.info("gh-ost start: task_id=%s cmd=%s", task.id, " ".join(shlex.quote(c) for c in cmd))

    # 把 log 文件 chown 到 archery:archery（gunicorn 跑在 archery 用户下）
    # root 跑时这里会报错，archery 跑时直接 OK
    try:
        if os.path.exists(log_path):
            os.remove(log_path)
        # 先 touch 一下
        with open(log_path, "w") as f:
            f.write("")
        try:
            import pwd
            archery_pwd = pwd.getpwnam("archery")
            os.chown(log_path, archery_pwd.pw_uid, archery_pwd.pw_gid)
        except (KeyError, PermissionError, OSError):
            pass
    except PermissionError as exc:
        logger.warning("can't touch log file %s: %s", log_path, exc)

    # nohup gh-ost ... > log 2>&1 &  — Popen 模式
    with open(log_path, "ab", buffering=0) as logf:
        proc = subprocess.Popen(
            cmd,
            stdout=logf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # 等价 nohup
            cwd="/tmp",
        )

    if proc.poll() is not None:
        # 进程秒退，看日志
        try:
            with open(log_path, "r", errors="replace") as f:
                err_tail = f.read()[-2000:]
        except Exception:
            err_tail = "(can't read log)"
        raise RuntimeError(
            f"gh-ost 进程秒退 (rc={proc.returncode})。log tail: {err_tail}"
        )

    logger.info("gh-ost started: task_id=%s pid=%s log=%s", task.id, proc.pid, log_path)
    return proc.pid


def stop_ghost_process(pid: int, timeout: int = 10) -> bool:
    """停止 gh-ost 子进程。先 SIGTERM，超时 SIGKILL。

    Returns:
        True 成功停止
    """
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True  # 进程已经不在了
    except PermissionError:
        logger.error("no permission to SIGTERM pid=%s", pid)
        return False

    # 等几秒
    import time
    for _ in range(timeout * 2):
        try:
            os.kill(pid, 0)  # probe
        except ProcessLookupError:
            return True
        time.sleep(0.5)

    # 还没死，SIGKILL
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return True


def is_alive(pid: int) -> bool:
    """进程是否还活着。"""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def read_log_tail(log_path: str, max_bytes: int = 65536) -> str:
    """读 log 末尾 max_bytes。"""
    try:
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except (FileNotFoundError, PermissionError):
        return ""
