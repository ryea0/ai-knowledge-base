# AGENTS.md

本项目是一个 AI 知识库助手，用于自动采集 AI/LLM/Agent 领域的技术动态。
系统从 GitHub Trending 和 Hacker News 抓取原始内容，经 AI 分析后结构化存储为 JSON 知识条目，
并支持通过 Telegram、飞书等多渠道分发。
所有 Agent 由 OpenCode 驱动，协同完成「采集 → 分析 → 整理 → 分发」的全流程。

---

## 1. 技术栈

| 类别       | 选型                              | 说明                                  |
| ---------- | --------------------------------- | ------------------------------------- |
| 运行时     | Python 3.12  + FastAPI            | 主开发语言，所有 Agent 逻辑基于此实现 |
| Agent 编排 | OpenCode + 国产大模型（如 Doubao）| 驱动各 Agent 角色协作                 |
| 工作流引擎 | LangGraph                         | 编排采集/分析/整理的多步状态机流程    |
| AI模型    | OpenAI 兼容 API 调用字节模型         | llm调用    |
| 爬取工具   | OpenClaw                          | 负责网页抓取与内容清洗                |
| 数据格式   | JSON                              | 知识条目统一以 JSON 存储              |
| 分发渠道   | Telegram Bot / 飞书 Webhook       | 多渠道推送结构化知识                  |
| 数据库     | MySQL 8.0+                        | 结构化数据持久化，配合 SQLAlchemy ORM |
| 向量数据库  | ChromaDB                        | 存储向量数据 |
| 前端      | Vue 3 Composition API + TypeScript + Element Plus| 展示结果数据、文章以及人物状态等|

---

## 2. 编码规范

### 2.1 基础规范

- **遵循 PEP 8**：所有 Python 代码须通过 `ruff` / `flake8` 检查。
- **文档字符串**：统一使用 [Google 风格 docstring](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)，每个公开函数/类必须包含。
- **类型注解**：所有函数签名必须包含参数与返回值类型注解，配合 `mypy` 静态检查。
- **依赖管理**：使用 `uv` 管理依赖，锁定文件为 `uv.lock`；禁止手动编辑 `uv.lock`。依赖声明统一写入 `pyproject.toml` 的 `[project.dependencies]` 段。
- **测试**：新功能须附带 `pytest` 测试用例，覆盖率不低于 80%。
- **交付前检查**：每次提交前须依次运行以下命令，全部通过方可交付：
  ```bash
  uv run ruff check src/ tests/
  uv run mypy src/
  uv run pytest tests/ --cov=src --cov-fail-under=80
  ```
  工具链配置见 `pyproject.toml`（`[tool.ruff]` / `[tool.mypy]` / `[tool.pytest.ini_options]` / `[tool.coverage]`）。

### 2.2 代码路径规范

所有生成的代码**必须严格按照以下路径放置**，禁止随意创建目录或文件：

| 代码类型             | 存放路径                        | 说明                                       |
| ------------------- | ------------------------------- | ------------------------------------------ |
| 数据源采集器         | `src/collectors/`               | GitHub Trending / Hacker News 等采集逻辑   |
| AI 分析与摘要        | `src/analyzers/`                | LLM 摘要、标签提取、分类逻辑               |
| 知识整理与去重       | `src/organizers/`               | 去重算法、格式化与存盘逻辑                |
| 多渠道分发           | `src/distributors/`             | Telegram / 飞书推送逻辑                    |
| 数据模型与 Schema    | `src/models/`                   | Pydantic 模型、数据结构定义                |
| LangGraph 工作流     | `src/graph/`                    | 状态机定义、节点编排                       |
| 通用工具函数         | `src/utils/`                    | 跨模块复用的工具函数（如 GitHub API 封装）  |
| 测试代码             | `tests/`                        | 镜像 `src/` 目录结构，`tests/collectors/` 对应 `src/collectors/` |
| 原始采集内容         | `knowledge/raw/`                | Markdown 格式，文件名 = 条目 `article_id` |
| 结构化知识条目       | `knowledge/articles/`           | JSON 格式，文件名 = 条目 `article_id`     |
| 项目配置             | `pyproject.toml`                | 依赖与工具链配置                           |

**路径规则：**

1. 新建 Python 模块时，须在对应目录下创建 `__init__.py`。
2. 测试文件命名与被测模块一一对应：`src/utils/github_api.py` → `tests/utils/test_github_api.py`。
3. 禁止在项目根目录直接放置业务 `.py` 文件；CLI 入口脚本放 `src/` 下（如 `src/main.py`），一次性运维脚本放 `scripts/`。
4. 禁止在 `src/` 之外的目录创建业务代码；`scripts/` 仅用于一次性运维脚本，非业务代码。
5. 配置文件统一放项目根目录或 `src/config/`，禁止散落在各子模块中。

### 2.3 Python 编码细则（基于 Google Style Guide 精简）

> 以下 20 条规则提炼自 [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)，AI 生成代码时须逐条遵守。

#### 命名（Naming）

1. **命名风格**：模块/文件用 `snake_case`；包名用全小写无下划线；类用 `PascalCase`；函数/变量用 `snake_case`；常量用 `UPPER_SNAKE_CASE`。内部成员以 `_` 前缀标识。
2. **避免歧义命名**：禁止单字母 `l`、`O`、`I`（与 `0`/`1` 混淆）；循环计数器可用 `i`/`j`/`k`。命名须具描述性，避免无意义缩写（通用术语 `url`/`http` 除外）。
3. **异常命名**：自定义异常类名以 `Error` 结尾，须继承已有异常基类，避免 `FooModule.FooError` 式重复前缀。
4. **可见性约定**：受保护成员用 `_name`；**禁止**用 `__name` 双下划线触发名称改写（除非需严格防止子类覆盖）。模块级私有常量用 `_MAX_VALUE` 格式。
5. **避免可变默认参数**：函数默认值禁止使用 `list`/`dict`/`set` 等可变对象，须用 `None` 哨兵并在函数体内初始化。

#### 异常处理（Exceptions）

6. **优先内置异常**：参数校验失败用 `ValueError`，类型错误用 `TypeError`，运行时状态异常用 `RuntimeError`。仅在内置异常无法表达语义时自定义。
7. **禁止 assert 替代校验**：`assert` 仅用于不可达路径的内部不变式断言，**不可**用于参数校验或业务逻辑（测试代码除外）。`assert` 在 `-O` 模式下会被移除。
8. **禁止裸 except**：禁止 `except:` 或 `except Exception:` 捕获全部异常，除非在该块内重新 `raise` 或位于线程最外层隔离点。须捕获具体异常类型。
9. **try 块最小化**：仅包裹可能抛出异常的具体语句，禁止大段代码包裹在 `try` 中。资源清理统一用 `finally` 或上下文管理器（`with` 语句）。
10. **异常链保留**：重新抛出异常时必须用 `raise NewError(...) from exc` 保留原始 traceback，禁止裸 `raise NewError(...)` 丢失上下文。

#### 日志（Logging）

11. **日志器规范**：每个模块顶部声明 `logger = logging.getLogger(__name__)`，禁止 `print()`，禁止 `logging.basicConfig()` 在库代码中调用（仅入口脚本可配置）。
12. **延迟格式化**：日志消息用 `%s` 占位符 + 参数传递（如 `logger.error("失败: %s", err)`），**禁止** f-string / `.format()` / `+` 拼接（无法利用级别过滤跳过格式化开销）。
13. **日志级别约定**：`DEBUG` = 详细的变量值/调用栈；`INFO` = 关键流程节点（采集开始/分析完成/发布成功）；`WARNING` = 可恢复的降级行为（重试、跳过）；`ERROR` = 操作失败但系统可继续；`CRITICAL` = 系统不可用。生产环境默认 `INFO`。
14. **异常日志规范**：`logger.exception()` 自动附加 traceback，用于 `except` 块内；`logger.error(..., exc_info=True)` 同效。日志须包含操作上下文（模块名、操作类型、关键标识），但**禁止输出** API Key / Token / 密码等敏感字段。

#### 并发（Concurrency）

15. **禁止依赖内置类型原子性**：`dict`/`list` 的操作不保证线程安全（`__hash__`/`__eq__` 可被重写），多线程共享可变数据必须显式加锁或使用 `queue.Queue`。
16. **线程池优先**：并发任务优先使用 `concurrent.futures.ThreadPoolExecutor`（I/O 密集）或 `ProcessPoolExecutor`（CPU 密集），禁止裸 `threading.Thread` 创建不受管理的线程。
17. **锁粒度最小化**：临界区内只做内存操作，**禁止**在持锁状态下执行 I/O（网络请求、文件读写、`time.sleep`），避免死锁。优先使用 `threading.Condition` 进行线程间协调。
18. **异步不混用**：`asyncio` 事件循环内禁止直接调用阻塞 I/O；须用 `asyncio.to_thread()` 或 `run_in_executor()` 桥接。禁止在同一个事件循环中混用 `threading.Lock` 与 `asyncio.Lock`。
19. **全局可变状态禁令**：模块级可变变量（全局 list/dict/连接池）须避免。确需共享时，用 `threading.local()` 隔离或显式锁保护，并在声明处注释说明设计原因。
20. **资源释放保证**：线程/进程池须用 `with` 语句管理生命周期；`Queue` / `Lock` / `Semaphore` 等同步原语在异常路径下须通过 `finally` 释放，禁止遗漏导致资源泄漏。

---

### 2.4 环境变量约定

所有密钥与外部服务配置须通过环境变量读取（`.env` 文件已 gitignore，不入库），禁止硬编码。命名规则：`<服务>_<用途>`，全大写 `SNAKE_CASE`。新增变量须同步更新下表与 `.env.example`。

| 变量名                      | 用途                          | 必填 | 示例 / 默认              |
| --------------------------- | ----------------------------- | ---- | ------------------------ |
| `MYSQL_HOST`                | MySQL 主机                    | 是   | `127.0.0.1`              |
| `MYSQL_PORT`                | MySQL 端口                    | 否   | `3306`                   |
| `MYSQL_USER`                | MySQL 用户名                  | 是   | `kb_app`                 |
| `MYSQL_PASSWORD`            | MySQL 密码                    | 是   |                          |
| `MYSQL_DATABASE`            | MySQL 库名                    | 是   | `ai_knowledge_base`      |
| `LLM_API_KEY`               | LLM 服务 API Key（摘要/标签） | 是   |                          |
| `LLM_API_BASE`              | LLM 服务端点                  | 否   | 国产模型默认端点         |
| `LLM_MODEL`                 | LLM 模型名                    | 否   | `doubao-pro`             |
| `TELEGRAM_BOT_TOKEN`        | Telegram Bot Token            | 否\* | 未配置则跳过该渠道       |
| `FEISHU_WEBHOOK_URL`        | 飞书 Webhook 地址             | 否\* | 未配置则跳过该渠道       |
| `GITHUB_TOKEN`              | GitHub API Token（提升限速）  | 否   | 未配置走匿名（限速更低） |

\* `TELEGRAM_BOT_TOKEN` 与 `FEISHU_WEBHOOK_URL` 至少配置一个，否则分发无可用渠道。

DB 连接串须由上述字段拼装（`mysql+pymysql://{user}:{password}@{host}:{port}/{database}`），禁止用单一 `DATABASE_URL` 混合拼接。

---

## 3. 项目结构

```
ai-knowledge-base/
├── AGENTS.md                  # 本文件，Agent 协作约定
├── pyproject.toml             # 依赖与工具链配置（ruff/mypy/pytest/coverage）
├── .env                       # 环境变量（已 gitignore，不入库）
├── .env.example               # 环境变量模板（入库，见 §2.4）
├── .opencode/
│   ├── agents/                # OpenCode Agent 定义（采集/分析/整理）
│   │   ├── collector.md
│   │   ├── analyzer.md
│   │   └── organizer.md
│   └── skills/                # OpenCode 技能定义（目录式，每个技能含 SKILL.md）
│       ├── fetch-github-trending/SKILL.md
│       ├── fetch-hackernews/SKILL.md
│       └── distribute-message/SKILL.md
├── .agents/                   # 跨工具共享的 Agent 资源（如 grill-me skill）
├── knowledge/
│   ├── raw/                   # 采集的原始内容（Markdown 原文）
│   └── articles/              # 经分析后的结构化 JSON 知识条目
├── src/
│   ├── collectors/            # 数据源采集器
│   ├── analyzers/             # AI 分析与摘要生成
│   ├── organizers/            # 知识整理与去重
│   ├── distributors/          # 多渠道分发
│   ├── models/                # 数据模型与 Pydantic schema
│   ├── graph/                 # LangGraph 工作流定义
│   ├── config/                # 配置加载（环境变量解析、DB 连接串拼装）
│   └── utils/                 # 通用工具函数（GitHub API 封装、ID 生成等）
├── tests/                     # pytest 测试（镜像 src/ 目录结构）
├── scripts/                   # 一次性运维脚本（非业务代码）
└── deploy/                    # 部署配置
    ├── docker/                # Docker 部署（Dockerfile / docker-compose / init.sql）
    └── k8s/                   # Kubernetes 清单（CronJob / StatefulSet / ConfigMap / Secret）
```

---

## 4. 知识条目 JSON 格式

> **数据权威**：MySQL `kb_article` 表为知识条目的唯一 source of truth（见 §7.5）；
> `knowledge/articles/<id>.json` 为 DB 记录的磁盘投影，可从 DB 重建。
> 写入顺序：先写 DB（事务内），成功后同步写 JSON 文件；两者不一致时以 DB 为准。

所有知识条目以 JSON 格式投影至 `knowledge/articles/<id>.json`，字段定义如下：

> **必填性对齐**：字段表中"必填"列以 §7.5 DDL 约束为准。DDL 带 `DEFAULT` 的字段在 JSON 投影中始终写出实际值（不省略）；DDL 允许 `NULL` 的字段在未发生时写 `null`。

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
| `article_id`        | string   | 是   | 业务标识，格式 `kb-YYYYMMDD-NNNN`（NNNN=DB 自增主键，全局递增，见 §7.5 与 `src/utils/id_gen.py`） |
| `title`             | string   | 是   | 条目标题                                     |
| `source_url`        | string   | 是   | 原始链接                                     |
| `source_platform`   | string   | 是   | 来源平台枚举（`github_trending` / `hackernews`，新增来源须同步更新 §4、§7.5 注释与 `src/models/enums.py`） |
| `source_score`      | integer  | 否   | 来源热度（star 数 / points），默认 0        |
| `summary`           | string   | 是   | AI 生成的中文摘要                            |
| `content_path`      | string   | 是   | 原始内容文件的相对路径（相对项目根目录）    |
| `tags`              | string[] | 是   | 自动生成的标签（小写）                       |
| `category`          | string   | 是   | 内容分类枚举（`model_release` / `paper` / `tool` / `tutorial` / `news`，判定标准见 §6.5） |
| `status`            | string   | 是   | 生命周期状态（JSON 写字符串枚举，DB 存 TINYINT，映射见 §6.6 与 `src/models/enums.py`） |
| `language`          | string   | 否   | 原文语言，默认 `zh`                          |
| `collected_at`      | string   | 是   | 采集时间（ISO 8601 UTC）                     |
| `analyzed_at`       | string   | 否   | 分析完成时间，未分析为 `null`                |
| `published_at`      | string   | 否   | 发布时间，未发布为 `null`                    |
| `published_channels`| string[] | 否   | 已推送渠道列表，未分发为 `null`              |

---

## 5. Agent 角色概览

| Agent       | 职责                                         | 输入                         | 输出                          | 关键技能                        |
| ----------- | -------------------------------------------- | ---------------------------- | ----------------------------- | ------------------------------- |
| **采集 Agent** (collector)  | 从 GitHub Trending / Hacker News 搜索采集技术动态，提取标题/链接/热度/摘要，初步筛选并按热度排序 | 数据源配置、关键词列表      | JSON 数组（title/url/source/popularity/summary），不落盘 | `fetch_github_trending` `fetch_hackernews` |
| **分析 Agent** (analyzer)   | 读取 `knowledge/raw/` 原始内容，生成摘要、亮点、评分(1-10)、建议标签 | 原始内容文件                 | JSON 对象（title/summary/highlights/score/tags/category/language），不落盘 | LLM 摘要、标签提取、内容评分 |
| **整理 Agent** (organizer)  | 去重检查、格式化为标准 JSON、分类存入 `knowledge/articles/` | 分析 JSON 产出 + 采集元信息  | `knowledge/articles/{date}-{source}-{slug}.json` (status: pending) | 去重算法、JSON 格式化、文件命名 |

### 采集 Agent 权限模型

采集 Agent 采用**只读权限**设计，仅允许 Read / Grep / Glob / WebFetch，禁止 Write / Edit / Bash。采集 Agent 只负责搜索和信息提取，输出 JSON 候选列表，不直接写文件；原始内容落盘和结构化条目写入由后续流程在质量审核后完成。详见 `.opencode/agents/collector.md`。

### 分析 Agent 权限模型

分析 Agent 采用**只读权限**设计，仅允许 Read / Grep / Glob / WebFetch，禁止 Write / Edit / Bash。分析 Agent 只负责内容分析和信息提取，输出 JSON 分析结果，不直接写文件；结构化条目写入由整理 Agent 统一完成。详见 `.opencode/agents/analyzer.md`。

### 整理 Agent 权限模型

整理 Agent 允许 Read / Grep / Glob / Write / Edit，禁止 WebFetch / Bash。整理 Agent 是唯一允许写入 `knowledge/articles/` 的 Agent，负责去重检查、格式化和存盘；不从外部数据源获取信息（禁止 WebFetch），内容来源仅限采集和分析产出。详见 `.opencode/agents/organizer.md`。

### 工作流

```
[数据源] -> 采集 Agent -> JSON 候选列表（不落盘）
                           ↓
              [原始内容写入 knowledge/raw/]
                           ↓
        分析 Agent -> 分析 JSON（摘要/亮点/评分/标签），不落盘
                           ↓
        整理 Agent -> 去重/格式化/存盘 -> knowledge/articles/ (status: pending)
                           ↓
                   分发 -> Telegram/飞书 (status: published)
```

---

## 6. 内容规范

### 6.1 采集范围

- 仅采集与 **AI / LLM / Agent / 模型训练 / 推理优化 / 多模态 / RAG / Prompt 工程** 等直接相关的技术内容。
- 关键词包括但不限于：`llm`、`gpt`、`transformer`、`fine-tuning`、`rag`、`agent`、`multimodal`、`embedding`、`vllm`、`langchain`、`llama`、`diffusion` 等。
- 同一主题优先保留信息量最大、时间最新的一条；重复或高度相似内容由整理 Agent 去重。
- **采集侧幂等**：采集前须先查 DB `kb_article.source_url` 是否已存在（或查 `knowledge/raw/` 是否已有同 URL 条目），已存在则跳过，禁止对同一 URL 重复采集并生成新条目。
- **限流与重试**：对外部数据源（GitHub API、HN API、外部网页）的请求须遵守以下约束：
  - **速率限制**：须尊重目标服务的 `X-RateLimit-*` / `Retry-After` 响应头；未提供时，GitHub API 匿名请求间隔 ≥ 2s、带 Token ≥ 0.5s，HN API 间隔 ≥ 1s。
  - **重试策略**：网络错误 / 429 / 5xx 须指数退避重试（初始 1s、倍增、上限 60s），最多 3 次；4xx（非 429）不重试。
  - **并发控制**：采集并发请求线程池 `max_workers ≤ 5`，禁止无限制并发。
  - **超时**：单次 HTTP 请求超时 30s，总采集超时 10 分钟，超时则记 `WARNING` 并跳过当批剩余项。

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

### 6.6 状态定义与转换矩阵

`status` 枚举的唯一定义点为 `src/models/enums.py` 中的 `ArticleStatus(IntEnum)`，DB 存整数值，JSON 写字符串名。任何新增/变更状态须先改枚举文件，再同步本节。

| 枚举名     | DB 值 | JSON 字符串   | 含义                         |
| ---------- | ----- | ------------- | ---------------------------- |
| `PENDING`  | 0     | `"pending"`   | 已采集待分析 / 已分析待审核 |
| `REVIEWED` | 1     | `"reviewed"`  | 已审核，待分发               |
| `PUBLISHED`| 2     | `"published"` | 已推送至至少一个渠道         |
| `ARCHIVED` | 3     | `"archived"`  | 归档，不再分发               |

**状态转换矩阵**（行=当前态，列=目标态，✓=允许，✗=禁止，空=无需转换）：

| from \ to     | pending | reviewed | published | archived |
| ------------- | ------- | -------- | --------- | -------- |
| **pending**   | ✓\*     | ✓        | ✗         | ✓        |
| **reviewed**  | ✗       | ✓\*      | ✓         | ✓        |
| **published** | ✗       | ✗        | ✓\*       | ✓        |
| **archived**  | ✗       | ✗        | ✗         | ✓\*      |

\* 表示保持当前态（无操作）。规则要点：

1. `published` 之后禁止修改 `title`/`summary`/`tags`/`category`/`content_path`（见红线第 2 条），仅允许转 `archived`。
2. `pending` 不能直接跳 `published`（见红线第 7 条），须经 `reviewed`。
3. 分析或分发失败时**不新增失败态**，留在原态并在日志记 `ERROR`，由重试或人工介入。
4. 所有状态转换须在 DB 事务内完成（`UPDATE ... SET status=... WHERE id=... AND status=<期望旧值>`，利用条件更新保证 CAS 语义）。
5. **分发幂等**：推送渠道前须先查 `published_channels` 是否已含目标渠道，含则跳过；推送成功后须在同一事务内将渠道名追加至 `published_channels` 并视情况更新 `status`/`published_at`。状态须在 `reviewed` 时方可分发（`published_channels` 为 `NULL` 或不含目标渠道），禁止从 `pending` 直接推送。

### 6.7 原始内容规范

- `knowledge/raw/` 中的原始文件以 Markdown 格式存储，文件名与条目 `article_id` 一致（如 `kb-20260727-0001.md`）。
- 原始文件须保留：来源标题、来源 URL、正文内容、采集时间元信息。
- **原始内容只可追加，不可修改或删除**（参见红线第 1 条）。

### 6.8 语言与去重

- 知识库面向中文读者，`summary` 统一为中文；`title` 中文为主，保留专有名词英文。
- `language` 字段记录原文语言（`zh` / `en`）。
- 相同主题不同来源的内容，整理 Agent 须按信息完整度和来源热度保留一条，其余标记为 `archived`。

---

## 7. 数据库设计规范（MySQL）

> 以下规范综合阿里巴巴 Java 开发手册（MySQL 篇）及互联网公司常见 MySQL 最佳实践，AI 生成 DDL / 查询语句时须逐条遵守。

### 7.1 建表规范

| 规则 | 说明 |
| ---- | ---- |
| **存储引擎** | 统一使用 `InnoDB`，禁止使用 `MyISAM`。 |
| **字符集** | 统一使用 `utf8mb4`，排序规则使用 `utf8mb4_0900_ai_ci`（MySQL 8.0+）或 `utf8mb4_unicode_ci`。禁止使用 `utf8`（实为 3 字节，无法存储 Emoji）。 |
| **表名** | 全小写 `snake_case`，禁止使用驼峰、拼音、数据库保留字；须加业务前缀（如 `kb_article`）。 |
| **字段名** | 全小写 `snake_case`，禁止使用数据库保留字（`desc`/`order`/`type` 等，须加业务前缀如 `article_type`）。 |
| **主键** | 每张表必须有主键，推荐使用 `BIGINT UNSIGNED AUTO_INCREMENT` 或分布式 ID。**禁止**使用 `UUID` 作为聚簇索引主键（页分裂严重）。 |
| **必选字段** | 每张业务表须包含：`id`（主键）、`created_at`（创建时间）、`updated_at`（更新时间），且 `updated_at` 须设置 `ON UPDATE CURRENT_TIMESTAMP`。 |
| **禁用外键** | 禁止使用 `FOREIGN KEY`，关联关系在应用层维护。 |
| **禁用存储过程/触发器/视图** | 业务逻辑不沉入数据库层，便于迁移和调试。 |
| **禁止使用数据库枚举** | 不使用 `ENUM` 类型，状态字段使用 `TINYINT UNSIGNED` 并在代码层映射；或在 MySQL 8.0+ 使用 `CHECK` 约束。 |
| **金额/精度** | 金额字段禁止使用 `FLOAT`/`DOUBLE`，须使用 `DECIMAL(18,2)` 或整数分。 |

### 7.2 字段类型规范

| 场景 | 推荐类型 | 禁止 |
| ---- | -------- | ---- |
| 布尔值 | `TINYINT(1) UNSIGNED`（0/1） | `BOOLEAN` / `ENUM('Y','N')` |
| 短文本（< 255 字符） | `VARCHAR(n)`，n 须为合理值 | `TEXT` |
| 长文本 / Markdown 原文 | `MEDIUMTEXT` 或 `LONGTEXT` | `VARCHAR(10000)` |
| JSON 结构化数据 | `JSON`（MySQL 8.0+） | `TEXT` 手动序列化 |
| 时间戳 | `DATETIME(3)`（毫秒精度），应用层统一写 UTC | `VARCHAR` 存时间字符串；`TIMESTAMP`（2038 问题 + 时区隐式转换） |
| IP 地址 | `VARBINARY(16)` 或 `VARCHAR(45)` | `INT` |
| 布尔状态多值 | 位运算 `BIGINT` + 应用层解释 | 多列 `TINYINT` |

### 7.3 索引规范

1. **索引命名**：普通索引前缀 `idx_`；唯一索引前缀 `uk_`；全文索引前缀 `ft_`。如 `idx_source_url`、`uk_article_id`。
2. **单表索引数**：单表索引数量不超过 **5 个**，单索引字段数不超过 **5 列**。
3. **覆盖索引优先**：高频查询须设计覆盖索引（包含 `SELECT` 所需全部字段），避免回表。
4. **最左前缀原则**：联合索引须按区分度从高到低排列，查询条件须满足最左前缀。
5. **禁止在索引列上使用函数**：`WHERE DATE(created_at) = '2026-07-27'` 会导致索引失效，须改写为 `WHERE created_at >= '2026-07-27' AND created_at < '2026-07-28'`。
6. **禁止 `SELECT *`**：一律显式指定字段列表，避免覆盖索引失效和列变更导致的隐式错误。
7. **LIKE 优化**：禁止左模糊 `LIKE '%keyword'`（索引失效），须使用右模糊 `LIKE 'keyword%'` 或全文索引。
8. **前缀索引**：对长字符串列（如 `VARCHAR(500)`）建索引时，使用前缀索引 `idx_col(prefix_len)`，减少索引体积。

### 7.4 SQL 编写规范

1. **大写关键字**：SQL 关键字（`SELECT`/`FROM`/`WHERE`/`JOIN`/`GROUP BY` 等）一律大写，表名/字段名小写。
2. **表别名**：多表 JOIN 必须使用有语义的别名（如 `article a`、`raw_content r`）；单表简单查询允许使用任意别名。
3. **JOIN 规范**：禁止使用逗号隐式 JOIN（`FROM a, b WHERE a.id = b.id`），须使用显式 `INNER JOIN` / `LEFT JOIN`。
4. **分页规范**：深度分页（`OFFSET > 10000`）须使用延迟关联或游标分页（`WHERE id > last_id LIMIT n`），禁止直接 `LIMIT 100000, 20`。
5. **批量写入**：单条 `INSERT` 语句须使用多值形式 `INSERT INTO ... VALUES (...), (...), (...)`，单批次不超过 **500 行**。
6. **事务范围**：事务须尽可能短小，禁止在事务中包含远程调用（HTTP 请求 / RPC）。事务中只做数据库操作。
7. **避免大事务**：单事务影响行数超过 **1000 行**时须拆分批次提交，避免长事务锁争用和 binlog 膨胀。
8. **ORM 使用**：使用 SQLAlchemy 时禁止拼接原生 SQL 字符串（SQL 注入风险），须使用参数绑定或 ORM 查询构造器。

### 7.5 表设计示例

以知识条目表为例：

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
    created_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at      DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_article_id (article_id),
    KEY idx_source_url (source_url(255)),
    KEY idx_status_created (status, created_at),
    KEY idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识条目表';
```

---

## 8. 红线（绝对禁止的操作）

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
11. **禁止执行 `rm -rf` 等危险命令** -- 不得对 `knowledge/`、`src/`、`tests/`、`.opencode/`、用户家目录或项目外路径执行删除；清理 `build/`、`dist/`、`.venv/`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/` 等构建/缓存产物除外。
12. **禁止修改 `AGENTS.md` 本身** —— 本文件由项目维护者维护，Agent 不得自行编辑，除非用户明确要求。
13. **禁止在非约定路径创建代码文件** —— 所有代码须按 §2.2 路径规范放置，禁止随意创建目录或在根目录放置业务 `.py` 文件。
14. **禁止在数据库中使用外键、存储过程、触发器、视图** —— 关联关系在应用层维护，业务逻辑不沉入数据库层（参见 §7.1）。
15. **禁止 `SELECT *`** —— 须显式指定字段列表，避免索引失效和列变更隐患（参见 §7.3）。

---

*本文件由项目维护者维护，Agent 在每次会话开始时须读取并遵守上述约定。*
