-- kb_llm_model LLM 模型表
-- DDL 定义见 docs/specs/llm-provider.md §9.1 / docs/specs/db-conventions.md §7.5，本文件由 MySQL 容器初始化时自动执行

CREATE TABLE IF NOT EXISTS kb_llm_model (
    id                        BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    provider_id               BIGINT UNSIGNED  NOT NULL                COMMENT '所属供应商 kb_llm_provider.id（应用层维护关联）',
    model_code                VARCHAR(80)      NOT NULL                COMMENT '模型标识，如 deepseek-chat / llama3.2',
    litellm_model             VARCHAR(120)     NOT NULL                COMMENT 'LiteLLM 完整模型标识，如 deepseek/deepseek-chat / ollama/llama3.2',
    display_name              VARCHAR(120)     NOT NULL                COMMENT '展示名称',
    description               VARCHAR(255)     NULL                    COMMENT '模型描述',
    context_window            INT              NOT NULL DEFAULT 4096   COMMENT '上下文窗口大小 tokens',
    max_output_tokens         INT              NOT NULL DEFAULT 4096   COMMENT '最大输出 tokens',
    supports_streaming        TINYINT(1) UNSIGNED NOT NULL DEFAULT 1   COMMENT '是否支持流式输出',
    supports_function_calling TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否支持函数调用',
    supports_vision           TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否支持视觉/多模态',
    supports_reasoning        TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否为推理模型（content 空 / reasoning_content / thinking_blocks）',
    task_type                 JSON             NULL                    COMMENT '任务类型数组，如 ["TextGeneration"]、["VisualQuestionAnswering"]',
    input_price_per_1m        DECIMAL(10,4)    NOT NULL DEFAULT 0.0000 COMMENT '输入每百万 token 价格，币种见 currency 列，local=0',
    output_price_per_1m       DECIMAL(10,4)    NOT NULL DEFAULT 0.0000 COMMENT '输出每百万 token 价格，币种见 currency 列，local=0',
    currency                  CHAR(3)          NOT NULL DEFAULT 'CNY'  COMMENT '计费币种：CNY=人民币, USD=美元',
    is_enabled                TINYINT(1) UNSIGNED NOT NULL DEFAULT 1   COMMENT '是否启用',
    is_default                TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否为该供应商默认模型，每供应商至多1个',
    source                    TINYINT UNSIGNED NOT NULL DEFAULT 0      COMMENT '来源 0=preset 1=discovered 2=manual，枚举 LlmModelSource',
    -- 每供应商至多一个默认模型：is_default=1 且未删除时 default_guard='p:{provider_id}'，唯一约束保证；其余为 NULL
    default_guard             VARCHAR(40)      AS (CASE WHEN is_default=1 AND is_deleted=0 THEN CONCAT('p:',provider_id) ELSE NULL END) STORED COMMENT '默认模型唯一约束辅助列',
    -- 软删除（见 docs/specs/db-conventions.md §7.1 必选字段）
    is_deleted                TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否软删除 0=否 1=是',
    deleted_at                DATETIME(3)      NULL                    COMMENT '软删除时间',
    -- (provider_id, model_code) 唯一约束：软删除行 guard 列为 NULL，未删除行为 'pm:{provider_id}:{model_code}'
    provider_model_guard      VARCHAR(130)     AS (CASE WHEN is_deleted=0 THEN CONCAT('pm:',provider_id,':',model_code) ELSE NULL END) STORED COMMENT '(provider_id,model_code) 唯一约束辅助列，软删除行排除',
    created_at                DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at                DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_default_guard (default_guard),
    UNIQUE KEY uk_provider_model_guard (provider_model_guard),
    KEY idx_provider_enabled (provider_id, is_enabled),
    KEY idx_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM 模型表';
