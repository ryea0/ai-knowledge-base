-- kb_workflow_run 工作流执行历史表
-- 记录每次工作流执行的 trace_id / 阶段 / 耗时 / 状态，供前端「工作流管理」页面展示
-- trace_id 为业务唯一标识（UUIDv4 前8位），全局唯一
-- DDL 约定见 docs/specs/db-conventions.md §7.1 / docs/specs/trace-spec.md §10，本文件由 MySQL 容器初始化时自动执行

CREATE TABLE IF NOT EXISTS kb_workflow_run (
    id              BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    trace_id        VARCHAR(16)      NOT NULL                COMMENT '链路追踪ID，UUIDv4 前8位十六进制，每次工作流执行唯一',
    stage           VARCHAR(20)      NOT NULL                COMMENT '执行阶段 collect/analyze/curate/distribute/all',
    status          VARCHAR(20)      NOT NULL DEFAULT 'running' COMMENT '执行状态 running/success/failed',
    started_at      DATETIME(3)      NOT NULL                COMMENT '执行开始时间',
    finished_at     DATETIME(3)      NULL                    COMMENT '执行结束时间，运行中为 NULL',
    duration_ms     INT              NULL                    COMMENT '执行耗时毫秒，运行中为 NULL',
    candidate_count INT              NOT NULL DEFAULT 0      COMMENT '采集候选条目数',
    article_count   INT              NOT NULL DEFAULT 0      COMMENT '产出知识条目数',
    error_summary   VARCHAR(500)     NULL                    COMMENT '错误摘要（脱敏后，禁止含 API Key）',
    -- 软删除（见 docs/specs/db-conventions.md §7.1 必选字段）
    is_deleted      TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否软删除 0=否 1=是',
    deleted_at      DATETIME(3)      NULL                    COMMENT '软删除时间',
    created_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_trace_id (trace_id),
    KEY idx_status_started (status, started_at),
    KEY idx_stage_started (stage, started_at),
    KEY idx_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='工作流执行历史表';
