---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# 采集 GitHub 热门开源项目

## 使用场景

- 采集 Agent 需要发现近期 GitHub 上热门的 AI/LLM/Agent 相关开源项目时。
- 需要获取仓库的名称、描述、star 数、语言、topics 等结构化信息时。
- 需要为知识库流水线提供候选条目输入时。

## 执行步骤

1. **搜索热门仓库**：通过 GitHub API（`GET /search/repositories`，按 `stars` 排序、限定近期时间范围 `created:>YYYY-MM-DD` 或 `pushed:>YYYY-MM-DD`）搜索热门仓库，获取仓库名称、描述、star 数、语言、topics 等元信息。若设置了 `GITHUB_TOKEN` 环境变量，请求时携带认证以提升速率限制。

2. **提取信息**：从 API 响应中逐条提取 `name`（仓库名）、`url`（仓库链接）、`summary`（描述）、`stars`（star 数）、`language`（主语言）、`topics`（话题标签数组）。

3. **过滤**：按以下规则筛选--
   - **纳入**：名称、描述或 topics 命中 AI/LLM/Agent 关键词（`llm`、`gpt`、`transformer`、`fine-tuning`、`rag`、`agent`、`multimodal`、`embedding`、`vllm`、`langchain`、`llama`、`diffusion` 等）。
   - **排除**：仓库名或描述以 `awesome-` 开头的聚合列表（如 `awesome-llm`、`awesome-chatgpt`），因这类仓库仅为链接汇总，非原创技术项目。

4. **去重**：按 `url` 去重，同一仓库仅保留一条；若 `knowledge/raw/` 中已存在同 URL 的采集记录则跳过（幂等）。

5. **撰写中文摘要**：对每条保留的仓库，按公式 **项目名 + 做什么 + 为什么值得关注** 撰写一句话中文摘要。保留专有名词/模型名称英文原名（如 GPT-5、LLaMA 3），禁止编造、夸大或加入主观评价。

6. **排序取 Top 15**：按 `stars` 降序排列，取前 15 条作为本批输出。若不足 15 条则全部保留，并在日志中说明原因。

7. **输出 JSON**：将结果写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`（日期取 UTC 当日）。文件结构见下方"输出格式"。

## 注意事项

- **速率限制**：GitHub API 匿名请求间隔 ≥ 2s、带 Token ≥ 0.5s；遇 `429` 或 `5xx` 须指数退避重试（初始 1s、倍增、上限 60s、最多 3 次）。
- **超时**：单次 HTTP 请求超时 30s。
- **并发**：若并发抓取，线程池 `max_workers ≤ 5`。
- **原始文件只追加**：`knowledge/raw/` 中的文件只可追加，不可修改或删除。
- **`source_url` 必须真实**：每条记录须指向真实可访问的仓库页面，禁止伪造。
- **禁止裸 `print()`**：一律使用 `logging`。
- **密钥安全**：`GITHUB_TOKEN` 从环境变量读取，禁止硬编码，禁止记入日志。
- **主题聚焦**：仅采集 AI/LLM/Agent 领域内容，非相关内容一律跳过。
- **类型注解**：所有公开函数须有完整类型注解。

完整规范见项目根目录 `AGENTS.md` §6.1（采集范围与限流）、§8（红线）。

## 输出格式

写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`，结构如下：

```json
{
  "source": "github_trending",
  "skill": "github-trending",
  "collected_at": "2026-07-27T08:00:00Z",
  "items": [
    {
      "name": "vllm-project/vllm",
      "url": "https://github.com/vllm-project/vllm",
      "summary": "vLLM 是高吞吐量 LLM 推理与服务引擎，通过 PagedAttention 优化 KV Cache 内存管理，显著提升推理吞吐量，值得关注的推理基础设施。",
      "stars": 28000,
      "language": "Python",
      "topics": ["llm", "inference", "serving", "optimization"]
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source` | string | 固定 `github_trending` |
| `skill` | string | 固定 `github-trending` |
| `collected_at` | string | 采集时间（ISO 8601 UTC） |
| `items` | array | 候选条目数组，按 `stars` 降序，最多 15 条 |
| `items[].name` | string | 仓库全名（`owner/repo`） |
| `items[].url` | string | 仓库链接 |
| `items[].summary` | string | 中文摘要（项目名 + 做什么 + 为什么值得关注） |
| `items[].stars` | integer | star 数 |
| `items[].language` | string | 主语言，无则为空字符串 |
| `items[].topics` | string[] | 话题标签数组 |
