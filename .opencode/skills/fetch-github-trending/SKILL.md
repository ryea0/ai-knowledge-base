---
name: fetch-github-trending
description: Use when the collector agent needs to fetch GitHub Trending repositories and README content for the AI knowledge base. Covers scraping trending lists, filtering by AI/LLM keywords, and saving raw markdown to knowledge/raw/.
---

# Fetch GitHub Trending

本技能负责从 GitHub Trending 抓取热门仓库，筛选 AI/LLM/Agent 相关项目，并将原始内容保存为 Markdown。

## 触发场景

- 采集 Agent 需要获取 GitHub Trending 列表时。
- 需要抓取某仓库 README 作为原始内容时。

## 工作流程

1. **抓取列表**：访问 `https://github.com/trending`（可选语言/时间范围参数），解析仓库名称、描述、star 数、语言。
2. **关键词过滤**：仅保留描述或名称命中 AI 关键词的项目（`llm`、`gpt`、`transformer`、`fine-tuning`、`rag`、`agent`、`multimodal`、`embedding`、`vllm`、`langchain`、`llama`、`diffusion` 等）。
3. **抓取 README**：对命中项目，获取其 README 内容作为正文。
4. **生成 ID**：按 `kb-YYYYMMDD-NNNN` 格式生成唯一 ID（同日递增）。
5. **写入原始文件**：保存到 `knowledge/raw/<id>.md`，格式：

```
# <仓库标题>
- Source URL: https://github.com/<owner>/<repo>
- Platform: github_trending
- Score: <star 数>
- Collected At: <ISO 8601 UTC>

<README 正文>
```

## 约束

- 原始文件只可追加，不可修改或删除。
- `source_url` 必须指向真实页面。
- 禁止裸 `print()`，一律用 `logging`。
- 不得抓取非 AI 领域内容。
- 所有函数须有完整类型注解。

完整规范见项目根目录 `AGENTS.md`。
