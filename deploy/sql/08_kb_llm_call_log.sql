-- kb_llm_call_log LLM 调用计量日志表
-- 记录每次 LLM 调用的 token 用量和成本，用于供应商成本追踪和用量分析
-- 每次调用一行，成功/失败均记录（失败时 usage 为 NULL）
-- DDL 约定见 docs/specs/db-conventions.md §7.1，本文件由 MySQL 容器初始化时自动执行

CREATE TABLE IF NOT EXISTS kb_llm_call_log (
    id              BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    trace_id        VARCHAR(16)      NOT NULL                COMMENT '链路追踪ID，关联工作流执行',
    provider_id     BIGINT UNSIGNED  NOT NULL                COMMENT '供应商 kb_llm_provider.id',
    model_id        BIGINT UNSIGNED  NOT NULL                COMMENT '模型 kb_llm_model.id',
    is_success      TINYINT(1) UNSIGNED NOT NULL             COMMENT '0=失败 1=成功',
    input_tokens    INT              NULL                    COMMENT '输入 token 数，失败时为 NULL',
    output_tokens   INT              NULL                    COMMENT '输出 token 数，失败时为 NULL',
    total_tokens    INT              NULL                    COMMENT '总 token 数，失败时为 NULL',
    cost_amount     DECIMAL(10,6)    NULL                    COMMENT '预估成本金额，币种见 cost_currency 列，失败时为 NULL',
    cost_currency   CHAR(3)          NULL                    COMMENT '成本币种：CNY=人民币, USD=美元，失败时为 NULL',
    latency_ms      INT              NULL                    COMMENT '响应延迟毫秒，失败时为 NULL',
    error_msg       VARCHAR(500)     NULL                    COMMENT '失败原因（脱敏后，禁止含 API Key）',
    called_at       DATETIME(3)      NOT NULL                COMMENT '调用时间',
    -- 软删除（见 docs/specs/db-conventions.md §7.1 必选字段）
    is_deleted      TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否软删除 0=否 1=是',
    deleted_at      DATETIME(3)      NULL                    COMMENT '软删除时间',
    created_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    KEY idx_trace_id (trace_id),
    KEY idx_provider_time (provider_id, called_at),
    KEY idx_model_time (model_id, called_at),
    KEY idx_called_at (called_at),
    KEY idx_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM 调用计量日志表';
