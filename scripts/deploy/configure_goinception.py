"""配置 Archery SysConfig 让 sql/engines/goinception.py 能找到 goInception 服务。

根因: 之前 TRUNCATE 了 sql_config 表，导致 go_inception_host 等配置
      都是 None，MySQLdb.connect 报 '\connect argument 1 must be str, not None'。

修复: 用 SysConfig.set 写入 go_inception_host/port/user/password。
      主机写 127.0.0.1，goInception 在本机 4000 端口。
"""
import os
import sys

sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()

from common.config import SysConfig

cfg = SysConfig()

# goInception 在本机 4000 端口（systemd 服务 /opt/goinception/goInception）
# user/password 留空：goInception 默认接受空凭据连接
to_set = {
    "go_inception_host": "127.0.0.1",
    "go_inception_port": "4000",
    # goInception 不真鉴权，但 MySQLdb 拿到 None 会报错
    # 必须是非空字符串（任意值都可，goInception 内部透传给目标 MySQL）
    "go_inception_user": "root",
    "go_inception_password": "",
    # 备份库（如果做 DML/DDL 执行时需要回滚表）
    # 留空表示关闭 backup：纯审计场景不需要
    "inception_remote_backup_host": "",
    "inception_remote_backup_port": "3306",
    "inception_remote_backup_user": "root",
    "inception_remote_backup_password": "",
}

print("=" * 70)
print("写入 SysConfig（goInception 连接配置）")
print("=" * 70)
for k, v in to_set.items():
    cfg.set(k, v)
    got = cfg.get(k)
    print(f"  {k:35s} = {got!r}")

print()
print("=" * 70)
print("验证: GoInceptionEngine.get_connection 用的 4 个值")
print("=" * 70)
for k in ("go_inception_host", "go_inception_port", "go_inception_user", "go_inception_password"):
    print(f"  {k:35s} = {cfg.get(k)!r}")

print()
print("=" * 70)
print("测试 MySQLdb 连接 goInception")
print("=" * 70)
import MySQLdb
try:
    conn = MySQLdb.connect(
        host=cfg.get("go_inception_host"),
        port=int(cfg.get("go_inception_port", 4000)),
        user=cfg.get("go_inception_user") or "",
        passwd=cfg.get("go_inception_password") or "",
        connect_timeout=5,
    )
    cur = conn.cursor()
    cur.execute("INCEPTION GET VARIABLES")
    rows = cur.fetchall()
    print(f"  ✓ 连接成功，INCEPTION GET VARIABLES 返回 {len(rows)} 行")
    for r in rows[:5]:
        print(f"    {r}")
    conn.close()
except Exception as e:
    print(f"  ✗ 连接失败: {e}")
    sys.exit(1)

print()
print("DONE - 重启 gunicorn 让 ORM 缓存刷新:")
print("  systemctl restart archery-prod-gunicorn.service")
print()
print("然后回 /submitsql/ 页面点 SQL检测 → 应该看到 goInception 返回的语法/审核结果")
