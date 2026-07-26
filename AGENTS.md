# AGENTS.md

本项目是一个 AI 知识库助手，用于自动采集 AI/LLM/Agent 领域的技术动态。
系统从 GitHub Trending 和 Hacker News 抓取原始内容，经 AI 分析后结构化存储为 JSON 知识条目，
并支持通过 Telegram、飞书等多渠道分发。
所有 Agent 由 OpenCode 驱动，协同完成「采集 → 分析 → 整理 → 分发」的全流程。

---

## 1. 技术栈

| 类别       | 选型                              | 说明                                  |
| ---------- | --------------------------------- | ------------------------------------- |
| 运行时     | Python 3.12                       | 主开发语言，所有 Agent 逻辑基于此实现 |
| Agent 编排 | OpenCode + 国产大模型（如 Doubao）| 驱动各 Agent 角色协作                 |
| 工作流引擎 | LangGraph                         | 编排采集/分析/整理的多步状态机流程    |
| 爬取工具   | OpenClaw                          | 负责网页抓取与内容清洗                |
| 数据格式   | JSON                              | 知识条目统一以 JSON 存储              |
| 分发渠道   | Telegram Bot / 飞书 Webhook       | 多渠道推送结构化知识                  |

---

## 2. 编码规范

- **遵循 PEP 8**：所有 Python 代码须通过 `ruff` / `flake8` 检查。
- **命名**：变量与函数使用 `snake_case`；类使用 `PascalCase`；常量使用 `UPPER_SNAKE_CASE`。
- **文档字符串**：统一使用 [Google 风格 docstring](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)，每个公开函数/类必须包含。
- **日志**：**禁止裸 `print()`**，一律使用 `logging` 模块（`logger = logging.getLogger(__name__)`）。
- **类型注解**：所有函数签名必须包含参数与返回值类型注解，配合 `mypy` 静态检查。
- **依赖管理**：使用 `uv` 或 `pip-tools` 锁定依赖，禁止直接修改 `requirements.txt` 之外的锁定文件。
- **测试**：新功能须附带 `pytest` 测试用例，覆盖率不低于 80%。

---

## 3. 项目结构

```
ai-knowledge-base/
├── AGENTS.md                  # 本文件，Agent 协作约定
├── .opencode/
│   ├── agents/                # OpenCode Agent 定义（采集/分析/整理）
│   │   ├── collector.md
│   │   ├── analyzer.md
│   │   └── curator.md
│   └── skills/                # OpenCode 技能定义
│       ├── fetch_github_trending.md
│       ├── fetch_hackernews.md
│       └── distribute_message.md
├── knowledge/
│   ├── raw/                   # 采集的原始内容（HTML/Markdown 原文）
│   └── articles/              # 经分析后的结构化 JSON 知识条目
├── src/
│   ├── collectors/            # 数据源采集器
│   ├── analyzers/             # AI 分析与摘要生成
│   ├── curators/              # 知识整理与去重
│   ├── distributors/          # 多渠道分发
│   ├── models/                # 数据模型与 Pydantic schema
│   └── graph/                 # LangGraph 工作流定义
├── tests/                     # pytest 测试
└── pyproject.toml             # 项目与依赖配置
```

---

## 4. 知识条目 JSON 格式

所有知识条目存放在 `knowledge/articles/<id>.json`，字段定义如下：

```json
{
  "id": "kb-20260727-0001",
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
  "published_channels": []
}
```

### 字段说明

| 字段                | 类型     | 必填 | 说明                                         |
| ------------------- | -------- | ---- | -------------------------------------------- |
| `id`                | string   | 是   | 唯一标识，格式 `kb-YYYYMMDD-NNNN`            |
| `title`             | string   | 是   | 条目标题                                     |
| `source_url`        | string   | 是   | 原始链接                                     |
| `source_platform`   | string   | 是   | 来源平台枚举                                 |
| `source_score`      | integer  | 否   | 来源热度（star 数 / points）                 |
| `summary`           | string   | 是   | AI 生成的中文摘要                            |
| `content_path`      | string   | 是   | 原始内容文件的相对路径                       |
| `tags`              | string[] | 是   | 自动生成的标签（小写）                       |
| `category`          | string   | 是   | 内容分类枚举                                 |
| `status`            | string   | 是   | 生命周期状态                                 |
| `language`          | string   | 否   | 原文语言                                     |
| `collected_at`      | string   | 是   | 采集时间（ISO 8601 UTC）                     |
| `analyzed_at`       | string   | 否   | 分析完成时间                                 |
| `published_at`      | string   | 否   | 发布时间，未发布为 `null`                    |
| `published_channels`| string[] | 否   | 已推送渠道列表                               |

---

## 5. Agent 角色概览

| Agent       | 职责                                         | 输入                         | 输出                          | 关键技能                        |
| ----------- | -------------------------------------------- | ---------------------------- | ----------------------------- | ------------------------------- |
| **采集 Agent** (collector)  | 从 GitHub Trending / Hacker News 抓取原始内容 | 数据源配置、关键词列表      | `knowledge/raw/*.md` 原始文件 | `fetch_github_trending` `fetch_hackernews` |
| **分析 Agent** (analyzer)   | AI 阅读原文，生成摘要、标签、分类            | 原始内容文件                 | `knowledge/articles/*.json`  | LLM 摘要、标签提取              |
| **整理 Agent** (curator)    | 去重、状态流转、多渠道分发                    | 结构化 JSON 条目             | 推送消息 + 更新状态           | `distribute_message`、去重算法  |

### 工作流

```
[数据源] → 采集 Agent → knowledge/raw/
                           ↓
        分析 Agent → knowledge/articles/ (status: pending)
                           ↓
        整理 Agent → 去重/审核 → (status: reviewed)
                           ↓
                   分发 → Telegram/飞书 (status: published)
```

---

## 6. 内容规范

### 6.1 采集范围

- 仅采集与 **AI / LLM / Agent / 模型训练 / 推理优化 / 多模态 / RAG / Prompt 工程** 等直接相关的技术内容。
- 关键词包括但不限于：`llm`、`gpt`、`transformer`、`fine-tuning`、`rag`、`agent`、`multimodal`、`embedding`、`vllm`、`langchain`、`llama`、`diffusion` 等。
- 同一主题优先保留信息量最大、时间最新的一条；重复或高度相似内容由整理 Agent 去重。

### 6.2 标题规范

- 标题须反映内容核心信息，控制在 60 字以内。
- 使用中文，保留专有名词/模型名称的英文原名（如 GPT-5、LLaMA 3）。
- 禁止使用标题党式表述（如「震惊！」「必看！」），保持客观技术描述。

### 6.3 摘要规范

- 摘要须为 AI 生成的高质量中文概括，篇幅控制在 2-4 句话、150 字以内。
- 必须包含：**是什么**（核心内容）+ **关键特性/数据**（如有）+ **影响/应用场景**（如有）。
- 摘要须基于原文事实，**不得编造、夸大或加入主观评价**。
- 若原文为英文，摘要须翻译为中文并保留关键技术术语。

### 6.4 标签规范

- 标签全部小写，使用英文或通用缩写（如 `llm`、`rag`、`fine-tuning`）。
- 每条知识条目 **3-8 个标签**，至少包含一个技术领域标签和一个细分方向标签。
- 禁止使用无意义标签（如 `ai`、`tech`、`other` 等过于宽泛的标签）。
- 标签应可复用，相同技术主题的条目须使用相同标签以支持聚合检索。

### 6.5 分类规范

`category` 字段取值及判定标准：

| 取值             | 判定标准                                                 |
| ---------------- | -------------------------------------------------------- |
| `model_release`  | 新模型发布（如 GPT-5、LLaMA 4）                          |
| `paper`          | 学术论文 / 技术报告（ArXiv、研究报告）                   |
| `tool`           | 工具 / 框架 / SDK 发布或重大更新                         |
| `tutorial`       | 教程 / 操作指南 / 最佳实践指南                           |
| `news`           | 行业新闻 / 融资 / 人事变动 / 政策等非技术性动态          |

无法明确归类时，默认使用 `news`，并在整理阶段复核。

### 6.6 原始内容规范

- `knowledge/raw/` 中的原始文件以 Markdown 格式存储，文件名与条目 `id` 一致（如 `kb-20260727-0001.md`）。
- 原始文件须保留：来源标题、来源 URL、正文内容、采集时间元信息。
- **原始内容只可追加，不可修改或删除**（参见红线第 1 条）。

### 6.7 语言与去重

- 知识库面向中文读者，`summary` 统一为中文；`title` 中文为主，保留专有名词英文。
- `language` 字段记录原文语言（`zh` / `en`）。
- 相同主题不同来源的内容，整理 Agent 须按信息完整度和来源热度保留一条，其余标记为 `archived`。

---

## 7. 红线（绝对禁止的操作）

> 以下行为会破坏数据完整性或触发安全风险，**任何 Agent 不得执行**：

1. **禁止删除或覆盖 `knowledge/raw/` 中的原始文件** —— 原始数据只可追加，不可修改。
2. **禁止在 `status` 为 `published` 后修改条目内容** —— 已发布条目只能标记为 `archived`。
3. **禁止伪造或省略 `source_url`** —— 每条知识必须可溯源，URL 须指向真实页面。
4. **禁止裸 `print()` 输出** —— 一律使用 `logging`，避免污染 Agent 标准输出。
5. **禁止硬编码 API Key / Token** —— 所有密钥必须从环境变量或 `.env` 读取，严禁写入代码或提交到 Git。
6. **禁止跳过类型注解** —— 所有公开函数必须有完整类型注解，`mypy` 不得报错。
7. **禁止直接向生产渠道推送未经分析（`status: pending`）的条目** —— 分发前必须经整理 Agent 审核为 `reviewed`。
8. **禁止采集非 AI/LLM/Agent 领域的内容** —— 保持知识库主题聚焦。
9. **禁止编造不存在的项目、论文或数据** —— 摘要与标题须严格基于原文事实，不得虚构任何信息。
10. **禁止在日志中输出 API Key / Token 或其他敏感信息** —— 日志须经脱敏处理，仅记录必要的流程信息。
11. **禁止执行 `rm -rf` 等危险命令** —— 不得删除目录、批量文件或执行任何破坏性系统操作。
12. **禁止修改 `AGENTS.md` 本身** —— 本文件由项目维护者维护，Agent 不得自行编辑，除非用户明确要求。

---

*本文件由项目维护者维护，Agent 在每次会话开始时须读取并遵守上述约定。*
