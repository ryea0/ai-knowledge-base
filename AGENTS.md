# AGENTS.md

本项目是一个 AI 知识库助手，用于自动采集 AI/LLM/Agent 领域的技术动态。
系统从 GitHub Trending 和 Hacker News 抓取原始内容，经 AI 分析后结构化存储为 JSON 知识条目，
并支持通过 Telegram、飞书等多渠道分发。
所有 Agent 由 OpenCode 驱动，协同完成「采集 -> 分析 -> 整理 -> 分发」的全流程。

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
2. 测试文件命名与被测模块一一对应：`src/utils/github_api.py` -> `tests/utils/test_github_api.py`。
3. 禁止在项目根目录直接放置业务 `.py` 文件；CLI 入口脚本放 `src/` 下（如 `src/main.py`），一次性运维脚本放 `scripts/`。
4. 禁止在 `src/` 之外的目录创建业务代码；`scripts/` 仅用于一次性运维脚本，非业务代码。
5. 配置文件统一放项目根目录或 `src/config/`，禁止散落在各子模块中。

---

## 3. 项目结构

```
ai-knowledge-base/
├── AGENTS.md                  # 本文件，Agent 协作约定
├── docs/                      # 详细规范文档（按需查阅，见 §12）
├── pyproject.toml             # 依赖与工具链配置（ruff/mypy/pytest/coverage）
├── .env                       # 环境变量（已 gitignore，不入库）
├── .env.example               # 环境变量模板（入库，见 docs/specs/coding-standards.md §2.4）
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

## 8. 红线（绝对禁止的操作）

> 以下行为会破坏数据完整性或触发安全风险，**任何 Agent 不得执行**：

1. **禁止删除或覆盖 `knowledge/raw/` 中的原始文件** -- 原始数据只可追加，不可修改。
2. **禁止在 `status` 为 `published` 后修改条目内容** -- 已发布条目只能标记为 `archived`。
3. **禁止伪造或省略 `source_url`** -- 每条知识必须可溯源，URL 须指向真实页面。
4. **禁止裸 `print()` 输出** -- 一律使用 `logging`，避免污染 Agent 标准输出。
5. **禁止硬编码 API Key / Token** -- 所有密钥必须从环境变量或 `.env` 读取，严禁写入代码或提交到 Git。
6. **禁止跳过类型注解** -- 所有公开函数必须有完整类型注解，`mypy` 不得报错。
7. **禁止直接向生产渠道推送未经分析（`status: pending`）的条目** -- 分发前必须经整理 Agent 审核为 `reviewed`。
8. **禁止采集非 AI/LLM/Agent 领域的内容** -- 保持知识库主题聚焦。
9. **禁止编造不存在的项目、论文或数据** -- 摘要与标题须严格基于原文事实，不得虚构任何信息。
10. **禁止在日志中输出 API Key / Token 或其他敏感信息** -- 日志须经脱敏处理，仅记录必要的流程信息。
11. **禁止执行 `rm -rf` 等危险命令** -- 不得对 `knowledge/`、`src/`、`tests/`、`.opencode/`、用户家目录或项目外路径执行删除；清理 `build/`、`dist/`、`.venv/`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/` 等构建/缓存产物除外。
12. **禁止修改 `AGENTS.md` 本身** -- 本文件由项目维护者维护，Agent 不得自行编辑，除非用户明确要求。
13. **禁止在非约定路径创建代码文件** -- 所有代码须按 §2.2 路径规范放置，禁止随意创建目录或在根目录放置业务 `.py` 文件。
14. **禁止在数据库中使用外键、存储过程、触发器、视图** -- 关联关系在应用层维护，业务逻辑不沉入数据库层（参见 [docs/specs/db-conventions.md §7.1](docs/specs/db-conventions.md)）。
15. **禁止 `SELECT *`** -- 须显式指定字段列表，避免索引失效和列变更隐患（参见 [docs/specs/db-conventions.md §7.3](docs/specs/db-conventions.md)）。

---

## 12. 详细规范索引（按需查阅）

> 以下规范文档从 AGENTS.md 拆分而来，章节编号保持不变。Agent 在涉及对应领域时须读取相关文档。

| 规范领域 | 文件 | 原始章节 | 适用场景 |
| --- | --- | --- | --- |
| Python 编码细则 + 环境变量 | [docs/specs/coding-standards.md](docs/specs/coding-standards.md) | §2.3 / §2.4 | 写 Python 代码时 |
| 知识条目 JSON 格式 | [docs/specs/article-format.md](docs/specs/article-format.md) | §4 | 改 article 相关代码时 |
| 内容规范（采集/标题/摘要/标签/分类/状态/去重） | [docs/specs/content-spec.md](docs/specs/content-spec.md) | §6 | 采集/分析/整理时 |
| 数据库设计规范 | [docs/specs/db-conventions.md](docs/specs/db-conventions.md) | §7 | 写 DDL / ORM / SQL 时 |
| LLM 供应商管理 | [docs/specs/llm-provider.md](docs/specs/llm-provider.md) | §9 | 改 `src/llm/` 时 |
| 链路追踪（traceId） | [docs/specs/trace-spec.md](docs/specs/trace-spec.md) | §10 | 改 trace/日志/工作流时 |
| 前端页面规范 | [docs/specs/frontend-spec.md](docs/specs/frontend-spec.md) | §11 | 写前端时 |

---

*本文件由项目维护者维护，Agent 在每次会话开始时须读取并遵守上述约定。*
