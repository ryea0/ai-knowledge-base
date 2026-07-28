-- kb_llm_health LLM 模型健康状态表
-- 模型级当前健康状态（upsert 语义），替代旧的 kb_llm_health_log（append-only 日志）。
-- 每个模型至多一行，由 uk_model_health_guard 保证。
-- 创建模型时自动创建对应 health 行（health_status=unknown），删除模型时同步软删除。
-- DDL 定义见 docs/specs/llm-provider.md §9.1-9.2 / docs/specs/db-conventions.md §7.5，本文件由 MySQL 容器初始化时自动执行

CREATE TABLE IF NOT EXISTS kb_llm_health (
    id                      BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    provider_id             BIGINT UNSIGNED  NOT NULL                COMMENT '供应商 kb_llm_provider.id（应用层维护关联）',
    model_id                BIGINT UNSIGNED  NOT NULL                COMMENT '模型 kb_llm_model.id（每个模型一行）',
    health_status           TINYINT UNSIGNED NOT NULL DEFAULT 3      COMMENT '健康状态 0=healthy 1=degraded 2=unhealthy 3=unknown，枚举 LlmHealthStatus',
    consecutive_failures    INT              NOT NULL DEFAULT 0      COMMENT '连续失败次数，成功时归零',
    failure_threshold       INT              NOT NULL DEFAULT 5      COMMENT '连续失败达此值时 health_status 转 unhealthy',
    health_check_enabled    TINYINT(1) UNSIGNED NOT NULL DEFAULT 1   COMMENT '是否启用健康检查',
    last_check_at           DATETIME(3)      NULL                    COMMENT '最近健康检查时间',
    last_success_at         DATETIME(3)      NULL                    COMMENT '最近成功时间',
    last_failure_at         DATETIME(3)      NULL                    COMMENT '最近失败时间',
    last_latency_ms         INT              NULL                    COMMENT '最近检查延迟毫秒',
    last_error              VARCHAR(500)     NULL                    COMMENT '最近错误信息（须脱敏，禁止含 API Key）',
    -- 软删除（见 docs/specs/db-conventions.md §7.1 必选字段）
    is_deleted              TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否软删除 0=否 1=是',
    deleted_at              DATETIME(3)      NULL                    COMMENT '软删除时间',
    -- model_id 唯一约束：软删除行 guard 列为 NULL，未删除行为 'mh:{model_id}'
    model_health_guard      VARCHAR(30)      AS (CASE WHEN is_deleted=0 THEN CONCAT('mh:',model_id) ELSE NULL END) STORED COMMENT 'model_id 唯一约束辅助列，每模型至多一行健康状态',
    created_at              DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at              DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_model_health_guard (model_health_guard),
    KEY idx_provider_status (provider_id, health_status),
    KEY idx_model_id (model_id),
    KEY idx_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM 模型健康状态表';
