"""
v0.3.0-beta 审批守卫 打包脚本
============================
打包范围:
  - sql/models.py                                    (enable_gh_ost 字段)
  - sql/views.py                                     (can_enable_ghost 守卫 + lazy auto-enable)
  - sql/sql_workflow.py                              (拒绝清理 DdlGhostTask)
  - sql_api/api_workflow.py                          (submit 只存标记)
  - sql/templates/detail.html                        (审批前提示)
  - scripts/drill_v030b_approval_gating.py           (演练脚本)
  - scripts/pack_v030b_approval.py                   (本脚本)
  - docs/changelogs/2026-08-11_gh-ost-approval-gating.md  (changelog)

用法: python scripts/pack_v030b_approval.py
"""
import io
import os
import tarfile
import time
from pathlib import Path

ROOT = Path(r"G:\MiniMax工作空间\archery_dev")
DIST = ROOT / "dist"
DIST.mkdir(parents=True, exist_ok=True)

FILES = [
    "sql/models.py",
    "sql/views.py",
    "sql/sql_workflow.py",
    "sql_api/api_workflow.py",
    "sql/templates/detail.html",
    "scripts/drill_v030b_approval_gating.py",
    "scripts/pack_v030b_approval.py",
    "docs/changelogs/2026-08-11_gh-ost-approval-gating.md",
]

PREFIX = "v0_3_0_beta_approval_gating"


def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = DIST / f"v0.3.0-beta-approval-gating_{ts}.tar.gz"
    print(f"[pack] 输出: {out}")

    with tarfile.open(out, "w:gz") as tar:
        for rel in FILES:
            abs_path = ROOT / rel
            if not abs_path.exists():
                # changelog 第一次跑可能不存在，跳过
                if "changelogs" in rel:
                    print(f"[pack] - {rel} (跳过, 文件不存在)")
                    continue
                raise SystemExit(f"文件不存在: {abs_path}")
            content = abs_path.read_bytes()
            arcname = f"{PREFIX}/{rel}"
            info = tarfile.TarInfo(name=arcname)
            info.size = len(content)
            info.mtime = abs_path.stat().st_mtime
            info.mode = 0o644
            tar.addfile(info, fileobj=io.BytesIO(content))
            print(f"[pack] + {rel} -> {arcname} ({len(content)} bytes)")

    print(f"[pack] 完成: {out.stat().st_size} bytes")
    return out


if __name__ == "__main__":
    main()
