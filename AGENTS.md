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
| LLM 调用 | LiteLLM                          | 统一多供应商 LLM 调用，支持路由/fallback/成本追踪 |
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
| 数据模型与 Schema    | `src/models/`                   | Pydantic 模型、数据结构定义、枚举定义      |
| LLM 供应商管理与调用 | `src/llm/`                      | Provider/Model CRUD、LiteLLM 封装、健康检查、路由 |
| LangGraph 工作流     | `src/graph/`                    | 状态机定义、节点编排                       |
| 通用工具函数         | `src/utils/`                    | 跨模块复用的工具函数（如 GitHub API 封装）  |
| 通用基础设施         | `src/common/`                   | 统一响应模型、错误码、异常处理器、链路追踪（traceId） |
| 测试代码             | `tests/`                        | 镜像 `src/` 目录结构，`tests/collectors/` 对应 `src/collectors/` |
| 原始采集内容         | `knowledge/raw/`                | Markdown 格式，文件名 = 条目 `article_id` |
| 结构化知识条目       | `knowledge/articles/`           | JSON 格式，文件名 = 条目 `article_id`     |
| 前端项目             | `kb-web/`                       | Vue 3 + TS + Vite + Element Plus 前端工程  |
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
14. **异常日志规范**：`except` 块内**必须**使用 `logger.exception("描述")` 或 `logger.error("描述", exc_info=True)` 附加完整 traceback，**禁止**仅记录 `str(exc)` 丢失调用栈（兜底隔离点除外）。日志须包含操作上下文（模块名、操作类型、关键标识），但**禁止输出** API Key / Token / 密码等敏感字段。外部异常消息（httpx / requests 等）入库前须经脱敏处理（如 `src/llm/client.py` 的 `_sanitize_error()`），`health.py` / `service.py` 等模块的 `last_error` 字段写入时**必须调用同一脱敏函数**，禁止直接截断入库。

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
| `LLM_PROVIDER_ENCRYPTION_KEY` | LLM 供应商 API Key 加密主密钥 | 是   | 任意 passphrase，SHA-256 派生 Fernet 密钥 |
| `LLM_DEFAULT_PROVIDER_CODE` | 启动时默认供应商代码          | 否   | `deepseek`               |
| `LLM_API_KEY`               | （废弃）单供应商 API Key，保留向后兼容 | 否   |                          |
| `LLM_API_BASE`              | （废弃）单供应商端点，保留向后兼容     | 否   | 国产模型默认端点         |
| `LLM_MODEL`                 | （废弃）单供应商模型名，保留向后兼容   | 否   | `doubao-pro`             |
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
│   ├── llm/                   # LLM 供应商管理（Provider/Model CRUD、LiteLLM 封装、健康检查、路由）
│   ├── graph/                 # LangGraph 工作流定义
│   ├── config/                # 配置加载（环境变量解析、DB 连接串拼装、数据库会话管理）
│   ├── common/                # 通用基础设施（统一响应、错误码、异常处理器、链路追踪）
│   └── utils/                 # 通用工具函数（GitHub API 封装、ID 生成等）
├── tests/                     # pytest 测试（镜像 src/ 目录结构）
├── scripts/                   # 一次性运维脚本（非业务代码）
├── kb-web/                    # 前端工程（Vue 3 + TS + Vite + Element Plus）
│   ├── src/
│   │   ├── api/               # API 请求封装（axios 实例 + 各模块接口函数）
│   │   ├── assets/            # 静态资源（图片、字体、样式）
│   │   ├── components/        # 通用组件（跨页面复用）
│   │   ├── composables/       # 组合式函数（Composition API hooks）
│   │   ├── layouts/           # 布局组件（侧边栏 / 导航 / 页脚）
│   │   ├── router/            # Vue Router 路由定义
│   │   ├── stores/            # Pinia 状态管理
│   │   ├── types/             # TypeScript 类型定义
│   │   ├── views/             # 页面级组件（与路由一一对应）
│   │   ├── App.vue            # 根组件
│   │   └── main.ts            # 应用入口
│   ├── public/                # 静态文件（不经 Vite 处理，直接拷贝）
│   ├── index.html             # HTML 入口模板
│   ├── vite.config.ts         # Vite 配置（代理、别名、构建优化）
│   └── tsconfig.json          # TypeScript 配置
└── deploy/                    # 部署配置
    ├── docker/                # Docker 部署（Dockerfile / docker-compose / init.sql）
    ├── sql/                   # DDL 脚本（按编号顺序执行，docker-compose 挂载到 initdb.d）
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
| **必选字段** | 每张业务表须包含：`id`（主键）、`created_at`（创建时间）、`updated_at`（更新时间，须设置 `ON UPDATE CURRENT_TIMESTAMP`）、`is_deleted`（软删除标记，`TINYINT(1) UNSIGNED NOT NULL DEFAULT 0`）、`deleted_at`（软删除时间，`DATETIME(3) NULL`）。**纯追加日志表**（如 `kb_llm_health_log`）例外，仅需 `id` + `created_at`，不需要 `updated_at` / `is_deleted` / `deleted_at`。 |
| **软删除** | 业务表禁止物理删除（`DELETE FROM`），须使用软删除（`UPDATE SET is_deleted=1, deleted_at=NOW(3)`）。所有查询须过滤 `WHERE is_deleted = 0`。唯一约束须使用 guard 生成列排除软删除行（软删除行 guard = NULL，MySQL 唯一索引允许多个 NULL）。 |
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

## 9. LLM 供应商管理规范

> 本节定义多 LLM 供应商的配置管理、路由策略、健康检查和模型发现规范。
> 代码实现见 `src/llm/`，DDL 见 `deploy/sql/01-04_*.sql`，枚举定义见 `src/models/enums.py`。

### 9.1 供应商与模型

**三张表**：

| 表 | 职责 | DDL 文件 |
| -- | ---- | -------- |
| `kb_llm_provider` | 供应商配置 + 健康当前状态（内联） | `deploy/sql/01_kb_llm_provider.sql` |
| `kb_llm_model` | 模型清单（每供应商多个，`is_default` 标记默认） | `deploy/sql/02_kb_llm_model.sql` |
| `kb_llm_health_log` | 健康检查日志（append-only，定期清理） | `deploy/sql/03_kb_llm_health_log.sql` |

**枚举定义**（`src/models/enums.py`）：

| 枚举 | DB 值 | JSON 字符串 | 说明 |
| ---- | ----- | ----------- | ---- |
| `LlmProviderType` | 0/1 | `cloud`/`local` | 供应商类型 |
| `LlmAuthType` | 0/1/2/3 | `bearer`/`oauth`/`header`/`none` | 鉴权方式 |
| `LlmHealthStatus` | 0/1/2/3 | `healthy`/`degraded`/`unhealthy`/`unknown` | 健康状态 |
| `LlmModelSource` | 0/1/2 | `preset`/`discovered`/`manual` | 模型记录来源 |

**鉴权方式统一存储**：

| auth_type | `api_key_encrypted` | `auth_config` JSON | 典型供应商 |
| --------- | ------------------- | ------------------ | ---------- |
| `bearer` (0) | API Key（加密） | `null` 或 `{}` | OpenAI / DeepSeek / Ark / Qwen |
| `oauth` (1) | API Key（加密） | `{"secret_key": "enc:...", "token_url": "..."}` | 百度千帆（二期） |
| `header` (2) | API Key（加密） | `{"header_name": "x-goog-api-key"}` | Google Gemini（二期） |
| `none` (3) | `NULL` | `null` | Ollama / llama.cpp |

`api_key_encrypted` 须用 `LLM_PROVIDER_ENCRYPTION_KEY` 环境变量经 SHA-256 派生 Fernet 密钥加密存储，禁止明文入库。

**一期支持 6 家供应商**（种子数据见 `deploy/sql/04_seed_llm_providers.sql`）：

| provider_code | 类型 | auth_type | litellm_provider | base_url |
| ------------- | ---- | --------- | ---------------- | -------- |
| `ark` | cloud | bearer | `volcengine` | `https://ark.cn-beijing.volces.com/api/v3` |
| `deepseek` | cloud | bearer | `deepseek` | `https://api.deepseek.com/v1` |
| `qwen` | cloud | bearer | `openai` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `openai` | cloud | bearer | `openai` | `https://api.openai.com/v1` |
| `ollama` | local | none | `ollama` | `http://localhost:11434/v1` |
| `llamacpp` | local | none | `openai` | `http://localhost:8080/v1` |

### 9.2 路由规则与健康状态机

**路由查询**：`WHERE is_enabled=1 AND health_status != unhealthy ORDER BY priority, id`。unhealthy 供应商被自动跳过，degraded 仍可尝试。路由实现见 `src/llm/router.py`。

**健康状态机**（类熔断器，实现见 `src/llm/health.py`）：

```
UNKNOWN ──首次检查──▶ HEALTHY
HEALTHY ──失败 1 次──▶ DEGRADED
DEGRADED ──失败达 threshold──▶ UNHEALTHY
UNHEALTHY ──健康检查成功──▶ HEALTHY
任意状态 ──成功──▶ HEALTHY（consecutive_failures 归零）
```

- 所有状态转换使用 CAS（`UPDATE ... WHERE id=? AND health_status=?`）保证并发安全。
- `failure_threshold` 按供应商可配（local 类型建议设高阈值）。
- unhealthy 供应商仅通过定时健康检查恢复，不接受业务调用自愈。
- 健康检查日志写入 `kb_llm_health_log`（append-only），不随业务调用频率膨胀。

### 9.3 模型发现

通过 `GET {base_url}/models` 获取模型 ID 列表，交叉 LiteLLM 注册表（`litellm.model_cost` / `litellm.get_model_info`）补全 `context_window` / `supports_function_calling` / `supports_vision` / 定价等元数据。未命中的模型字段留默认值，`source=discovered`，前端提示用户补全。发现结果不直接写 DB，由前端用户勾选后调用 `create_model` 批量创建。实现见 `src/llm/service.py` 的 `discover_models()`。

### 9.4 安全要求

- `api_key_encrypted` 须用 Fernet 加密存储，密钥从 `LLM_PROVIDER_ENCRYPTION_KEY` 环境变量读取（红线 #5 延伸）。
- 日志中禁止输出 `api_key` / `auth_config` 内容（红线 #10 延伸）。
- `last_error` 字段须脱敏后写入，移除可能包含的 API Key 片段。
- 供应商删除为软删除（`is_enabled=0`），保留历史日志引用完整性。

---

## 10. 链路追踪（traceId）规范

> 本节定义 traceId 的生成、传递、注入和输出规范。
> 实现见 `src/common/trace.py`（待实现），日志格式见 `src/main.py` / `src/config/logging.py`（待实现）。

### 10.1 设计目标

调用链路「采集 -> 分析 -> 整理 -> 分发」中的所有日志须可通过统一 `trace_id` 关联到同一次工作流执行。在多线程、多请求并发场景下，通过 `trace_id` 快速定位一次完整链路的全部日志。

### 10.2 traceId 格式

| 属性 | 规则 |
| ---- | ---- |
| 格式 | UUIDv4 前 8 位十六进制（如 `a1b2c3d4`），短小可读 |
| 唯一性 | 每次工作流执行 / 每个 HTTP 请求生成一个 |
| 大小写 | 全小写 |
| 存储 | `str` 类型，不加密 |

### 10.3 生成与传递规则

**生成点（须在链路入口生成）：**

| 入口 | 生成方式 | 实现位置 |
| ---- | -------- | -------- |
| CLI 执行 | `main()` 启动时生成，注入 `WorkflowState` | `src/main.py` |
| LangGraph 工作流 | `build_workflow()` 执行前生成，写入 `WorkflowState["trace_id"]` | `src/graph/workflow.py` |
| FastAPI 请求 | 从请求头 `X-Request-Id` 提取；未携带时自动生成；响应头回传 `X-Request-Id` | FastAPI 中间件（待实现） |

**传递规则：**

1. **工作流链路**：`trace_id` 存入 `WorkflowState["trace_id"]`，各节点函数从 `state` 中读取并传入日志。
2. **跨函数传递**：工作流节点调用的业务函数（采集器 / 分析器 / 整理器 / 分发器）须接收 `trace_id: str` 参数并写入日志。
3. **LLM 调用链**：`chat_completion()` / `record_success()` / `record_failure()` 等函数须接收 `trace_id` 参数，将 LLM 调用日志关联到触发它的工作流。
4. **禁止跨链路复用**：每次工作流执行 / 每个请求生成新的 `trace_id`，禁止复用上一次执行的 ID。

### 10.4 日志注入规则

采用 `contextvars.ContextVar` + `logging.Filter` 实现自动注入，业务代码**无需**手动在每条日志中拼接 `trace_id`：

1. **ContextVar 声明**（`src/common/trace.py`）：
   ```python
   import contextvars
   trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")
   ```

2. **设置 traceId**：链路入口设置 `trace_id_var.set(generated_id)`，后续同线程 / 同协程内的所有日志自动携带。

3. **Logging Filter**：注册全局 `logging.Filter`，从 `trace_id_var` 读取当前值并注入 `LogRecord`：
   ```python
   class TraceIdFilter(logging.Filter):
       def filter(self, record: logging.LogRecord) -> bool:
           record.trace_id = trace_id_var.get()
           return True
   ```

4. **日志格式**：格式字符串须包含 `%(trace_id)s`：
   ```
   %(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s
   ```

5. **多线程传递**：`ThreadPoolExecutor` 提交任务时，须在子线程入口调用 `trace_id_var.set(parent_trace_id)`，确保子线程日志关联到同一链路。推荐使用 `contextvars.copy_context()` 传递。

### 10.5 WorkflowState 字段扩展

`WorkflowState`（`src/graph/state.py`）须增加 `trace_id` 字段：

```python
class WorkflowState(TypedDict, total=False):
    trace_id: str              # 链路追踪 ID（工作流入口生成）
    stage: str
    candidates: list[dict[str, Any]]
    analysis_results: list[dict[str, Any]]
    articles: list[dict[str, Any]]
    distribution_results: list[dict[str, Any]]
    errors: list[dict[str, Any]]
```

### 10.6 节点日志规范

工作流各节点函数（`src/graph/nodes.py`）的日志**须**携带 `trace_id`：

```python
def collect_node(state: WorkflowState) -> WorkflowState:
    trace_id = state.get("trace_id", "-")
    trace_id_var.set(trace_id)
    logger.info("采集节点启动，候选条目数: %d", len(state.get("candidates", [])))
    # trace_id 已通过 Filter 自动注入日志，无需手动拼接
    ...
```

### 10.7 实现清单（待完成）

| 序号 | 文件 | 改动内容 |
| ---- | ---- | -------- |
| T-01 | `src/common/trace.py` | 新建：`trace_id_var` ContextVar + `TraceIdFilter` + `generate_trace_id()` 工具函数 |
| T-02 | `src/main.py` | 日志格式增加 `[%(trace_id)s]`；`main()` 生成 traceId 并 `set` |
| T-03 | `src/graph/state.py` | `WorkflowState` 增加 `trace_id: str` 字段 |
| T-04 | `src/graph/workflow.py` | `build_workflow()` 执行前生成 traceId 写入初始 state |
| T-05 | `src/graph/nodes.py` | 各节点函数入口 `trace_id_var.set(state["trace_id"])` |
| T-06 | `src/llm/client.py` | `chat_completion()` 增加 `trace_id` 参数，日志携带 |
| T-07 | `src/llm/health.py` | `record_success/record_failure/check_provider_health` 增加 `trace_id` 参数；`last_error` 写入前调用 `_sanitize_error()` |
| T-08 | `src/llm/service.py` | except 块补充 `exc_info=True`；错误日志调用 `_sanitize_error()` |
| T-09 | `src/utils/github_api.py` | 3 处 except 块补充 `exc_info=True` |
| T-10 | `src/mcp_knowledge_server.py` | 2 处 except 块补充 `exc_info=True` |

---

## 11. 前端页面规范

> 本节定义前端页面划分、路由结构、各页面功能要求与组件约定。
> 前端工程位于 `kb-web/`，技术栈见 §1（Vue 3 Composition API + TypeScript + Element Plus）。
> 页面级组件统一放 `kb-web/src/views/`，与路由一一对应；路由定义见 `kb-web/src/router/index.ts`。

### 11.1 页面总览

| # | 页面 | 路由 | 菜单层级 | 状态 | 说明 |
|---|------|------|----------|------|------|
| 1 | 仪表盘 | `/dashboard` | 一级 | 新增 | 系统统计概览、趋势图表、健康摘要 |
| 2 | 知识条目列表 | `/articles` | 一级 | 已有 | 条目筛选/搜索/分页，需增强标签与来源筛选 |
| 3 | 条目详情 | `/articles/:id` | 二级 | 已有 | 完整条目信息 + 原始 Markdown 渲染 + 状态流转操作 |
| 4 | LLM 供应商列表 | `/llm/providers` | 一级 | 已有 | 供应商 CRUD + 健康状态展示，需扩展为完整增删改查 |
| 5 | LLM 供应商详情 | `/llm/providers/:id` | 二级 | 新增 | 供应商编辑 + 模型管理 + 模型发现 + 健康检查日志 |
| 6 | 工作流管理 | `/workflow` | 一级 | 新增 | 任务触发 + 执行历史 + 链路追踪（traceId） |
| 7 | 分发渠道 | `/distributors` | 一级 | 新增 | 渠道配置状态 + 分发历史 + 手动重发 |

> **菜单结构**：侧边栏一级菜单为「仪表盘」「知识条目」「LLM 管理」「工作流」「分发渠道」，条目详情与供应商详情为二级页面（不在侧边栏显示，通过列表点击跳入）。

### 11.2 仪表盘（DashboardView）

| 要素 | 说明 |
| ---- | ---- |
| 路由 | `/dashboard`，应用默认重定向目标 |
| 组件 | `kb-web/src/views/DashboardView.vue` |
| API | `GET /articles/stats`（条目统计）、`GET /llm/providers`（供应商健康摘要） |
| 功能区块 | |

1. **统计卡片**：知识条目总数、各状态计数（pending / reviewed / published / archived）、今日新增数。
2. **来源平台分布**：饼图，按 `source_platform`（github_trending / hackernews）聚合。
3. **热门标签 Top 10**：标签云或条形图，按出现频次排序。
4. **LLM 供应商健康概览**：healthy / degraded / unhealthy / unknown 计数卡片，点击跳转供应商列表。
5. **采集趋势**：近 7 天 / 30 天每日新增条目折线图（按 `collected_at` 聚合）。

### 11.3 知识条目列表（ArticleListView）

| 要素 | 说明 |
| ---- | ---- |
| 路由 | `/articles` |
| 组件 | `kb-web/src/views/ArticleListView.vue`（已存在，需增强） |
| API | `GET /articles`（分页列表） |
| 已有功能 | 状态筛选、分类筛选、关键词搜索、分页、行点击跳转详情 |
| 需增强 | |

1. **标签筛选**：新增标签下拉多选筛选器，支持按标签过滤。
2. **来源平台筛选**：新增来源平台下拉（github_trending / hackernews / 全部）。
3. **批量操作**：列表增加多选 checkbox，支持批量审核（pending→reviewed）、批量归档。
4. **列展示优化**：标签列以 `el-tag` 展示前 3 个标签，超出显示 `+N`。

### 11.4 条目详情（ArticleDetailView）

| 要素 | 说明 |
| ---- | ---- |
| 路由 | `/articles/:id`（`:id` = `article_id`） |
| 组件 | `kb-web/src/views/ArticleDetailView.vue`（已存在，需增强） |
| API | `GET /articles/:id`（条目详情）、`GET /articles/:id/raw`（原始 Markdown 内容）、`PATCH /articles/:id/status`（状态流转）、`POST /articles/:id/distribute`（触发分发） |
| 功能区块 | |

1. **基础信息区**：标题、来源链接（外链跳转）、来源平台、热度、分类、标签、语言、状态标签、各时间戳（采集 / 分析 / 发布）。
2. **AI 摘要区**：`summary` 字段渲染，突出展示。
3. **原始内容区（采集内容阅读）**：调用 `GET /articles/:id/raw` 获取 `content_path` 对应的 Markdown 原文，使用 Markdown 渲染组件展示。原始内容只读，禁止编辑（红线 #1）。
4. **状态操作区**：
   - `pending` → 「审核」按钮（转为 `reviewed`）。
   - `reviewed` → 「分发」按钮（选择渠道触发推送）+ 「归档」按钮。
   - `published` → 显示已推送渠道列表（`published_channels`）+ 「归档」按钮。
   - `archived` → 仅展示，无操作按钮。
   - 状态转换须遵循 §6.6 转换矩阵，前端按当前 `status` 控制按钮可见性。
5. **分发渠道状态**：若 `published_channels` 非空，展示各渠道推送状态（图标 + 时间）。

### 11.5 LLM 供应商列表（LlmProviderListView）

| 要素 | 说明 |
| ---- | ---- |
| 路由 | `/llm/providers` |
| 组件 | `kb-web/src/views/LlmProviderView.vue`（已存在，需重构为完整 CRUD） |
| API | `GET /llm/providers`（列表）、`POST /llm/providers`（创建）、`PATCH /llm/providers/:id`（更新）、`POST /llm/providers/:id/health-check`（手动健康检查） |
| 已有功能 | 供应商列表只读展示 |
| 需增强 | |

1. **新增供应商**：对话框表单，字段见 `ProviderCreate`（§9.1），API Key 输入框为 password 类型，提交后明文传输至后端加密存储。
2. **编辑供应商**：行内「编辑」按钮，打开预填表单；API Key 字段留空表示不修改。
3. **启用/禁用切换**：`el-switch` 直接切换 `is_enabled`，禁用即软删除（§9.4）。
4. **手动健康检查**：行内「检查」按钮，调用 `POST /llm/providers/:id/health-check`，刷新健康状态。
5. **跳转详情**：行点击或「详情」按钮跳转 `/llm/providers/:id`。
6. **健康状态展示**：`el-tag` 颜色映射 healthy=success / degraded=warning / unhealthy=danger / unknown=info。

### 11.6 LLM 供应商详情（LlmProviderDetailView）

| 要素 | 说明 |
| ---- | ---- |
| 路由 | `/llm/providers/:id` |
| 组件 | `kb-web/src/views/LlmProviderDetailView.vue`（新增） |
| API | `GET /llm/providers/:id`、`PATCH /llm/providers/:id`、`GET /llm/providers/:id/models`、`POST /llm/providers/:id/models`、`PATCH /llm/models/:id`、`POST /llm/providers/:id/discover`（模型发现）、`GET /llm/providers/:id/health-logs`（健康日志） |
| 布局 | `el-tabs` 多 Tab 页，Tab 切换不离开路由 |
| 功能 Tab | |

1. **Tab: 供应商信息** — 供应商完整字段展示与编辑（同 §11.5 编辑表单），含 `last_check_at` / `last_success_at` / `last_failure_at` / `consecutive_failures` / `last_error` 只读展示。
2. **Tab: 模型管理** — 该供应商下所有模型列表（`GET /llm/providers/:id/models`），支持：
   - 新增模型（对话框表单，字段见 `ModelCreate`）。
   - 编辑模型（`ModelUpdate`）。
   - 启用/禁用模型（`el-switch`）。
   - 设为默认模型（`is_default`，同供应商仅一个默认）。
   - 列展示：模型代码、LiteLLM 标识、上下文窗口、函数调用/多模态支持、输入/输出价格、来源（preset/discovered/manual）、启用状态、默认标记。
3. **Tab: 模型发现** — 点击「发现模型」按钮调用 `POST /llm/providers/:id/discover`，返回 `DiscoveredModel[]` 候选列表：
   - 表格展示候选模型，含 `already_exists` 标记（已存在行灰显）。
   - 用户勾选未存在的模型，点击「批量导入」调用 `POST /llm/providers/:id/models` 批量创建。
   - 未命中 LiteLLM 注册表的字段（如定价、上下文窗口）提示用户补全。
4. **Tab: 健康检查日志** — 分页表格展示 `kb_llm_health_log` 记录：
   - 列：检查时间、模型（如有）、延迟（ms）、结果（成功/失败）、错误信息（脱敏后）。
   - 支持按时间范围筛选。

### 11.7 工作流管理（WorkflowView）

| 要素 | 说明 |
| ---- | ---- |
| 路由 | `/workflow` |
| 组件 | `kb-web/src/views/WorkflowView.vue`（新增） |
| API | `POST /workflow/run`（触发工作流）、`GET /workflow/runs`（执行历史列表）、`GET /workflow/runs/:trace_id`（链路详情） |
| 功能区块 | |

1. **任务触发面板**：
   - 阶段选择：`collect`（采集）/ `analyze`（分析）/ `curate`（整理）/ `distribute`（分发）/ `all`（全流程）。
   - 采集参数：数据源选择（GitHub Trending / Hacker News / 全部）、关键词输入（逗号分隔）。
   - 「执行」按钮触发 `POST /workflow/run`，返回 `trace_id`。
2. **执行历史列表**：
   - 列：traceId、阶段、开始时间、结束时间、耗时、状态（running/success/failed）、候选数、分析数、条目数。
   - traceId 可点击复制。
   - 支持按状态、时间范围筛选。
3. **链路追踪详情**（点击行展开或弹窗）：
   - 按 `trace_id` 查询关联日志，展示各节点（collect→analyze→curate→distribute）的执行时间线。
   - 错误信息展示（`errors` 列表）。

### 11.8 分发渠道（DistributionView）

| 要素 | 说明 |
| ---- | ---- |
| 路由 | `/distributors` |
| 组件 | `kb-web/src/views/DistributionView.vue`（新增） |
| API | `GET /distributors/channels`（渠道配置状态）、`GET /distributions`（分发历史分页）、`POST /articles/:id/distribute`（手动重发） |
| 功能区块 | |

1. **渠道配置卡片**：
   - Telegram：展示 `TELEGRAM_BOT_TOKEN` 配置状态（已配置/未配置），不展示 Token 明文。
   - 飞书：展示 `FEISHU_WEBHOOK_URL` 配置状态（已配置/未配置），不展示 URL 明文。
   - 渠道状态卡片以图标 + 状态标签展示，敏感信息脱敏（红线 #10）。
2. **分发历史列表**：
   - 列：条目标题、渠道（telegram/feishu）、推送时间、结果（success/skipped/failed）、错误信息。
   - 支持按渠道、结果筛选。
   - 分页。
3. **手动重发**：失败行提供「重发」按钮，调用 `POST /articles/:id/distribute` 重新推送（须遵循分发幂等，§6.6 第 5 条）。

### 11.9 前端通用约定

1. **API 请求封装**：所有请求经 `kb-web/src/utils/request.ts`（axios 实例），统一处理 `X-Request-Id` 请求头注入与响应拦截（§10.3）。
2. **类型定义**：与后端 Pydantic schema 对应的 TypeScript interface 放 `kb-web/src/types/` 或各 `api/*.ts` 内联定义。
3. **状态管理**：跨页面共享状态用 Pinia store（`kb-web/src/stores/`），页面内局部状态用 `ref`/`reactive`。
4. **状态流转前端校验**：所有状态操作按钮须按 §6.6 转换矩阵控制可见性，前端做第一道校验，后端做权威校验。
5. **敏感信息脱敏**：前端展示 API Key / Token / Webhook URL 时仅显示掩码（如 `sk-****xxxx`），禁止明文展示（红线 #10 延伸）。
6. **Markdown 渲染**：原始内容渲染须使用 Markdown 解析库（如 `markdown-it`），渲染前不做任何内容修改（红线 #1 延伸）。
7. **路由懒加载**：所有页面组件使用 `() => import()` 动态导入，首屏仅加载 Dashboard。

---

*本文件由项目维护者维护，Agent 在每次会话开始时须读取并遵守上述约定。*
