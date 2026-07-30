-- 迁移脚本：为 kb_llm_model 增加 currency 列，为 kb_llm_call_log 将 cost_usd 拆为 cost_amount + cost_currency
-- 适用于已有数据库的增量升级，新库由 02/08 DDL 直接包含新列
-- 幂等设计：MySQL 8.0 不支持 ADD COLUMN IF NOT EXISTS，通过 information_schema 检查实现幂等

-- ---------------------------------------------------------------------------
-- kb_llm_model: 新增 currency 列
-- ---------------------------------------------------------------------------
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'kb_llm_model' AND COLUMN_NAME = 'currency');
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE kb_llm_model ADD COLUMN currency CHAR(3) NOT NULL DEFAULT ''CNY'' COMMENT ''计费币种：CNY=人民币, USD=美元'' AFTER output_price_per_1m',
    'SELECT ''kb_llm_model.currency already exists, skipping'' AS message');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------------------
-- kb_llm_call_log: cost_usd -> cost_amount + cost_currency
-- ---------------------------------------------------------------------------
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'kb_llm_call_log' AND COLUMN_NAME = 'cost_amount');
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE kb_llm_call_log ADD COLUMN cost_amount DECIMAL(10,6) NULL COMMENT ''预估成本金额，币种见 cost_currency 列，失败时为 NULL'' AFTER total_tokens',
    'SELECT ''kb_llm_call_log.cost_amount already exists, skipping'' AS message');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'kb_llm_call_log' AND COLUMN_NAME = 'cost_currency');
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE kb_llm_call_log ADD COLUMN cost_currency CHAR(3) NULL COMMENT ''成本币种：CNY=人民币, USD=美元，失败时为 NULL'' AFTER cost_amount',
    'SELECT ''kb_llm_call_log.cost_currency already exists, skipping'' AS message');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------------------
-- 迁移已有数据（仅在旧列 cost_usd 仍存在时执行）
-- ---------------------------------------------------------------------------
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'kb_llm_call_log' AND COLUMN_NAME = 'cost_usd');
SET @sql = IF(@col_exists = 1,
    'UPDATE kb_llm_call_log log JOIN kb_llm_model model ON log.model_id = model.id SET log.cost_amount = log.cost_usd, log.cost_currency = model.currency WHERE log.cost_usd IS NOT NULL',
    'SELECT ''cost_usd not found, skipping data migration'' AS message');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'kb_llm_call_log' AND COLUMN_NAME = 'cost_usd');
SET @sql = IF(@col_exists = 1,
    'UPDATE kb_llm_call_log SET cost_currency = ''CNY'' WHERE cost_amount IS NOT NULL AND cost_currency IS NULL',
    'SELECT ''cost_usd not found, skipping CNY fillback'' AS message');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------------------
-- 删除旧列 cost_usd（幂等：列不存在时跳过）
-- ---------------------------------------------------------------------------
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'kb_llm_call_log' AND COLUMN_NAME = 'cost_usd');
SET @sql = IF(@col_exists = 1,
    'ALTER TABLE kb_llm_call_log DROP COLUMN cost_usd',
    'SELECT ''cost_usd not found, skipping drop'' AS message');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
