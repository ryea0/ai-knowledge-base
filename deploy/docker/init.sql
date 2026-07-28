-- 本文件为 MySQL 容器初始化入口，按编号顺序加载 deploy/sql/ 下所有 .sql 文件。
-- Docker 容器通过 volume 挂载 deploy/sql/ 到 /docker-entrypoint-initdb.d/ 自动执行。
-- DDL 定义见 docs/specs/db-conventions.md §7.5（kb_article）与 docs/specs/llm-provider.md §9（LLM 供应商三张表）。
-- 1. 知识条目表（本文件内联定义，因早于 deploy/sql/ 拆分）
CREATE TABLE IF NOT EXISTS kb_article (
    id              BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键，同时作为 article_id 的序号源（NNNN），全局递增不按日重置',
    article_id      VARCHAR(32)      NOT NULL                COMMENT '业务ID，格式 kb-YYYYMMDD-NNNN，NNNN=id 零填充至4位，id>9999 报错',
    title           VARCHAR(120)     NOT NULL                COMMENT '条目标题（内容规范见 §6.2，DB 长度为上限）',
    source_url      VARCHAR(512)     NOT NULL                COMMENT '原始链接',
    source_platform VARCHAR(20)      NOT NULL                COMMENT '来源平台 github_trending/hackernews，新增来源须同步更新 §4 与 src/models/enums.py',
    source_score    INT              NOT NULL DEFAULT 0      COMMENT '来源热度',
    summary         VARCHAR(500)     NOT NULL                COMMENT 'AI生成中文摘要（内容规范见 §6.3，DB 长度为上限）',
    content_path    VARCHAR(255)     NOT NULL                COMMENT '原始内容文件路径',
    tags            JSON             NOT NULL                COMMENT '标签数组',
    category        VARCHAR(20)      NOT NULL                COMMENT '分类 model_release/paper/tool/tutorial/news，判定标准见 §6.5',
    status          TINYINT UNSIGNED NOT NULL DEFAULT 0      COMMENT '状态 0=pending 1=reviewed 2=published 3=archived，枚举定义见 src/models/enums.py ArticleStatus',
    language        CHAR(2)          NOT NULL DEFAULT 'zh'   COMMENT '原文语言',
    collected_at    DATETIME(3)      NOT NULL                COMMENT '采集时间',
    analyzed_at     DATETIME(3)      NULL                    COMMENT '分析完成时间',
    published_at    DATETIME(3)      NULL                    COMMENT '发布时间',
    published_channels JSON          NULL                    COMMENT '已推送渠道列表',
    score              TINYINT UNSIGNED NULL                    COMMENT 'analyzer 评分 1-10（SPEC §4.10 扩展）',
    score_reason       VARCHAR(500)     NULL                    COMMENT '评分理由（SPEC §4.10 扩展）',
    highlights         JSON             NULL                    COMMENT '亮点数组（SPEC §4.10 扩展）',
    is_deleted           TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否软删除 0=否 1=是',
    deleted_at           DATETIME(3)      NULL                    COMMENT '软删除时间',
    created_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    -- article_id 由自增主键派生（kb-YYYYMMDD-NNNN），NNNN 全局递增不复用，
    -- 软删除行不会产生 article_id 冲突，因此直接对 article_id 建唯一索引，无需 guard 列。
    UNIQUE KEY uk_article_id (article_id),
    KEY idx_source_url (source_url(255)),
    KEY idx_status_created (status, created_at),
    KEY idx_category (category),
    KEY idx_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识条目表';
