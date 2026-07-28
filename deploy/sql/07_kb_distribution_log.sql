-- kb_distribution_log 分发历史日志表
-- 记录每次分发的推送结果，供前端「分发渠道」页面展示分发历史和手动重发
-- 每条知识条目每次推送一行，成功/跳过/失败均记录
-- DDL 约定见 docs/specs/db-conventions.md §7.1 / docs/specs/content-spec.md §6.6，本文件由 MySQL 容器初始化时自动执行

CREATE TABLE IF NOT EXISTS kb_distribution_log (
    id              BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    article_id      VARCHAR(32)      NOT NULL                COMMENT '条目业务ID kb-YYYYMMDD-NNNN',
    channel         VARCHAR(20)      NOT NULL                COMMENT '推送渠道 telegram/feishu',
    result          VARCHAR(20)      NOT NULL                COMMENT '推送结果 success/skipped/failed',
    attempted_at    DATETIME(3)      NOT NULL                COMMENT '推送尝试时间',
    error_msg       VARCHAR(500)     NULL                    COMMENT '失败原因（脱敏后，禁止含 Token/Webhook URL）',
    -- 软删除（见 docs/specs/db-conventions.md §7.1 必选字段）
    is_deleted      TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否软删除 0=否 1=是',
    deleted_at      DATETIME(3)      NULL                    COMMENT '软删除时间',
    created_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    KEY idx_article_id (article_id),
    KEY idx_channel_result (channel, result),
    KEY idx_attempted_at (attempted_at),
    KEY idx_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='分发历史日志表';
