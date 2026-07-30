-- kb_pipeline_run 工作流执行指标表
-- 每次工作流执行一行，记录 trace_id / 起止时间 / 终态 / 转化漏斗
-- 纯追加日志表（db-conventions §7.1 例外）：仅需 id + created_at，无 updated_at / is_deleted / deleted_at
-- PRD: _bmad-output/planning-artifacts/prd-pipeline-metrics.md
-- 架构: _bmad-output/planning-artifacts/arch-pipeline-metrics.md

CREATE TABLE IF NOT EXISTS kb_pipeline_run (
    id              BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    trace_id        VARCHAR(16)      NOT NULL                COMMENT '链路追踪ID，关联 kb_node_metric.trace_id',
    status          VARCHAR(20)      NOT NULL                COMMENT '执行终态 success/human_flagged/error',
    started_at      DATETIME(3)      NULL                    COMMENT '工作流开始时间',
    ended_at        DATETIME(3)      NULL                    COMMENT '工作流结束时间',
    duration_ms     INT              NULL                    COMMENT '总耗时毫秒',
    source_count    INT              NOT NULL DEFAULT 0      COMMENT '采集条目数（M5漏斗入口）',
    analysis_count  INT              NOT NULL DEFAULT 0      COMMENT '分析条目数（M5漏斗中间）',
    article_count   INT              NOT NULL DEFAULT 0      COMMENT '整理后条目数（M5漏斗中间）',
    saved_count     INT              NOT NULL DEFAULT 0      COMMENT '保存条目数（M5漏斗出口）',
    human_flagged   TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否被人工标记 0=否 1=是',
    review_passed   TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '审核是否通过 0=否 1=是',
    iteration       INT              NOT NULL DEFAULT 0      COMMENT '审核循环次数',
    total_cost_yuan DECIMAL(12,6)    NOT NULL DEFAULT 0.000000 COMMENT 'LLM总成本（元）',
    created_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '记录创建时间',
    PRIMARY KEY (id),
    KEY idx_trace_id (trace_id),
    KEY idx_status_created (status, created_at),
    KEY idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='工作流执行指标表（纯追加日志表）';


-- kb_node_metric 节点级指标表
-- 每个节点每次执行一行（含循环中的重复执行）
-- 通过 run_id 和 trace_id 关联到 kb_pipeline_run（应用层维护，非 FK）
-- 纯追加日志表（db-conventions §7.1 例外）

CREATE TABLE IF NOT EXISTS kb_node_metric (
    id              BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    run_id          BIGINT UNSIGNED  NOT NULL                COMMENT '关联 kb_pipeline_run.id（应用层维护，非FK）',
    trace_id        VARCHAR(16)      NOT NULL                COMMENT '链路追踪ID',
    node_name       VARCHAR(20)      NOT NULL                COMMENT '节点名称 collect/analyze/review/organize/revise/save/human_flag',
    duration_ms     INT              NOT NULL                COMMENT '节点耗时毫秒',
    cost_data       JSON             NULL                    COMMENT '节点LLM成本数据 {prompt_tokens,completion_tokens,total_tokens}',
    review_passed   TINYINT(1) UNSIGNED NULL                 COMMENT '审核是否通过（仅review节点填充）',
    iteration       INT              NULL                    COMMENT '审核轮次（仅review节点填充）',
    error           VARCHAR(500)     NOT NULL DEFAULT ''     COMMENT '错误信息（脱敏后，正常执行时为空）',
    created_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '记录创建时间',
    PRIMARY KEY (id),
    KEY idx_run_id (run_id),
    KEY idx_trace_id (trace_id),
    KEY idx_node_created (node_name, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='节点级指标表（纯追加日志表）';
