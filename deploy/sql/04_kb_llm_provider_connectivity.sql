-- kb_llm_provider_connectivity 供应商联通性状态表
-- 供应商级当前联通性（upsert 语义），每个供应商至多一行。
-- 由定时任务（每 5 分钟）或手动触发连通性测试时写入/更新。
-- DDL 约定见 docs/specs/db-conventions.md §7，本文件由 MySQL 容器初始化时自动执行

CREATE TABLE IF NOT EXISTS kb_llm_provider_connectivity (
    id                BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    provider_id       BIGINT UNSIGNED  NOT NULL                COMMENT '供应商 kb_llm_provider.id（应用层维护关联）',
    is_connected      TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否连通 0=否 1=是',
    latency_ms        INT              NULL                    COMMENT '最近探测延迟毫秒',
    last_check_at     DATETIME(3)      NULL                    COMMENT '最近探测时间',
    last_success_at   DATETIME(3)      NULL                    COMMENT '最近成功时间',
    last_failure_at   DATETIME(3)      NULL                    COMMENT '最近失败时间',
    last_error        VARCHAR(500)     NULL                    COMMENT '最近错误信息（须脱敏，禁止含 API Key）',
    -- 软删除（见 docs/specs/db-conventions.md §7.1 必选字段）
    is_deleted        TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否软删除 0=否 1=是',
    deleted_at        DATETIME(3)      NULL                    COMMENT '软删除时间',
    -- provider_id 唯一约束：软删除行 guard 列为 NULL，未删除行为 'pc:{provider_id}'
    provider_connectivity_guard VARCHAR(40) AS (CASE WHEN is_deleted=0 THEN CONCAT('pc:',provider_id) ELSE NULL END) STORED COMMENT 'provider_id 唯一约束辅助列，每供应商至多一行联通状态',
    created_at        DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at        DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_provider_connectivity_guard (provider_connectivity_guard),
    KEY idx_provider_id (provider_id),
    KEY idx_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM 供应商联通性状态表';
