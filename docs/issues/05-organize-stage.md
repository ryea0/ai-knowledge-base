# 05 - 整理阶段：去重 + DB UPDATE（CAS）+ JSON sidecar + MD 渲染

> 对应 GitHub Issue: [#8](https://github.com/ryea0/ai-knowledge-base/issues/8)

## 要构建什么

实现 organizer 节点：最终的回写阶段，合并候选元信息与分析结果，去重，持久化到 DB（CAS 条件更新），写入 JSON sidecar，并渲染人类可读的 Markdown 视图。本切片产出实际的知识制品--DB 行、`knowledge/articles/<article_id>.json`、`knowledge/articles/<article_id>.md`--状态均为 `status: pending`。

本切片交付完整的整理路径：状态中的候选+分析 -> 去重后的 `pending` 条目落盘并入库，可通过运行 `--stage all` 并检查每条条目的三种制品来演示。

## 验收标准

- [ ] URL 去重：跳过 `source_url` 已存在于 DB 的条目（与 collector 幂等性互为纵深防御）
- [ ] 标题相似度去重（G6）：归一化标题（去标点、小写、去停用词），计算 **Jaccard 相似度**；相似度 ≥ `DEDUP_THRESHOLD`（默认 0.8，来自 `src/config/`）的配对视为重复--保留 `source_score` 最高的一条，其余标记 `archived`
- [ ] 将候选元信息（source_url/platform/score/collected_at/content_path/article_id）与 `AnalyzerResult`（title/summary/highlights/score/score_reason/tags/category/language）合并为 `KnowledgeArticle`
- [ ] **写入时断言**（G9）：organizer 在写入新条目前断言 `score` / `highlights` / `score_reason` 非 None（Optional 默认值仅用于读取旧文件）
- [ ] DB 写入用 CAS 条件更新：`UPDATE ... SET <fields> WHERE id=... AND status=pending`（§6.6 要点 4，AC 56）；`analyzed_at` 在此 UPDATE 中设置
- [ ] 应用 `popularity` -> `source_score` 映射（G13）
- [ ] **写入顺序**（G7/G11）：DB 事务（UPDATE）commit -> JSON sidecar 写入 -> MD 渲染；所有文件 I/O 在 DB 事务**之外**（§7.4 规则 6）；MD 渲染失败不回滚 DB/JSON
- [ ] JSON sidecar 写入 `knowledge/articles/<article_id>.json`（文件名 = `article_id`，§4.9）；JSON 在关闭前经 `json.dumps` 序列化后回读校验（P2--捕获未转义引号）
- [ ] MD 渲染至 `knowledge/articles/<article_id>.md`（文件名 = `article_id`，§4.9），含标题、摘要、亮点、标签、分类、来源 URL、采集/分析时间戳，以人类可读布局呈现
- [ ] 新条目 `status: pending`；去重落选条目 `status: archived`（AC 33/34）
- [ ] 任何写入前运行 `KnowledgeArticle` Pydantic 验证（AC 32）
- [ ] `--stage organize` 运行 organizer 节点，为每条条目产出三种制品
- [ ] Graph 测试（扩展 `tests/graph/test_pipeline.py`）断言：DB 行存在且 status/timestamps/`article_id` 格式正确；JSON sidecar 符合 `KnowledgeArticle` schema；MD 文件结构正确；CAS 更新仅影响 `pending` 行
- [ ] `uv run ruff check src/ tests/` 通过
- [ ] `uv run mypy src/` 通过

## 被阻塞

- [#6](./03-collect-stage.md)（采集阶段）--需要候选元信息 + DB 占位行 + persist_raw 生成的 `article_id` 以执行 UPDATE。
- [#7](./04-analyze-stage.md)（分析阶段）--需要 `AnalyzerResult`（summary/highlights/score/score_reason/tags/category/language）以合并为最终条目。

---

*tracer-bullet 整理切片。贯穿去重 + CAS 写入 + JSON sidecar + MD 渲染--产出制品的阶段。*
