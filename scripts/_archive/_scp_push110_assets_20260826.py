#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scp 推 110 物料到 110 prod /tmp/
8/26 17:16 用户拍板 "要", 提前 scp 推前物料

推 110 物料 (5 个文件):
1. scripts/deploy/5step_prerequisites_110prod.sh (5 步必做 13 步, 22.9KB)
2. scripts/deploy/pre_push_backup_110prod_20260826.sh (3 份备份, 9.5KB)
3. scripts/deploy/rollback_110prod_v030_20260826.sh (一键回滚, 10KB)
4. scripts/deploy/verify_5endpoints_110prod.sh (5+1 端点验证, 11.5KB)
5. docs/runbooks/2026-08-27_push-v030-execution-manual.md (推 110 手册, 48KB)

附加 (推 110 准备):
- 110 prod qcluster 状态 check (8/25 教训: 30 天没重启风险, §1.5 风险 4)
- 110 prod /backup/ 剩余空间 check (8/17 摸底可用 54GB, 推 110 必 >5GB)
- 110 prod /dbdata/archery_v114_c9236a0 当前 commit (期望 d303c04)
- 110 prod .my.cnf 可用性 check

8/26 17:16 mavis @ 用户拍板 "要"
"""

import sys
import os
import io
import time

# UTF-8 输出 (PowerShell GBK 兜底)
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import paramiko

# 凭据 (从 memory 8/24 钉钉 OA settings 教训抄)
HOST = '172.20.2.110'
USER = 'root'
PASSWORD = 'lAqfb8uEmQYsnGNQwIHtGPwukjCz6J'
PORT = 22

# 推 110 物料 (本地 → 110 prod /tmp/)
ASSETS = [
    {
        'local': r'G:\MiniMax工作空间\archery_dev\scripts\deploy\5step_prerequisites_110prod.sh',
        'remote': '/tmp/5step_prerequisites_110prod.sh',
        'size': '22.9KB',
        'desc': '5 步必做 13 步脚本',
        'chmod': '0755',
    },
    {
        'local': r'G:\MiniMax工作空间\archery_dev\scripts\deploy\pre_push_backup_110prod_20260826.sh',
        'remote': '/tmp/pre_push_backup_110prod_20260826.sh',
        'size': '9.5KB',
        'desc': '3 份备份脚本',
        'chmod': '0755',
    },
    {
        'local': r'G:\MiniMax工作空间\archery_dev\scripts\deploy\rollback_110prod_v030_20260826.sh',
        'remote': '/tmp/rollback_110prod_v030_20260826.sh',
        'size': '10KB',
        'desc': '一键回滚脚本',
        'chmod': '0755',
    },
    {
        'local': r'G:\MiniMax工作空间\archery_dev\scripts\deploy\verify_5endpoints_110prod.sh',
        'remote': '/tmp/verify_5endpoints_110prod.sh',
        'size': '11.5KB',
        'desc': '5+1 端点验证脚本',
        'chmod': '0755',
    },
    {
        'local': r'G:\MiniMax工作空间\archery_dev\docs\runbooks\2026-08-27_push-v030-execution-manual.md',
        'remote': '/tmp/2026-08-27_push-v030-execution-manual.md',
        'size': '48KB',
        'desc': '推 110 主手册 (DBA 现场参考)',
        'chmod': '0644',
    },
]


def ssh_exec(ssh, cmd, timeout=30):
    """执行远程命令, 返 (stdout, stderr, exit_code)"""
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    ec = stdout.channel.recv_exit_status()
    return out, err, ec


def main():
    print('=' * 70)
    print('scp 推 110 物料到 172.20.2.110:/tmp/ (8/26 17:16 用户拍板 "要")')
    print('=' * 70)
    print()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f'>>> SSH 连接 {USER}@{HOST}:{PORT} ...')
    try:
        ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=10)
    except Exception as e:
        print(f'!!! SSH 连接失败: {e}')
        sys.exit(1)
    print('  ✓ SSH 连接成功')
    print()

    # ===== 第一步: 推 110 物料 scp =====
    sftp = ssh.open_sftp()
    print('===== 1. scp 推 110 物料 (5 个文件) =====')
    print()
    for asset in ASSETS:
        local_path = asset['local']
        remote_path = asset['remote']
        if not os.path.exists(local_path):
            print(f'!!! 本地文件不存在: {local_path}')
            sys.exit(1)
        local_size = os.path.getsize(local_path)
        print(f'>>> {asset["desc"]} ({asset["size"]})')
        print(f'    本地: {local_path}')
        print(f'    远端: {remote_path}')
        try:
            sftp.put(local_path, remote_path)
        except Exception as e:
            print(f'    !!! scp 失败: {e}')
            sys.exit(1)
        # 改权限
        ssh_exec(ssh, f'chmod {asset["chmod"]} {remote_path}')
        # 验证
        out, err, ec = ssh_exec(ssh, f'ls -la {remote_path} && stat -c "%s bytes" {remote_path}')
        print(f'    远端确认: {out}')
        if f'{local_size}' not in out:
            print(f'    !!! size 不一致 (本地 {local_size} vs 远端见上)')
            sys.exit(1)
        print(f'    ✓ OK')
        print()
    sftp.close()
    print()

    # ===== 第二步: 110 prod 推前状态 check =====
    print('===== 2. 110 prod 推前状态 check =====')
    print()

    # 2.1 qcluster 状态 (8/25 教训 §1.5 风险 4)
    print('>>> 2.1 qcluster 进程状态 (§1.5 风险 4: 30 天没重启历史)')
    out, err, ec = ssh_exec(ssh, 'ps -eo pid,etime,time,cmd | grep qcluster | grep -v grep | head -3')
    print(f'    {out if out else "(空)"}')
    if out:
        for line in out.split('\n'):
            if 'qcluster' in line and ('30' in line or '31' in line or '29' in line or 'days' in line):
                print(f'    !!! ⚠️  qcluster 跑了 30+ 天, 推 110 前必重启')
    print()

    # 2.2 /backup/ 剩余空间
    print('>>> 2.2 /backup/ 剩余空间 (推 110 必 > 5GB)')
    out, err, ec = ssh_exec(ssh, 'df -BG /backup | tail -1')
    print(f'    {out}')
    print()

    # 2.3 /dbdata/archery_v114_c9236a0 当前 commit (期望 d303c04)
    print('>>> 2.3 /dbdata/archery_v114_c9236a0 当前 commit (期望 d303c04)')
    out, err, ec = ssh_exec(ssh, 'cd /dbdata/archery_v114_c9236a0 2>/dev/null && git log -1 --oneline 2>&1 | head -1')
    print(f'    {out if out else "(目录不存在或不是 git 仓库)"}')
    print()

    # 2.4 .my.cnf 可用性
    print('>>> 2.4 .my.cnf 可用性 check')
    out, err, ec = ssh_exec(ssh, 'mysql --defaults-file=/root/.my.cnf -e "SELECT VERSION(), DATABASE();" 2>&1')
    print(f'    {out if out else "(my.cnf 不可用)"}')
    print()

    # 2.5 gunicorn master pid
    print('>>> 2.5 gunicorn master pid (期望 102228)')
    out, err, ec = ssh_exec(ssh, 'ps -ef | grep gunicorn | grep -v grep | awk \'$3==1 {print $2}\' | head -1')
    print(f'    {out if out else "(无 master)"}')
    print()

    # 2.6 110 prod 3 个端点预检
    print('>>> 2.6 3 个端点预检 (推 110 前期望全 200/302)')
    for ep in ['/login/', '/dbaprinciples/', '/admin/']:
        out, err, ec = ssh_exec(ssh, f'curl -sI --max-time 5 http://127.0.0.1:9123{ep} 2>&1 | head -1')
        print(f'    {ep} -> {out if out else "(无响应)"}')
    print()

    ssh.close()
    print('=' * 70)
    print('✓ 推 110 物料 scp 完 + 推前状态 check 完')
    print('  下一步: 18:00 群发"19:00 开始" / 18:45 DBA 自查 / 18:50 跑 3 份备份')
    print('=' * 70)


if __name__ == '__main__':
    main()
