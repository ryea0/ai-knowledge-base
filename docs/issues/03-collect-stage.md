# 03 - 采集阶段：GH Trending + HN 采集器 + persist_raw 取号前置

> 对应 GitHub Issue: [#6](https://github.com/ryea0/ai-knowledge-base/issues/6)

## 要构建什么

实现真实的 collector 节点与 graph 层 `persist_raw` 步骤。collector 抓取 GitHub Trending Top 50 并通过 Official API 拉取 Hacker News 热门条目，按 AI/LLM/Agent 关键词过滤，按 `popularity` 降序排序，返回内存候选列表（不写文件--collector 为只读）。`persist_raw` 随后对每条候选插入 DB 占位行，通过 `build_article_id` 生成 `article_id`，写入 `knowledge/raw/<article_id>.md`，并将候选元信息送入 graph 状态供下游使用。

本切片交付完整的 collect->persist_raw 路径：外部数据源 -> 过滤后候选 -> DB 占位行 -> 磁盘上的 raw MD 文件，可通过运行 `--stage collect` 并检查 `knowledge/raw/` 来演示。

## 验收标准

- [ ] `src/utils/http_client.py` 封装 `httpx`（G10），含：速率限制（GitHub 匿名 ≥2s / 带 Token ≥0.5s，HN ≥1s，见 docs/specs/content-spec.md §6.1）、指数退避（初始 1s、×2 倍增、上限 60s、429/5xx/网络错误最多重试 3 次）、单次请求超时 30s、`ThreadPoolExecutor max_workers ≤ 5`
- [ ] 现有 `src/utils/github_api.py` 从 `urllib` 迁移至 `httpx`（或被 `http_client.py` 取代）
- [ ] `src/collectors/` 实现 GitHub Trending 爬虫：解析 trending 列表，提取 title/url/stars，抓取 README
- [ ] `src/collectors/` 实现 HN 采集器，使用 Official API（Firebase `https://hacker-news.firebaseio.com/v0/`，`/v0/topstories` + `/v0/item/<id>`，G15）；`popularity` = HN points
- [ ] AI/LLM/Agent 关键词过滤（§6.1 词表：llm、gpt、transformer、fine-tuning、rag、agent、multimodal、embedding、vllm、langchain、llama、diffusion……）
- [ ] 候选按 `popularity` 降序排序；GitHub 的 `popularity` = 总 star 数（G13）
- [ ] 每条候选在离开节点前验证为 `CollectorCandidate`（Pydantic）
- [ ] **幂等性**：在抓取/处理每条候选前，通过 `repo.get_by_url` 查询 DB `kb_article.source_url`；已存在则跳过。**无退化路径**（G2）--幂等检查一律查 DB（测试时由 repo fake 提供结果）
- [ ] `persist_raw` graph 层步骤（`src/graph/` 中的普通函数）在一个 DB 事务内执行取号前置（G1）：`INSERT` 占位行（`status=pending`，`source_url`/`source_platform`/`source_score`/`collected_at` 已填，其余默认）-> `LAST_INSERT_ID()` -> `build_article_id(id, collected_at)` -> `UPDATE` 回填 `article_id` -> commit
- [ ] commit 之后，`persist_raw` 在 DB 事务**之外**写入 `knowledge/raw/<article_id>.md`（G11），内容含来源标题、URL、正文、采集时间
- [ ] 实现真实的 SQLAlchemy `ArticleRepository` 写方法（`insert_placeholder`、`get_by_url`、`get_last_insert_id`）；测试复用工单 01 的内存 fake
- [ ] `--stage collect` 运行 collector + persist_raw，产出 raw MD 文件 + DB 占位行
- [ ] Graph 测试（扩展 `tests/graph/test_pipeline.py` 主接缝），用 HTTP fetcher fakes 覆盖：成功、404、429、超时；断言 raw MD 已写、DB 占位行存在且 `status=pending`、`article_id` 格式为 `kb-YYYYMMDD-NNNN`
- [ ] collector 在开始/完成时记录 INFO 级日志（§6.1，AC 63）
- [ ] `uv run ruff check src/ tests/` 通过
- [ ] `uv run mypy src/` 通过

## 被阻塞

- [#5](./02-walking-skeleton.md)（骨架）--需要 graph 脊柱、`Deps` 容器和 `ArticleRepository` 协议来接线 collector + persist_raw 节点。

---

*tracer-bullet 采集切片。贯穿 HTTP 客户端 + 爬虫 + DB 占位行 + raw MD 写入--一条完整的"数据源到磁盘"路径。*
