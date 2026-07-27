# 01 - 基础设施：数据契约 + 持久化协议 + 配置（预重构）

> 对应 GitHub Issue: [#4](https://github.com/ryea0/ai-knowledge-base/issues/4)

## 要构建什么

建立所有下游流水线阶段所依赖的基础数据层与持久化协议。这是一张预重构（prefactor）工单：它让后续的 collector/analyzer/organizer 切片能轻松落地并保持绿色通过。

定义强制阶段间交接的 Pydantic 数据契约、`kb_article` 的 SQLAlchemy ORM 映射、`ArticleRepository` 协议（测试用纯内存 fake，**禁止 SQLite**，见 G3）、配置加载器，以及三个分析深度列的 DDL schema 扩展。

## 验收标准

- [ ] Pydantic 模型 `CollectorCandidate`、`AnalyzerResult`、`KnowledgeArticle` 位于 `src/models/`，复用现有 `src/models/enums.py`（`ArticleStatus`、`Category`、`SourcePlatform`）作为枚举值的唯一定义点
- [ ] `KnowledgeArticle` 包含 §4.10 扩展字段 `score` / `score_reason` / `highlights`，设为 `Optional`（默认 `None`），以向后兼容解析现有 10 个旧 slug 命名 JSON 文件（G9）
- [ ] `kb_article` 的 SQLAlchemy ORM 模型位于 `src/models/`；禁止拼接原生 SQL 字符串
- [ ] `ArticleRepository` Protocol 定义于 `src/models/`（或 `src/graph/`），方法包括：`insert_placeholder`、`get_by_url`、`update_fields`、`update_status`、`get_last_insert_id`、`delete_by_id`——生产实现用 SQLAlchemy+MySQL，测试用纯 Python dict fake
- [ ] **测试禁用 SQLite**（G3）：与 MySQL 的 `JSON` / `DATETIME(3)` / `LAST_INSERT_ID()` 特性不兼容；测试中仅使用内存 fake
- [ ] `src/config/` 模块按 §2.4 加载环境变量（MYSQL_HOST/PORT/USER/PASSWORD/DATABASE、LLM_API_KEY/BASE/MODEL、GITHUB_TOKEN），并由各字段拼装 DB 连接串（`mysql+pymysql://{user}:{password}@{host}:{port}/{database}`）——禁止使用单一 `DATABASE_URL`
- [ ] `src/config/` 暴露 `DEDUP_THRESHOLD`（默认 `0.8`，G6）
- [ ] `deploy/docker/init.sql` 中 DDL 扩展：`kb_article` 新增 `score TINYINT UNSIGNED NULL`、`score_reason VARCHAR(500) NULL`、`highlights JSON NULL`；**不为 `score` 新建索引**（G8）；现有 4 个索引保持不变
- [ ] `tests/models/test_schemas.py` 中的 schema 契约测试覆盖：每个模型的有效/无效载荷；无 `score` 字段的旧 JSON 可解析且 `score=None`（G9）；枚举 parse/serialize 往返
- [ ] `uv run ruff check src/ tests/` 通过
- [ ] `uv run mypy src/` 通过（strict 模式）

## 被阻塞

- 无——可立即开始。

---

*tracer-bullet 基础切片。端到端贯穿 schema + 配置 + 测试接缝层，使后续阶段建立在已验证的契约之上。*
