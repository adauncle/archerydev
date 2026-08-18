#!/bin/bash
# W2 必做 6: schema diff (134 dev vs 110 prod)
# 在 134 dev 端跑, 先抓 134 dev schema, 再 ssh 110 prod 抓, 再 diff
## CUSTOM-DRILL-SCRIPT: schema diff 演练,推 110 模板 @ 2026-08-18 @ mavis

set -uo pipefail

DRILL_DIR="/opt/archery/prod/scripts/_drill"
TS=$(date +%Y%m%d_%H%M%S)
OUT_DIR="${DRILL_DIR}/schema_diff_${TS}"
mkdir -p "${OUT_DIR}"

DBOPS_PASS=$(cat /etc/archery/dbops_password)

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# === 抓 134 dev schema (db_name=archery_prod) ===
log "=== 抓 134 dev schema (archery_prod) ==="
mysql -h 127.0.0.1 -udbops -p"${DBOPS_PASS}" archery_prod -N -B -e "
SELECT CONCAT(table_name, '|', column_name, '|', column_type, '|', is_nullable, '|', IFNULL(column_default, 'NULL'), '|', IFNULL(extra, ''))
FROM information_schema.columns
WHERE table_schema = 'archery_prod'
ORDER BY table_name, ordinal_position;
" 2>/dev/null > "${OUT_DIR}/134dev_columns.txt"
wc -l "${OUT_DIR}/134dev_columns.txt"

mysql -h 127.0.0.1 -udbops -p"${DBOPS_PASS}" archery_prod -N -B -e "
SELECT CONCAT(table_name, '|', index_name, '|', non_unique, '|', GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ','), '|', index_type)
FROM information_schema.statistics
WHERE table_schema = 'archery_prod'
GROUP BY table_name, index_name, non_unique, index_type
ORDER BY table_name, index_name;
" 2>/dev/null > "${OUT_DIR}/134dev_indexes.txt"
wc -l "${OUT_DIR}/134dev_indexes.txt"

mysql -h 127.0.0.1 -udbops -p"${DBOPS_PASS}" archery_prod -N -B -e "
SELECT CONCAT(table_name, '|', engine, '|', table_collation)
FROM information_schema.tables
WHERE table_schema = 'archery_prod'
ORDER BY table_name;
" 2>/dev/null > "${OUT_DIR}/134dev_tables.txt"
wc -l "${OUT_DIR}/134dev_tables.txt"

# === 抓 110 prod schema (db_name=archery) ===
log ""
log "=== 抓 110 prod schema (archery) ==="
sshpass -e ssh -o StrictHostKeyChecking=no root@172.20.2.110 "
mysql --defaults-file=/root/.my.cnf -D archery -N -B -e \"
SELECT CONCAT(table_name, '|', column_name, '|', column_type, '|', is_nullable, '|', IFNULL(column_default, 'NULL'), '|', IFNULL(extra, ''))
FROM information_schema.columns
WHERE table_schema = 'archery'
ORDER BY table_name, ordinal_position;
\" 2>/dev/null > /tmp/110prod_columns.txt
wc -l /tmp/110prod_columns.txt

mysql --defaults-file=/root/.my.cnf -D archery -N -B -e \"
SELECT CONCAT(table_name, '|', index_name, '|', non_unique, '|', GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ','), '|', index_type)
FROM information_schema.statistics
WHERE table_schema = 'archery'
GROUP BY table_name, index_name, non_unique, index_type
ORDER BY table_name, index_name;
\" 2>/dev/null > /tmp/110prod_indexes.txt
wc -l /tmp/110prod_indexes.txt

mysql --defaults-file=/root/.my.cnf -D archery -N -B -e \"
SELECT CONCAT(table_name, '|', engine, '|', table_collation)
FROM information_schema.tables
WHERE table_schema = 'archery'
ORDER BY table_name;
\" 2>/dev/null > /tmp/110prod_tables.txt
wc -l /tmp/110prod_tables.txt
"
scp root@172.20.2.110:/tmp/110prod_columns.txt "${OUT_DIR}/110prod_columns.txt"
scp root@172.20.2.110:/tmp/110prod_indexes.txt "${OUT_DIR}/110prod_indexes.txt"
scp root@172.20.2.110:/tmp/110prod_tables.txt "${OUT_DIR}/110prod_tables.txt"

# === 比对 ===
log ""
log "=== schema diff 结果 ==="
log "--- 1. 表数量比对 ---"
echo "  134 dev 表数: $(grep -c '^[^|]*|' ${OUT_DIR}/134dev_tables.txt)"
echo "  110 prod 表数: $(grep -c '^[^|]*|' ${OUT_DIR}/110prod_tables.txt)"

log ""
log "--- 2. 表名差异 (134 dev 多 / 110 prod 多) ---"
diff <(cut -d'|' -f1 ${OUT_DIR}/134dev_tables.txt | sort -u) <(cut -d'|' -f1 ${OUT_DIR}/110prod_tables.txt | sort -u) > "${OUT_DIR}/tables_diff.txt"
cat "${OUT_DIR}/tables_diff.txt" || echo "  (无差异)"

log ""
log "--- 3. 列差异 (134 dev 列多 / 110 prod 列多) ---"
diff <(cut -d'|' -f1-2 ${OUT_DIR}/134dev_columns.txt | sort) <(cut -d'|' -f1-2 ${OUT_DIR}/110prod_columns.txt | sort) > "${OUT_DIR}/columns_diff.txt"
diff_lines=$(wc -l < "${OUT_DIR}/columns_diff.txt")
echo "  列差异行数: $diff_lines"
head -30 "${OUT_DIR}/columns_diff.txt"

log ""
log "--- 4. 索引差异 (134 dev 索引多 / 110 prod 索引多) ---"
diff <(cut -d'|' -f1-4 ${OUT_DIR}/134dev_indexes.txt | sort) <(cut -d'|' -f1-4 ${OUT_DIR}/110prod_indexes.txt | sort) > "${OUT_DIR}/indexes_diff.txt"
diff_lines=$(wc -l < "${OUT_DIR}/indexes_diff.txt")
echo "  索引差异行数: $diff_lines"
head -30 "${OUT_DIR}/indexes_diff.txt"

log ""
log "--- 5. 引擎 + collation 差异 (134 dev 表多 / 110 prod 表多) ---"
diff <(cut -d'|' -f1-3 ${OUT_DIR}/134dev_tables.txt | sort) <(cut -d'|' -f1-3 ${OUT_DIR}/110prod_tables.txt | sort) > "${OUT_DIR}/engine_diff.txt"
diff_lines=$(wc -l < "${OUT_DIR}/engine_diff.txt")
echo "  引擎+collation 差异行数: $diff_lines"
head -30 "${OUT_DIR}/engine_diff.txt"

log ""
log "=== W2 必做 6 schema diff 完成 ==="
log "结果目录: ${OUT_DIR}"
