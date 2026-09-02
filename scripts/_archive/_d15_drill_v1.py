# -*- coding: utf-8 -*-
"""9/2 D15: 字符集 implicit/explicit 字段 diff dryrun 演练.

3 个 case:
  Case A: 字段定义 **没显式** CHARSET (表默认) → 变更也没指定 → 应该 risk=none
  Case B: 字段定义 **显式** CHARSET=utf8mb4 → 变更没指定 → 应该 risk=high (旧显式丢了)
  Case C: 字段定义 **显式** CHARSET=utf8mb4 → 变更显式 utf8mb4 → 应该 risk=none (不变)
"""
import os
import sys

# 9/2 D12 实战新发现: 134 dev .env SECRET_KEY 真值要在本地跑 Django 时注入
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
os.environ["SECRET_KEY"] = "4H7ZIYKcjJZO8qbWDO80XR5UMrHliDXeFVTwarWkXVp79ySmruBVTk0NXdXjCkAOg9c"
# 134 dev 走 chdir 到 /opt/archery/prod (settings.LOGGING 相对路径, 必 cwd)
# 134 dev 走 root 跑 (systemd 一样的 env 一致, 9/2 D12 实战新发现)

# hack settings.LOGGING 避免 PermissionError
import django.conf
sys.path.insert(0, "/opt/archery/prod")

import django
django.setup()

from sql.models import Instance
from sql.extensions.ddl_gh_ost.services.column_diff import (
    _fetch_current_columns,
    _fetch_table_create_sql,
    _parse_column_explicit_attrs,
    column_diff_full,
    _assess_charset_risk,
    _assess_collation_risk,
)

# 拿 134 dev instance
instance = Instance.objects.get(id=1)
print("instance:", instance.instance_name, instance.host, instance.port)

# === 在 134 dev 准备 2 个演练表 ===
import pymysql
user, password = instance.get_username_password()

conn = pymysql.connect(
    host=instance.host, port=instance.port, user=user, password=password,
    database="hly_accesscard", connect_timeout=5, autocommit=True,
)

try:
    with conn.cursor() as cur:
        # Case A: 字段定义**没显式** CHARSET (类似 order_penalty)
        cur.execute("DROP TABLE IF EXISTS d15_test_implicit")
        cur.execute("""
            CREATE TABLE d15_test_implicit (
                id bigint NOT NULL,
                name varchar(100) DEFAULT NULL COMMENT '隐式 CHARSET'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """)
        print("Case A: 造表 d15_test_implicit (字段无显式 CHARSET)")

        # Case B: 字段定义**显式** CHARSET=utf8mb4
        cur.execute("DROP TABLE IF EXISTS d15_test_explicit")
        cur.execute("""
            CREATE TABLE d15_test_explicit (
                id bigint NOT NULL,
                name varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci
                    DEFAULT NULL COMMENT '显式 CHARSET'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """)
        print("Case B: 造表 d15_test_explicit (字段显式 CHARSET)")

        # Case C: 字段定义**显式** CHARSET=utf8mb4 + utf8mb4_general_ci (跟 utf8mb4_0900_ai_ci 不同)
        cur.execute("DROP TABLE IF EXISTS d15_test_explicit_general")
        cur.execute("""
            CREATE TABLE d15_test_explicit_general (
                id bigint NOT NULL,
                name varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci
                    DEFAULT NULL COMMENT '显式 utf8mb4_general_ci'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """)
        print("Case C: 造表 d15_test_explicit_general (字段显式 utf8mb4_general_ci)")
finally:
    conn.close()

# === 看下 _fetch_current_columns 拿到的 explicit 标记 ===
print("\n=== _fetch_current_columns 拿 explicit 标记 ===")
for tbl in ["d15_test_implicit", "d15_test_explicit", "d15_test_explicit_general"]:
    print(f"\n--- {tbl} ---")
    create_sql = _fetch_table_create_sql(instance, "hly_accesscard", tbl)
    print(f"SHOW CREATE TABLE 头 200 字符: {create_sql[:200]}")
    cols = _fetch_current_columns(instance, "hly_accesscard", tbl)
    for name, c in cols.items():
        print(f"  col {name}: charset={c['charset']!r}, collation={c['collation']!r}, "
              f"charset_explicit={c['charset_explicit']}, collation_explicit={c['collation_explicit']}")

# === dryrun column_diff_full 验证 ===
print("\n=== dryrun column_diff_full ===")

# Case A: 隐式 CHARSET + SQL 不指定 → 应该 risk=none
print("\n--- Case A: 旧 implicit + 新不指定 (期望 risk=none) ---")
sql_a = """ALTER TABLE d15_test_implicit MODIFY COLUMN name varchar(200) DEFAULT NULL COMMENT '改长度'"""
res = column_diff_full(instance, "hly_accesscard", sql_a)
if res.get("ok"):
    for t in res.get("tables", []):
        for c in t.get("columns", []):
            print(f"  col {c['name']}: {c['operation']}")
            for d in c.get("diffs", []):
                print(f"    diff: {d}")
else:
    print(f"  ERR: {res.get('error')}")

# Case B: 显式 CHARSET + SQL 不指定 → 应该 risk=high (旧显式丢了)
print("\n--- Case B: 旧 explicit + 新不指定 (期望 risk=high) ---")
sql_b = """ALTER TABLE d15_test_explicit MODIFY COLUMN name varchar(200) DEFAULT NULL COMMENT '改长度'"""
res = column_diff_full(instance, "hly_accesscard", sql_b)
if res.get("ok"):
    for t in res.get("tables", []):
        for c in t.get("columns", []):
            print(f"  col {c['name']}: {c['operation']}")
            for d in c.get("diffs", []):
                print(f"    diff: {d}")
else:
    print(f"  ERR: {res.get('error')}")

# Case C: 显式 CHARSET + SQL 显式同值 → 应该 risk=none (没变)
print("\n--- Case C: 旧 explicit + 新显式同值 (期望 risk=none) ---")
sql_c = """ALTER TABLE d15_test_explicit_general MODIFY COLUMN name varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '改长度'"""
res = column_diff_full(instance, "hly_accesscard", sql_c)
if res.get("ok"):
    for t in res.get("tables", []):
        for c in t.get("columns", []):
            print(f"  col {c['name']}: {c['operation']}")
            for d in c.get("diffs", []):
                print(f"    diff: {d}")
else:
    print(f"  ERR: {res.get('error')}")

# Case D (额外): 显式 CHARSET + SQL 显式不同值 → 应该 risk=high (值变了)
print("\n--- Case D: 旧 explicit + 新显式不同值 (期望 risk=high) ---")
sql_d = """ALTER TABLE d15_test_explicit MODIFY COLUMN name varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '换 collation'"""
res = column_diff_full(instance, "hly_accesscard", sql_d)
if res.get("ok"):
    for t in res.get("tables", []):
        for c in t.get("columns", []):
            print(f"  col {c['name']}: {c['operation']}")
            for d in c.get("diffs", []):
                print(f"    diff: {d}")
else:
    print(f"  ERR: {res.get('error')}")

# 清理演练表
conn = pymysql.connect(
    host=instance.host, port=instance.port, user=user, password=password,
    database="hly_accesscard", connect_timeout=5, autocommit=True,
)
try:
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS d15_test_implicit")
        cur.execute("DROP TABLE IF EXISTS d15_test_explicit")
        cur.execute("DROP TABLE IF EXISTS d15_test_explicit_general")
        print("\n--- 清理演练表 ---")
finally:
    conn.close()
