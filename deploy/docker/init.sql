-- kb_article 知识条目表
-- DDL 定义见 AGENTS.md §7.5，本文件由 MySQL 容器初始化时自动执行

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
    created_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_article_id (article_id),
    KEY idx_source_url (source_url(255)),
    KEY idx_status_created (status, created_at),
    KEY idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识条目表';
