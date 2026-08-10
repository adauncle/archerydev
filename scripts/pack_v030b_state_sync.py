"""
v0.3.0-beta 状态机修复打包脚本
============================
打包范围:
  - sql/extensions/ddl_gh_ost/services/poller.py    (_sync_workflow_status 新增)
  - sql/views.py                                    (has_ghost_task / ghost_task_is_terminal)
  - sql/templates/detail.html                       (active vs terminal UI 分支)
  - docs/changelogs/2026-08-10_gh-ost-v030-beta-state-sync.md (写完后回填)

打包到 dist/v0.3.0-beta-state-sync_<时间戳>.tar.gz
显式 arcname = "v0_3_0_beta_state_sync/<相对路径>"，保证解压到子目录。

用法:
  python scripts/pack_v030b_state_sync.py
"""
import os
import tarfile
import time
from pathlib import Path

ROOT = Path(r"G:\MiniMax工作空间\archery_dev")
DIST = ROOT / "dist"
DIST.mkdir(parents=True, exist_ok=True)

# 要打包的文件 (相对 ROOT)
FILES = [
    "sql/extensions/ddl_gh_ost/services/poller.py",
    "sql/views.py",
    "sql/templates/detail.html",
    "docs/changelogs/2026-08-10_gh-ost-v030-beta-state-sync.md",
    "scripts/pack_v030b_state_sync.py",
]

# 子目录前缀 (解压后所有文件会落在这里)
PREFIX = "v0_3_0_beta_state_sync"


def pack_one(abs_path: Path) -> str:
    """把单个文件读成 bytes，返回 (arcname, bytes)。"""
    rel = abs_path.relative_to(ROOT).as_posix()
    arcname = f"{PREFIX}/{rel}"
    return arcname, abs_path.read_bytes()


def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = DIST / f"v0.3.0-beta-state-sync_{ts}.tar.gz"
    print(f"[pack] 输出: {out}")

    packed = 0
    with tarfile.open(out, "w:gz") as tar:
        for rel in FILES:
            abs_path = ROOT / rel
            if not abs_path.exists():
                raise SystemExit(f"文件不存在: {abs_path}")
            arcname, content = pack_one(abs_path)
            info = tarfile.TarInfo(name=arcname)
            info.size = len(content)
            info.mtime = abs_path.stat().st_mtime
            info.mode = 0o644
            tar.addfile(info, fileobj=__import__("io").BytesIO(content))
            print(f"[pack] + {rel} -> {arcname} ({len(content)} bytes)")
            packed += 1

    print(f"[pack] 完成: {packed} 文件, {out.stat().st_size} bytes")
    return out


if __name__ == "__main__":
    main()
