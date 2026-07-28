-- kb_llm_health_log LLM 供应商健康检查日志表
-- Append-only，无 UPDATE/DELETE，可定期清理（建议保留 30 天）
-- 日志表为纯追加表，不需要 updated_at / is_deleted / deleted_at（见 docs/specs/db-conventions.md §7.1 例外说明）
-- DDL 定义见 docs/specs/llm-provider.md §9.2 / docs/specs/db-conventions.md §7.5，本文件由 MySQL 容器初始化时自动执行

CREATE TABLE IF NOT EXISTS kb_llm_health_log (
    id           BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    provider_id  BIGINT UNSIGNED  NOT NULL                COMMENT '供应商 kb_llm_provider.id',
    model_id     BIGINT UNSIGNED  NULL                    COMMENT '被检测模型 kb_llm_model.id，供应商级检查为 NULL',
    check_at     DATETIME(3)      NOT NULL                COMMENT '检查时间',
    latency_ms   INT              NULL                    COMMENT '响应延迟毫秒，超时为 NULL',
    is_success   TINYINT(1) UNSIGNED NOT NULL             COMMENT '0=失败 1=成功',
    error_msg    VARCHAR(500)     NULL                    COMMENT '失败原因（须脱敏，禁止含 API Key）',
    created_at   DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id),
    KEY idx_provider_time (provider_id, check_at),
    KEY idx_model_time (model_id, check_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM 供应商健康检查日志';
