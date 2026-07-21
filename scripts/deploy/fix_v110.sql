-- fix_v110.sql - 补 v1.10.0 漏跑的两个字段 + 重建 instance_account 唯一索引
-- 跑前确保 v0.1.0 部署的 schema 缺 is_ssl / db_name
-- 用 IF NOT EXISTS 兼容重复跑

-- 1. sql_instance 加 is_ssl（v1.10.0 引入）
SET @col_exists = (SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'sql_instance' AND column_name = 'is_ssl');
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE sql_instance ADD COLUMN is_ssl tinyint(1) DEFAULT 0 COMMENT ''\xE6\x98\xAF\xE5\x90\xA6\xE5\x90\xAF\xE7\x94\xA8SSL''',
    'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 2. instance_account 加 db_name（v1.10.0 引入）
SET @col_exists = (SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'instance_account' AND column_name = 'db_name');
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE instance_account ADD COLUMN db_name varchar(128) DEFAULT '''' NOT NULL COMMENT ''\xE6\x95\xB0\xE6\x8D\xAE\xE5\xBA\x93\xE5\x90\x8D\xEF\xBC\x88mongodb\xEF\xBC\x89'' AFTER host',
    'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 3. instance_account 重建唯一索引（v1.10.0 改成 4 字段联合唯一）
-- 先看老索引
SET @idx_name = (SELECT constraint_name FROM information_schema.table_constraints
    WHERE table_schema = DATABASE() AND table_name = 'instance_account' AND constraint_type = 'UNIQUE' LIMIT 1);
SET @sql = IF(@idx_name IS NOT NULL,
    CONCAT('ALTER TABLE instance_account DROP INDEX ', @idx_name),
    'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 看新索引是不是已存在（4 字段联合唯一）
SET @idx_exists = (SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'instance_account' AND index_name = 'uidx_instanceid_user_host_dbname');
SET @sql = IF(@idx_exists = 0,
    'ALTER TABLE instance_account ADD UNIQUE INDEX uidx_instanceid_user_host_dbname(`instance_id`, `user`, `host`, `db_name`)',
    'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 验证
SELECT '=== sql_instance.is_ssl ===' AS info;
SELECT is_ssl FROM sql_instance LIMIT 3;

SELECT '=== instance_account.db_name ===' AS info;
SELECT instance_id, `user`, host, db_name FROM instance_account LIMIT 3;

SELECT '=== instance_account 索引 ===' AS info;
SHOW INDEX FROM instance_account;
