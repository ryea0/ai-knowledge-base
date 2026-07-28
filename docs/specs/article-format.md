# 知识条目 JSON 格式

> 本文件从 AGENTS.md §4 拆分而来，章节编号保持不变。

---

## §4. 知识条目 JSON 格式

> **数据权威**：MySQL `kb_article` 表为知识条目的唯一 source of truth（见 [db-conventions.md §7.5](db-conventions.md)）；
> `knowledge/articles/<id>.json` 为 DB 记录的磁盘投影，可从 DB 重建。
> 写入顺序：先写 DB（事务内），成功后同步写 JSON 文件；两者不一致时以 DB 为准。

所有知识条目以 JSON 格式投影至 `knowledge/articles/<id>.json`，字段定义如下：

> **必填性对齐**：字段表中"必填"列以 [db-conventions.md §7.5](db-conventions.md) DDL 约束为准。DDL 带 `DEFAULT` 的字段在 JSON 投影中始终写出实际值（不省略）；DDL 允许 `NULL` 的字段在未发生时写 `null`。

```json
{
  "article_id": "kb-20260727-0001",
  "title": "OpenAI 发布 GPT-5 多模态推理模型",
  "source_url": "https://github.com/trending/...",
  "source_platform": "github_trending | hackernews",
  "source_score": 942,
  "summary": "一句话摘要：GPT-5 支持原生多模态输入，推理能力显著提升……",
  "content_path": "knowledge/raw/kb-20260727-0001.md",
  "tags": ["llm", "multimodal", "openai"],
  "category": "model_release | paper | tool | tutorial | news",
  "status": "pending | reviewed | published | archived",
  "language": "zh | en",
  "collected_at": "2026-07-27T08:00:00Z",
  "analyzed_at": "2026-07-27T08:05:00Z",
  "published_at": null,
  "published_channels": null
}
```

### 字段说明

| 字段                | 类型     | 必填 | 说明                                         |
| ------------------- | -------- | ---- | -------------------------------------------- |
| `article_id`        | string   | 是   | 业务标识，格式 `kb-YYYYMMDD-NNNN`（NNNN=DB 自增主键，全局递增，见 [db-conventions.md §7.5](db-conventions.md) 与 `src/utils/id_gen.py`） |
| `title`             | string   | 是   | 条目标题                                     |
| `source_url`        | string   | 是   | 原始链接                                     |
| `source_platform`   | string   | 是   | 来源平台枚举（`github_trending` / `hackernews`，新增来源须同步更新本节、[db-conventions.md §7.5](db-conventions.md) 注释与 `src/models/enums.py`） |
| `source_score`      | integer  | 否   | 来源热度（star 数 / points），默认 0        |
| `summary`           | string   | 是   | AI 生成的中文摘要                            |
| `content_path`      | string   | 是   | 原始内容文件的相对路径（相对项目根目录）    |
| `tags`              | string[] | 是   | 自动生成的标签（小写）                       |
| `category`          | string   | 是   | 内容分类枚举（`model_release` / `paper` / `tool` / `tutorial` / `news`，判定标准见 [content-spec.md §6.5](content-spec.md)） |
| `status`            | string   | 是   | 生命周期状态（JSON 写字符串枚举，DB 存 TINYINT，映射见 [content-spec.md §6.6](content-spec.md) 与 `src/models/enums.py`） |
| `language`          | string   | 否   | 原文语言，默认 `zh`                          |
| `collected_at`      | string   | 是   | 采集时间（ISO 8601 UTC）                     |
| `analyzed_at`       | string   | 否   | 分析完成时间，未分析为 `null`                |
| `published_at`      | string   | 否   | 发布时间，未发布为 `null`                    |
| `published_channels`| string[] | 否   | 已推送渠道列表，未分发为 `null`              |
