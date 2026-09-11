#!/bin/bash
# 134 dev 造大表 waybill_union_carrier_dba_bug1 (用存储过程插入 12w 行)
set -e
mysql -udbops -p'TJwgoqnHBlPG5WLemg1sG@#P' -D archery_prod <<'SQL'
DROP PROCEDURE IF EXISTS proc_dba_bug1_insert;
DELIMITER //
CREATE PROCEDURE proc_dba_bug1_insert()
BEGIN
    DECLARE i INT DEFAULT 0;
    WHILE i < 120000 DO
        INSERT INTO waybill_union_carrier_dba_bug1 (waybill_id, carrier_id, data)
        VALUES (CONCAT('WB', LPAD(i, 10, '0')), i % 100, REPEAT('x', 100));
        SET i = i + 1;
    END WHILE;
END //
DELIMITER ;

TRUNCATE TABLE waybill_union_carrier_dba_bug1;
CALL proc_dba_bug1_insert();
DROP PROCEDURE proc_dba_bug1_insert;
ANALYZE TABLE waybill_union_carrier_dba_bug1;

SELECT TABLE_ROWS AS info_rows, ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 1) AS info_size_mb
FROM information_schema.tables
WHERE TABLE_SCHEMA='archery_prod' AND TABLE_NAME='waybill_union_carrier_dba_bug1';
SELECT COUNT(*) AS actual_rows FROM waybill_union_carrier_dba_bug1;
SQL
