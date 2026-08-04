"""
verify_promote_110_syntax.py —— 把 promote_110.sh 通过 ssh 喂给 110 跑 bash -n 验证语法
"""
import sys
import subprocess
from pathlib import Path

local = Path(r'G:\MiniMax工作空间\archery_dev\scripts\promote_110.sh')
remote = 'root@172.20.2.110'
cmd = 'bash -n'

print(f"[local]  {local} ({local.stat().st_size} bytes)")

with open(local, 'rb') as f:
    content = f.read()

proc = subprocess.run(
    ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
     '-o', 'ConnectTimeout=10', remote, cmd],
    input=content,
    capture_output=True,
    timeout=30
)

print(f"[remote] {remote} '{cmd}'")
print(f"[rc]     {proc.returncode}")
if proc.stdout:
    print(f"[stdout] {proc.stdout.decode('utf-8', errors='replace')}")
if proc.stderr:
    print(f"[stderr] {proc.stderr.decode('utf-8', errors='replace')}")

if proc.returncode == 0:
    print("[OK] promote_110.sh syntax OK on 110 PROD")
    sys.exit(0)
else:
    print("[ERR] promote_110.sh syntax error on 110 PROD")
    sys.exit(1)
