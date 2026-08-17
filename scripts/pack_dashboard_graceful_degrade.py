"""pack_dashboard_graceful_degrade.py — 8/17 dashboard 优雅降级 打包

8/17 修复 Archery 上游 dashboard get_chart_data 串行无 try/except 缺陷。
打包物料:
- common/dashboard.py (改了 get_chart_data + 加 logger + CUSTOM-MODIFIED 头)
- scripts/_unit_safe_chart.py (单测)
- scripts/drill_dashboard_graceful_degrade.py (演练)
- docs/changelogs/2026-08-17_dashboard-graceful-degrade.md (changelog)
- scripts/pack_dashboard_graceful_degrade.py (本脚本, 134 dev 解包后保留作存档)

跑法: python scripts/pack_dashboard_graceful_degrade.py
输出: dist/dashboard-graceful-degrade_<ts>.tar.gz
"""
import io
import sys
import tarfile
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = Path(r"G:\MiniMax工作空间\archery_dev")
DIST = ROOT / "dist"
DIST.mkdir(parents=True, exist_ok=True)

FILES = [
    "common/dashboard.py",
    "scripts/_unit_safe_chart.py",
    "scripts/drill_dashboard_graceful_degrade.py",
    "scripts/pack_dashboard_graceful_degrade.py",
    "docs/changelogs/2026-08-17_dashboard-graceful-degrade.md",
]

PREFIX = "dashboard_graceful_degrade"


def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = DIST / f"dashboard-graceful-degrade_{ts}.tar.gz"
    print(f"[pack] 输出: {out}")
    with tarfile.open(out, "w:gz") as tar:
        for rel in FILES:
            abs_path = ROOT / rel
            if not abs_path.exists():
                raise SystemExit(f"文件不存在: {abs_path}")
            content = abs_path.read_bytes()
            arcname = f"{PREFIX}/{rel}"
            info = tarfile.TarInfo(name=arcname)
            info.size = len(content)
            info.mtime = abs_path.stat().st_mtime
            info.mode = 0o644
            tar.addfile(info, fileobj=io.BytesIO(content))
            print(f"[pack] + {rel} -> {arcname} ({len(content)} bytes)")
    print(f"[pack] 完成: {out.stat().st_size} bytes ({out.stat().st_size/1024:.1f} KB)")
    return out


if __name__ == "__main__":
    main()
