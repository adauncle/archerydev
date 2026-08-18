#!/bin/bash
# W2 必做 6 schema diff: 134 dev 端跑 diff 部分
# 数据已在 /opt/archery/prod/scripts/_drill/schema_diff_20260818_093907/
OUT_DIR="/opt/archery/prod/scripts/_drill/schema_diff_20260818_093907"

echo "=== 1. 表名差异 ==="
echo "--- 134 dev 多 (有, 110 prod 没有) ---"
comm -23 <(cut -d'|' -f1 ${OUT_DIR}/134dev_tables.txt | sort -u) <(cut -d'|' -f1 ${OUT_DIR}/110prod_tables.txt | sort -u)
echo "--- 110 prod 多 (有, 134 dev 没有) ---"
comm -13 <(cut -d'|' -f1 ${OUT_DIR}/134dev_tables.txt | sort -u) <(cut -d'|' -f1 ${OUT_DIR}/110prod_tables.txt | sort -u)

echo ""
echo "=== 2. 列差异 (前 50 行) ==="
echo "--- 134 dev 列多 ---"
diff <(cut -d'|' -f1-2 ${OUT_DIR}/134dev_columns.txt | sort) <(cut -d'|' -f1-2 ${OUT_DIR}/110prod_columns.txt | sort) | head -100
echo "--- 110 prod 列多 ---"
diff <(cut -d'|' -f1-2 ${OUT_DIR}/110prod_columns.txt | sort) <(cut -d'|' -f1-2 ${OUT_DIR}/134dev_columns.txt | sort) | head -100

echo ""
echo "=== 3. 共有表的列差异 (前 50 行) ==="
# 找共有表
common_tables=$(comm -12 <(cut -d'|' -f1 ${OUT_DIR}/134dev_tables.txt | sort -u) <(cut -d'|' -f1 ${OUT_DIR}/110prod_tables.txt | sort -u))
for tbl in $common_tables; do
  diff_dev=$(grep "^${tbl}|" ${OUT_DIR}/134dev_columns.txt | sort)
  diff_prod=$(grep "^${tbl}|" ${OUT_DIR}/110prod_columns.txt | sort)
  if [[ "$diff_dev" != "$diff_prod" ]]; then
    echo "--- ${tbl} ---"
    diff <(echo "$diff_dev") <(echo "$diff_prod") | head -10
  fi
done | head -100

echo ""
echo "=== 4. 共有表的引擎/collation 差异 ==="
for tbl in $common_tables; do
  dev_engine=$(grep "^${tbl}|" ${OUT_DIR}/134dev_tables.txt)
  prod_engine=$(grep "^${tbl}|" ${OUT_DIR}/110prod_tables.txt)
  if [[ "$dev_engine" != "$prod_engine" ]]; then
    echo "  ${tbl}: 134dev=${dev_engine} | 110prod=${prod_engine}"
  fi
done

echo ""
echo "=== 5. 共有表索引差异 (前 30 行) ==="
for tbl in $common_tables; do
  diff_dev=$(grep "^${tbl}|" ${OUT_DIR}/134dev_indexes.txt | sort)
  diff_prod=$(grep "^${tbl}|" ${OUT_DIR}/110prod_indexes.txt | sort)
  if [[ "$diff_dev" != "$diff_prod" ]]; then
    echo "--- ${tbl} ---"
    diff <(echo "$diff_dev") <(echo "$diff_prod") | head -10
  fi
done | head -60
