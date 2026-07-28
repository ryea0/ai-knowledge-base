-- kb_llm_provider LLM 供应商表
-- DDL 定义见 AGENTS.md §9.1 / §7.5，本文件由 MySQL 容器初始化时自动执行

CREATE TABLE IF NOT EXISTS kb_llm_provider (
    id                   BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    provider_code        VARCHAR(40)      NOT NULL                COMMENT '供应商代码，如 deepseek/ark/openai/ollama/llamacpp/qwen',
    display_name         VARCHAR(80)      NOT NULL                COMMENT '展示名称',
    provider_type        TINYINT UNSIGNED NOT NULL DEFAULT 0      COMMENT '类型 0=cloud 1=local，枚举 LlmProviderType',
    base_url             VARCHAR(255)     NOT NULL                COMMENT 'API 基础 URL，如 https://api.deepseek.com/v1',
    litellm_provider     VARCHAR(40)      NOT NULL                COMMENT 'LiteLLM 供应商标识，如 deepseek/openai/ollama',
    auth_type            TINYINT UNSIGNED NOT NULL DEFAULT 0      COMMENT '鉴权方式 0=bearer 1=oauth 2=header 3=none，枚举 LlmAuthType',
    api_key_encrypted    VARCHAR(255)     NULL                    COMMENT '加密后的主凭证，须应用层加解密，none 类型为 NULL',
    auth_config          JSON             NULL                    COMMENT '鉴权附加配置，结构由 auth_type 决定（见 AGENTS.md §9.1）',
    is_enabled           TINYINT(1) UNSIGNED NOT NULL DEFAULT 1   COMMENT '是否启用 0=禁用 1=启用',
    priority             INT              NOT NULL DEFAULT 100    COMMENT '路由优先级，数值越小优先级越高，同优先级按 id 升序',
    timeout_seconds      INT              NOT NULL DEFAULT 30     COMMENT '单次请求超时秒数，local 类型建议 120+',
    max_retries          INT              NOT NULL DEFAULT 3      COMMENT '最大重试次数（429/5xx 指数退避）',
    rpm_limit            INT              NOT NULL DEFAULT 0      COMMENT '每分钟请求上限，0=不限速',
    -- 健康状态（当前快照，内联避免 JOIN）
    health_status        TINYINT UNSIGNED NOT NULL DEFAULT 3      COMMENT '健康状态 0=healthy 1=degraded 2=unhealthy 3=unknown，枚举 LlmHealthStatus',
    health_check_enabled TINYINT(1) UNSIGNED NOT NULL DEFAULT 1   COMMENT '是否启用健康检查',
    last_check_at        DATETIME(3)      NULL                    COMMENT '最近健康检查时间',
    last_success_at      DATETIME(3)      NULL                    COMMENT '最近成功调用时间',
    last_failure_at      DATETIME(3)      NULL                    COMMENT '最近失败时间',
    consecutive_failures INT              NOT NULL DEFAULT 0      COMMENT '连续失败次数，成功时归零',
    failure_threshold    INT              NOT NULL DEFAULT 5      COMMENT '连续失败达此值时 health_status 转 unhealthy',
    last_error           VARCHAR(500)     NULL                    COMMENT '最近错误信息（须脱敏，禁止含 API Key）',
    -- 软删除（见 AGENTS.md §7.1 必选字段）
    is_deleted           TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否软删除 0=否 1=是',
    deleted_at           DATETIME(3)      NULL                    COMMENT '软删除时间',
    -- provider_code 唯一约束：软删除行 guard 列为 NULL（允许多个），未删除行为 'code:{provider_code}'
    provider_code_guard  VARCHAR(46)      AS (CASE WHEN is_deleted=0 THEN CONCAT('code:',provider_code) ELSE NULL END) STORED COMMENT 'provider_code 唯一约束辅助列，软删除行排除',
    created_at           DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at           DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_provider_code_guard (provider_code_guard),
    KEY idx_enabled_priority (is_enabled, priority),
    KEY idx_health_status (health_status),
    KEY idx_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM 供应商表';
