# 数据库设计规范（MySQL）

> 本文件从 AGENTS.md §7 拆分而来，章节编号保持不变。
> 以下规范综合阿里巴巴 Java 开发手册（MySQL 篇）及互联网公司常见 MySQL 最佳实践，AI 生成 DDL / 查询语句时须逐条遵守。

---

## §7.1 建表规范

| 规则 | 说明 |
| ---- | ---- |
| **存储引擎** | 统一使用 `InnoDB`，禁止使用 `MyISAM`。 |
| **字符集** | 统一使用 `utf8mb4`，排序规则使用 `utf8mb4_0900_ai_ci`（MySQL 8.0+）或 `utf8mb4_unicode_ci`。禁止使用 `utf8`（实为 3 字节，无法存储 Emoji）。 |
| **表名** | 全小写 `snake_case`，禁止使用驼峰、拼音、数据库保留字；须加业务前缀（如 `kb_article`）。 |
| **字段名** | 全小写 `snake_case`，禁止使用数据库保留字（`desc`/`order`/`type` 等，须加业务前缀如 `article_type`）。 |
| **主键** | 每张表必须有主键，推荐使用 `BIGINT UNSIGNED AUTO_INCREMENT` 或分布式 ID。**禁止**使用 `UUID` 作为聚簇索引主键（页分裂严重）。 |
| **必选字段** | 每张业务表须包含：`id`（主键）、`created_at`（创建时间）、`updated_at`（更新时间，须设置 `ON UPDATE CURRENT_TIMESTAMP`）、`is_deleted`（软删除标记，`TINYINT(1) UNSIGNED NOT NULL DEFAULT 0`）、`deleted_at`（软删除时间，`DATETIME(3) NULL`）。**纯追加日志表**（如 `kb_llm_call_log`）例外，仅需 `id` + `created_at`，不需要 `updated_at` / `is_deleted` / `deleted_at`。 |
| **软删除** | 业务表禁止物理删除（`DELETE FROM`），须使用软删除（`UPDATE SET is_deleted=1, deleted_at=NOW(3)`）。所有查询须过滤 `WHERE is_deleted = 0`。唯一约束须使用 guard 生成列排除软删除行（软删除行 guard = NULL，MySQL 唯一索引允许多个 NULL）。 |
| **禁用外键** | 禁止使用 `FOREIGN KEY`，关联关系在应用层维护。 |
| **禁用存储过程/触发器/视图** | 业务逻辑不沉入数据库层，便于迁移和调试。 |
| **禁止使用数据库枚举** | 不使用 `ENUM` 类型，状态字段使用 `TINYINT UNSIGNED` 并在代码层映射；或在 MySQL 8.0+ 使用 `CHECK` 约束。 |
| **金额/精度** | 金额字段禁止使用 `FLOAT`/`DOUBLE`，须使用 `DECIMAL(18,2)` 或整数分。 |

## §7.2 字段类型规范

| 场景 | 推荐类型 | 禁止 |
| ---- | -------- | ---- |
| 布尔值 | `TINYINT(1) UNSIGNED`（0/1） | `BOOLEAN` / `ENUM('Y','N')` |
| 短文本（< 255 字符） | `VARCHAR(n)`，n 须为合理值 | `TEXT` |
| 长文本 / Markdown 原文 | `MEDIUMTEXT` 或 `LONGTEXT` | `VARCHAR(10000)` |
| JSON 结构化数据 | `JSON`（MySQL 8.0+） | `TEXT` 手动序列化 |
| 时间戳 | `DATETIME(3)`（毫秒精度），应用层统一写 UTC | `VARCHAR` 存时间字符串；`TIMESTAMP`（2038 问题 + 时区隐式转换） |
| IP 地址 | `VARBINARY(16)` 或 `VARCHAR(45)` | `INT` |
| 布尔状态多值 | 位运算 `BIGINT` + 应用层解释 | 多列 `TINYINT` |

## §7.3 索引规范

1. **索引命名**：普通索引前缀 `idx_`；唯一索引前缀 `uk_`；全文索引前缀 `ft_`。如 `idx_source_url`、`uk_article_id`。
2. **单表索引数**：单表索引数量不超过 **5 个**，单索引字段数不超过 **5 列**。
3. **覆盖索引优先**：高频查询须设计覆盖索引（包含 `SELECT` 所需全部字段），避免回表。
4. **最左前缀原则**：联合索引须按区分度从高到低排列，查询条件须满足最左前缀。
5. **禁止在索引列上使用函数**：`WHERE DATE(created_at) = '2026-07-27'` 会导致索引失效，须改写为 `WHERE created_at >= '2026-07-27' AND created_at < '2026-07-28'`。
6. **禁止 `SELECT *`**：一律显式指定字段列表，避免覆盖索引失效和列变更导致的隐式错误。
7. **LIKE 优化**：禁止左模糊 `LIKE '%keyword'`（索引失效），须使用右模糊 `LIKE 'keyword%'` 或全文索引。
8. **前缀索引**：对长字符串列（如 `VARCHAR(500)`）建索引时，使用前缀索引 `idx_col(prefix_len)`，减少索引体积。

## §7.4 SQL 编写规范

1. **大写关键字**：SQL 关键字（`SELECT`/`FROM`/`WHERE`/`JOIN`/`GROUP BY` 等）一律大写，表名/字段名小写。
2. **表别名**：多表 JOIN 必须使用有语义的别名（如 `article a`、`raw_content r`）；单表简单查询允许使用任意别名。
3. **JOIN 规范**：禁止使用逗号隐式 JOIN（`FROM a, b WHERE a.id = b.id`），须使用显式 `INNER JOIN` / `LEFT JOIN`。
4. **分页规范**：深度分页（`OFFSET > 10000`）须使用延迟关联或游标分页（`WHERE id > last_id LIMIT n`），禁止直接 `LIMIT 100000, 20`。
5. **批量写入**：单条 `INSERT` 语句须使用多值形式 `INSERT INTO ... VALUES (...), (...), (...)`，单批次不超过 **500 行**。
6. **事务范围**：事务须尽可能短小，禁止在事务中包含远程调用（HTTP 请求 / RPC）。事务中只做数据库操作。
7. **避免大事务**：单事务影响行数超过 **1000 行**时须拆分批次提交，避免长事务锁争用和 binlog 膨胀。
8. **ORM 使用**：使用 SQLAlchemy 时禁止拼接原生 SQL 字符串（SQL 注入风险），须使用参数绑定或 ORM 查询构造器。

## §7.5 表设计示例

以知识条目表为例（实际 DDL 见 `deploy/sql/`）：

```sql
CREATE TABLE kb_article (
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
    is_deleted           TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否软删除 0=否 1=是',
    deleted_at           DATETIME(3)      NULL                    COMMENT '软删除时间',
    created_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_article_id (article_id),
    KEY idx_source_url (source_url(255)),
    KEY idx_status_created (status, created_at),
    KEY idx_category (category),
    KEY idx_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识条目表';
```
