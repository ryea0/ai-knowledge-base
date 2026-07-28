-- kb_llm_provider LLM 供应商表
-- 仅存储连接配置和鉴权信息，健康状态移至 kb_llm_health（模型级）。
-- DDL 定义见 docs/specs/llm-provider.md §9.1 / docs/specs/db-conventions.md §7.5，本文件由 MySQL 容器初始化时自动执行

CREATE TABLE IF NOT EXISTS kb_llm_provider (
    id                      BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    provider_code           VARCHAR(40)      NOT NULL                COMMENT '供应商代码，如 deepseek/ark/openai/ollama',
    display_name            VARCHAR(80)      NOT NULL                COMMENT '展示名称',
    provider_type           TINYINT UNSIGNED NOT NULL DEFAULT 0      COMMENT '类型 0=cloud 1=local，枚举 LlmProviderType',
    base_url                VARCHAR(255)     NOT NULL                COMMENT 'API 基础 URL',
    litellm_provider        VARCHAR(40)      NOT NULL                COMMENT 'LiteLLM 供应商标识，决定协议族和模型前缀，如 openai/ollama',
    -- 鉴权（auth_config JSON 已拆为显式列）
    auth_type               TINYINT UNSIGNED NOT NULL DEFAULT 0      COMMENT '鉴权方式 0=bearer 1=oauth 2=header 3=none，枚举 LlmAuthType',
    api_key_encrypted       VARCHAR(255)     NULL                    COMMENT '加密主凭证，须应用层加解密，none 类型为 NULL',
    secret_key_encrypted    VARCHAR(255)     NULL                    COMMENT '加密二次凭证，仅 auth_type=oauth 使用',
    header_name             VARCHAR(100)     NULL                    COMMENT '自定义鉴权 header 名，仅 auth_type=header 使用',
    token_url               VARCHAR(255)     NULL                    COMMENT 'OAuth token 交换地址，仅 auth_type=oauth 使用',
    -- 路由与限流
    is_enabled              TINYINT(1) UNSIGNED NOT NULL DEFAULT 1   COMMENT '是否启用 0=禁用 1=启用',
    priority                INT              NOT NULL DEFAULT 100    COMMENT '路由优先级，数值越小优先级越高，同优先级按 id 升序',
    timeout_seconds         INT              NOT NULL DEFAULT 30     COMMENT '单次请求超时秒数，local 类型建议 120+',
    max_retries             INT              NOT NULL DEFAULT 3      COMMENT '最大重试次数上限（按错误类型策略取 min）',
    rpm_limit               INT              NOT NULL DEFAULT 0      COMMENT '每分钟请求上限，0=不限速（预留，一期不实现）',
    -- 软删除（见 docs/specs/db-conventions.md §7.1 必选字段）
    is_deleted              TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否软删除 0=否 1=是',
    deleted_at              DATETIME(3)      NULL                    COMMENT '软删除时间',
    -- provider_code 唯一约束：软删除行 guard 列为 NULL（允许多个），未删除行为 'code:{provider_code}'
    provider_code_guard     VARCHAR(46)      AS (CASE WHEN is_deleted=0 THEN CONCAT('code:',provider_code) ELSE NULL END) STORED COMMENT 'provider_code 唯一约束辅助列，软删除行排除',
    created_at              DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at              DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_provider_code_guard (provider_code_guard),
    KEY idx_enabled_priority (is_enabled, priority),
    KEY idx_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM 供应商表';
