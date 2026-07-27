---
name: fetch-hackernews
description: Use when the collector agent needs to fetch Hacker News top stories and comments for the AI knowledge base. Covers pulling HN rankings, filtering by AI/LLM keywords, and saving raw markdown to knowledge/raw/.
---

# Fetch Hacker News

本技能负责从 Hacker News 抓取热门条目，筛选 AI/LLM/Agent 相关内容，并将原始内容保存为 Markdown。

## 触发场景

- 采集 Agent 需要获取 Hacker News 热门条目时。
- 需要抓取某条目的正文/评论作为原始内容时。

## 工作流程

1. **抓取列表**：通过 HN API（`https://hacker-news.firebaseio.com/v0/topstories.json`）或页面获取热门条目 ID 列表。
2. **获取条目详情**：对每个 ID 调用 `/item/<id>.json`，获取标题、URL、points、作者。
3. **关键词过滤**：仅保留标题/正文命中 AI 关键词的条目（`llm`、`gpt`、`transformer`、`fine-tuning`、`rag`、`agent`、`multimodal`、`embedding`、`vllm`、`langchain`、`llama`、`diffusion` 等）。
4. **抓取正文**：若 `url` 指向外部文章，抓取该页面正文；否则抓取 HN 评论。
5. **生成 ID**：按 `kb-YYYYMMDD-NNNN` 格式生成唯一 ID（同日递增）。
6. **写入原始文件**：保存到 `knowledge/raw/<id>.md`。文件须以 YAML front-matter 开头（结构以本目录 `schema.json` 为唯一真相源），后接正文，格式：

```
---
article_id: <kb-YYYYMMDD-NNNN>
title: <条目标题>
source_url: <原始链接>
source_platform: hackernews
source_score: <points>
collected_at: <ISO 8601 UTC>
---

# <条目标题>

<正文内容>
```

7. **写前校验（闸门）**：写盘前须核对 front-matter 所有字段（`article_id`/`title`/`source_url`/`source_platform`/`source_score`/`collected_at`）齐全且类型合法，正文 `body` 非空。**校验失败则禁止落盘**，须修正后重写，不得降级省略字段。

8. **格式冲突仲裁**：若目标文件已存在，按红线第 1 条**禁止覆盖**，直接跳过该 ID 并记 `WARNING`；如确需同日新增批次，使用新 ID（NNNN 递增）。不得迁就旧格式而省略 front-matter 字段。

## 约束

- 原始文件只可追加，不可修改或删除。
- **格式不可降级**：输出须严格符合本目录 `schema.json`；不得迁就旧格式省略 front-matter 字段。
- `source_url` 必须指向真实页面。
- 禁止裸 `print()`，一律用 `logging`。
- 不得抓取非 AI 领域内容。
- 所有函数须有完整类型注解。

完整规范见项目根目录 `AGENTS.md`。
