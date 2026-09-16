"""W3 索引 diff 演练 (DBA-bug-8, 2026-09-16 业务方实战)

业务: 业务方实战 add index idx_owner_name(owner_name), 表里已有 idx_owner_name 索引
      (owner_name 字段上), 字段 diff 弹窗 错显示 "ADD index 新列, 无冲突"
      (把 ADD INDEX 错解析成 ADD COLUMN).

演练 5 case (用 134 dev 真实业务表 archery_dev.accesscard_account, 已有 PK + unique + MUL 索引):
- A: 索引名重复 (add index idx_old_id (col), 但 idx_old_id 已存在) → 期望 high reject
- B: 索引字段重复 (add index idx_new_id (id), 但 id 字段已有 PK 索引, 走 PR/UNIQUE 判断) → 期望 pass (因为 PR 不冲突)
- B2: 索引字段重复 (add index idx_new (user_id), 但 user_id 已有 MUL 普通索引) → 期望 high reject (字段重复)
- C: 索引不重复 (add index idx_new (account_name), 假设 account_name 字段没索引) → 期望 pass
- D: drop index 不存在 (drop index idx_no_exists) → 期望 high reject

实战 case K: business add index idx_owner_name(owner_name) 但 owner_name 已有 idx_owner_name 索引
@ 2026-09-16 @ mavis
"""

import os
import sys

sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django  # noqa: E402

django.setup()

from sql.models import Instance  # noqa: E402
from sql.extensions.ddl_gh_ost.services.column_diff import (  # noqa: E402
    _diff_single_table,
    _fetch_current_indexes,
)


def load_env(env_path):
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


load_env("/opt/archery/prod/.env")


inst = Instance.objects.get(id=1)  # 134 dev 真实业务实例
db_name = "archery_dev"
table_name = "accesscard_account"


# 0. 查表当前索引
print("=== 0. 当前表索引 (archery_dev.accesscard_account) ===")
idx = _fetch_current_indexes(inst, db_name, table_name)
for name, info in idx.items():
    print(f"  {name}: columns={info['columns']} non_unique={info['non_unique']} type={info['type']}")
print()


def case(sql, expected_high=False, expected_low_pass=False, expected_name_in_index=None):
    """演练 case 验证"""
    result = _diff_single_table(inst, db_name, sql, force_table_name=table_name)
    if not result.get("ok"):
        return f"FAIL (期望 ok 但 ok=False) {result}"
    index_diff = result.get("index_diff", [])
    if expected_high:
        # 期望有 high 风险
        high_count = sum(1 for i in index_diff if any(d.get("risk") == "high" for d in i.get("diffs", [])))
        if high_count > 0:
            idx_names = [i.get("name") for i in index_diff]
            return f"PASS high={high_count} names={idx_names} diffs={[i.get('diffs') for i in index_diff]}"
        return f"FAIL (期望 high 但没有) index_diff={index_diff}"
    if expected_low_pass:
        # 期望 pass (无 high 风险, 无 mid 风险)
        high_count = sum(1 for i in index_diff if any(d.get("risk") == "high" for d in i.get("diffs", [])))
        if high_count == 0:
            return f"PASS pass index_diff={index_diff}"
        return f"FAIL (期望 pass 但有 high) index_diff={index_diff}"
    return f"UNEXPECTED TEST (need expected_* flag) result={result}"


# Case A: 索引名重复
print("=== A: 索引名重复 (add index idx_old_id ... 但 idx_old_id 已存在) ===")
# accesscard_account 真实索引看上面输出, 一般会有 PK + unique + MUL
# 这里假设 idx_old 索引可能存在, 如果不存在就改用真实存在的索引名
real_idx_names = list(idx.keys())
real_idx_first = real_idx_names[0] if real_idx_names else "PRIMARY"
print(f"  使用真实存在的索引名: {real_idx_first}")
sql_a = f"ALTER TABLE {table_name} ADD INDEX {real_idx_first} (account_number)"
print(case(sql_a, expected_high=True))

# Case B: 索引字段重复 (id 字段已有 PK)
print("\n=== B: 索引字段重复 - id 字段已有 PK (PK 不影响普通索引冲突) ===")
sql_b = f"ALTER TABLE {table_name} ADD INDEX idx_new_id (id)"
# PK 索引 non_unique=False (PRIMARY 是 unique), 跳过
# → 期望 pass (不冲突, 字段 PRIMARY 不算普通索引)
print(case(sql_b, expected_low_pass=True))

# Case B2: 索引字段重复 - user_id 字段已有 MUL 普通索引
print("\n=== B2: 索引字段重复 - user_id 字段已有 MUL 普通索引 (业务方实战) ===")
# 找一个 non_unique=True 的索引第一列作为冲突字段
mul_idx_first_col = None
for name, info in idx.items():
    if info["non_unique"] and info["columns"]:
        mul_idx_first_col = (name, info["columns"][0])
        break
if mul_idx_first_col:
    print(f"  真实 MUL 索引 {mul_idx_first_col[0]} 第一列 {mul_idx_first_col[1]} → 业务方实战场景")
    sql_b2 = f"ALTER TABLE {table_name} ADD INDEX idx_new_field ({mul_idx_first_col[1]})"
    print(case(sql_b2, expected_high=True))
else:
    print(f"  SKIP: archery_dev.accesscard_account 没有 MUL 普通索引, 演练改用 user_id 假设")
    # fallback: 跑 sql 看效果
    sql_b2 = f"ALTER TABLE {table_name} ADD INDEX idx_new_field (user_id)"
    print(case(sql_b2, expected_high=True))

# Case C: 索引不重复 (新字段没索引)
print("\n=== C: 索引不重复 (add index idx_new (account_name), account_name 没索引) ===")
# accesscard_account.account_name 字段应该没索引
sql_c = f"ALTER TABLE {table_name} ADD INDEX idx_new_unique (account_name)"
print(case(sql_c, expected_low_pass=True))

# Case D: drop index 不存在
print("\n=== D: drop index idx_no_exists (索引不存在) ===")
sql_d = f"ALTER TABLE {table_name} DROP INDEX idx_no_exists"
print(case(sql_d, expected_high=True))

# Case E: 实战 case 9/16 业务方
print("\n=== E: 实战 case 9/16 业务方 add index idx_owner_name (owner_name) 字段已加索引 ===")
# accesscard_account 没 owner_name 字段, 改用 add index idx_unique_field (account_number) 替代
# account_number 是 unique 字段 (UNIQUE 索引不影响)
print(f"  实战对应场景: 加索引 (字段: account_number) 但 account_number 是 UNIQUE 字段, 不算冲突 → pass")
sql_e = f"ALTER TABLE {table_name} ADD INDEX idx_owner_name_alt (account_number)"
print(case(sql_e, expected_low_pass=True))

# Case F: 实战 case 9/16 业务方 (索引字段重复, 索引名不同)
print("\n=== F: 实战 case 9/16 业务方 (字段重复, 索引名不同) ===")
# add index idx_new_name (user_id) 但 user_id 字段已有 MUL 普通索引
if mul_idx_first_col:
    sql_f = f"ALTER TABLE {table_name} ADD INDEX idx_completely_new_name ({mul_idx_first_col[1]})"
    print(case(sql_f, expected_high=True))
else:
    sql_f = f"ALTER TABLE {table_name} ADD INDEX idx_completely_new_name (user_id)"
    print(case(sql_f, expected_high=True))

# Case G: 实战 case 9/16 业务方真实 SQL (name 后无空格, 业务方实战 主验证)
print("\n=== G: 业务方实战真实 SQL (add index idx_owner_name(create_time) name 后无空格) ===")
# 关键: idx_owner_name(create_time) 无空格, 业务方实战 add index idx_owner_name(owner_name) 同款
# CREATE_TIME 字段已有 idx_c_time 普通索引 → 期望 high reject
sql_g = f"ALTER TABLE {table_name} ADD INDEX idx_owner_name({mul_idx_first_col[1] if mul_idx_first_col else 'create_time'})"
print(case(sql_g, expected_high=True))

# Case H: 多字段索引 (第一列 create_time 已有 idx_c_time, 应该 high reject 不是 pass)
print("\n=== H: 多字段索引 (第一列 create_time 已有 idx_c_time, high reject) ===")
sql_h = f"ALTER TABLE {table_name} ADD INDEX idx_multi_field (create_time, account_number)"
print(case(sql_h, expected_high=True))

# Case I: 实战 mixed SQL (ADD COLUMN + add index 在同一 ALTER, 业务方实战)
print("\n=== I: 实战 mixed SQL (ADD COLUMN xxx + add index yyy(z), 业务方实战) ===")
sql_i = f"""ALTER TABLE {table_name}
  ADD COLUMN new_test_col VARCHAR(150) DEFAULT NULL,
  ADD INDEX idx_test_col (new_test_col)"""
print(case(sql_i, expected_low_pass=True))


print("\n=== 演练完成 ===")