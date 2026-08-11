"""v0.3.0-beta DBA 兜底 + 大表 DDL 防呆 打包脚本"""
import io
import tarfile
import time
from pathlib import Path

ROOT = Path(r"G:\MiniMax工作空间\archery_dev")
DIST = ROOT / "dist"
DIST.mkdir(parents=True, exist_ok=True)

FILES = [
    "sql/views.py",
    "sql/templates/detail.html",
    "archery/settings.py",
    "scripts/drill_v030b_dba_fallback.py",
    "scripts/pack_v030b_dba_fallback.py",
    "docs/changelogs/2026-08-11_gh-ost-dba-fallback.md",
]

PREFIX = "v0_3_0_beta_dba_fallback"


def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = DIST / f"v0.3.0-beta-dba-fallback_{ts}.tar.gz"
    print(f"[pack] 输出: {out}")
    with tarfile.open(out, "w:gz") as tar:
        for rel in FILES:
            abs_path = ROOT / rel
            if not abs_path.exists():
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
