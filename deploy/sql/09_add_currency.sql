-- 迁移脚本：为 kb_llm_model 增加 currency 列，为 kb_llm_call_log 将 cost_usd 拆为 cost_amount + cost_currency
-- 适用于已有数据库的增量升级，新库由 02/08 DDL 直接包含新列

-- kb_llm_model: 新增 currency 列
ALTER TABLE kb_llm_model
    ADD COLUMN currency CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '计费币种：CNY=人民币, USD=美元'
    AFTER output_price_per_1m;

-- kb_llm_call_log: cost_usd -> cost_amount + cost_currency
ALTER TABLE kb_llm_call_log
    ADD COLUMN cost_amount DECIMAL(10,6) NULL COMMENT '预估成本金额，币种见 cost_currency 列，失败时为 NULL' AFTER total_tokens,
    ADD COLUMN cost_currency CHAR(3) NULL COMMENT '成本币种：CNY=人民币, USD=美元，失败时为 NULL' AFTER cost_amount;

-- 迁移已有数据：cost_amount = cost_usd，cost_currency 按模型 currency 填充
UPDATE kb_llm_call_log log
    JOIN kb_llm_model model ON log.model_id = model.id
    SET log.cost_amount = log.cost_usd,
        log.cost_currency = model.currency
    WHERE log.cost_usd IS NOT NULL;

-- 对无法关联模型的行，默认填充 CNY
UPDATE kb_llm_call_log
    SET cost_currency = 'CNY'
    WHERE cost_amount IS NOT NULL AND cost_currency IS NULL;

-- 删除旧列
ALTER TABLE kb_llm_call_log DROP COLUMN cost_usd;
