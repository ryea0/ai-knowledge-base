# SPEC.md - 三 Agent 采集-分析-整理流水线（collector -> analyzer -> organizer）

> **来源**：合并自 GitHub Issue [#1](https://github.com/ryea0/ai-knowledge-base/issues/1)（MD 输出决策 + Pydantic 交接验证）与 Issue [#2](https://github.com/ryea0/ai-knowledge-base/issues/2)（开放问题决策 + Schema 扩展 + 单测试 seam + 运行时韧性）。
> **权威基线**：`AGENTS.md`（项目协作约定）+ `draft/prd.md`（v0.1 草案）+ `docs/sub-agent-test-log.md`（实测发现）。
> **范围**：聚焦「采集 -> 分析 -> 整理」三段，产出 `status: pending` 的知识条目（JSON source of truth + Markdown 渲染视图）；分发（Telegram/飞书、`status: published`）不在本 Spec 范围。

---

## 1. 问题陈述

作为 AI 知识库的维护者，我每天需要从 GitHub Trending 与 Hacker News 中发现 AI/LLM/Agent 领域的新动态，但手动浏览、筛选、写摘要、归档既耗时又不可重复。当前仓库存在以下问题：

- **只有脚手架，无可运行流水线**：`src/main.py` 仅打印日志、`src/models/enums.py` 与两个 utils 是孤岛，没有可运行的采集-分析-整理流水线，也没有任何测试。
- **organizer 交付物与预期不符**：现有 organizer agent 定义为输出 JSON 到 `knowledge/articles/`，但维护者希望它输出 **Markdown**——结构化 JSON 应保留为 DB 支撑的 source of truth，但 organizer 的*交付物*是人类可读的 MD 文件。
- **阶段间契约无强制**：现有 agent 文件描述了数据流，但阶段间的契约仅为文字描述，没有 schema 或测试来强制执行，无法验证每个 agent 是否产出了正确的数据结构再交给下一阶段。
- **`draft/prd.md` 留下四个开放问题**：上游失败下游怎么办、数据怎么传、重跑策略、进度追踪。

我需要一个**可定时触发、可幂等重跑、单条失败不阻塞全流程**的自动化流水线，把外部动态变成结构化、可溯源、已评分的中文知识条目（`status: pending`），同时输出人类可读的 Markdown 渲染视图，供后续审核与分发。

---

## 2. 解决方案

用 **LangGraph** 编排一个串行状态机流水线，包含 **3 个 Agent 节点 + 1 个 graph 层持久化步骤**（共 4 节点）：**collector**、（persist_raw）、**analyzer**、**organizer**。其中 persist_raw 是 graph 层步骤而非 Agent，因 collector 无写权限，由 graph 层代为落盘。

```
[数据源] -> collector（抓取+过滤）  —— 候选列表（内存 JSON）
                                         |
              persist_raw（graph 层，非 Agent）  —— 取号前置 + 写 raw MD
                                         |
              analyzer（LLM 分析）      —— 分析 JSON（内存）
                                         |
              organizer（去重+格式化）  —— UPDATE 补全 + 写 JSON/MD
```

- **collector**：抓取 GitHub Trending Top 50 + Hacker News 热门，按 AI 关键词过滤，按热度降序，输出内存 JSON 候选列表（不写文件——collector 无写权限）。对每条**先查 DB `kb_article.source_url` 幂等**，已存在跳过。collector 输出的 `popularity` 字段在 organizer 阶段映射为 `source_score` 持久化（G13）。
- **persist_raw**（graph 层步骤，**非 Agent**，在 collector 之外因 collector 不能写）：**取号前置**（G1 决策 B）——先在 DB 事务内 `INSERT` 占位行（`status=pending`，`source_url`/`source_platform`/`source_score`/`collected_at` 已填，其余字段留空/默认）-> 取 `LAST_INSERT_ID()` -> `build_article_id` 生成 `article_id` -> `UPDATE` 回填 `article_id` -> commit -> 将原始内容写成 `knowledge/raw/<article_id>.md`（含来源标题、URL、正文与采集时间元信息）。**占位行失败时删除该行并记 ERROR**（见 §4.7）。
- **analyzer**：逐条读 `knowledge/raw/<article_id>.md`，调 LLM 生成中文摘要/亮点/1-10 评分/标签/分类/语言，产出内存 JSON，不落盘。
- **organizer**：逐条做 URL+标题去重，合并采集元信息与分析产出，在 DB 事务内 `UPDATE` 补全占位行的 `title`/`summary`/`tags`/`category`/`score`/`highlights`/`score_reason`/`analyzed_at`/`language` 等字段（CAS 条件 `WHERE id=... AND status=pending`），commit 后投影 `knowledge/articles/<article_id>.json`，**再渲染 `knowledge/articles/<article_id>.md`**。状态保持 `pending`。

每个 agent 的输出在传递给下游之前，会通过 **Pydantic schema** 验证，因此格式错误的 agent 响应会快速失败而非静默污染后续阶段。外部依赖（HTTP 抓取、LLM 调用、DB 会话）通过依赖注入传入，便于在单一 graph 测试 seam 上用 fakes 替换。

单条失败不中断整批：每条用 try/except 包裹，失败记 `logger.exception` 并跳过，批末汇总成功/跳过/失败计数。

### 四个开放问题的决策

1. **上游失败下游怎么办** -> 逐条隔离：单条采集/分析失败记 `ERROR` 并跳过，不污染下游；不新增失败态，条目留原态。占位行失败时删除占位行（G12）。
2. **数据怎么传** -> 阶段间用文件 + 内存 JSON：原始内容落 `knowledge/raw/<article_id>.md`，分析产出以内存 JSON 传给整理节点；DB `kb_article` 为唯一 source of truth，磁盘 JSON 为投影，Markdown 为渲染视图。
3. **重跑策略** -> 采集侧按 `source_url` 幂等去重（查 DB `kb_article.source_url`），已存在则跳过；状态转换用 `WHERE status=<期望旧值>` 的 CAS 更新。
4. **进度追踪** -> 用 `status` + `collected_at`/`analyzed_at` 时间戳 + DB 行存在性追踪；进度可通过查 `kb_article` 表得到。

---

## 3. 用户故事

### 采集（collector）

1. 作为知识库维护者，我希望每天自动从 GitHub Trending 抓取热门 AI 仓库，这样我就不用手动浏览 trending 页面。
2. 作为知识库维护者，我希望每天自动从 Hacker News 抓取热门 AI 讨论，这样我能覆盖社区视角而非仅仓库视角。HN 数据源使用 HN Official API（Firebase `https://hacker-news.firebaseio.com/v0/`，`/v0/topstories` + `/v0/item/<id>`）（G15）。
3. 作为知识库维护者，我希望采集结果按 AI/LLM/Agent 关键词过滤，这样知识库保持主题聚焦、不被无关内容污染。
4. 作为知识库维护者，我希望 collector 每次运行返回至少 15 条候选，以便下游分析有足够素材（数据源不足时除外，须说明原因）。
5. 作为知识库维护者，我希望采集结果按热度（star/points）降序排列，这样信息量最大的条目优先处理。
6. 作为知识库维护者，我希望每条候选项提取 title/url/source/popularity/summary 五字段，这样下游分析有结构化输入。collector 输出的 `popularity` 在 organizer 阶段映射为 `source_score` 持久化（G13）。
7. 作为知识库维护者，我希望重跑采集时已存在的 `source_url` 被跳过，这样不会对同一来源重复生成条目（幂等性）。
8. 作为知识库维护者，我希望 collector 在抓取前检查 DB `kb_article.source_url`，以便已采集的 URL 不会被重复抓取（G2：一律查 DB，无退化路径）。
9. 作为知识库维护者，我希望外部 HTTP 请求遵守速率限制并指数退避重试，这样不会被数据源封禁并恢复瞬态故障。
10. 作为知识库维护者，我希望采集并发线程池上限 ≤5，这样不会因并发过高触发限流。
11. 作为知识库维护者，我希望单次 HTTP 超时 30s、总采集超时 10 分钟，这样卡死的请求不会无限拖长流水线。
12. 作为知识库维护者，我希望 `popularity` 语义明确（GitHub=总 star 数 / HN=points），这样排序与展示无歧义。

### 原始内容持久化（persist_raw）

13. 作为知识库维护者，我希望原始内容以独立 Markdown 文件存入 `knowledge/raw/<article_id>.md`，这样每条可独立溯源、不被批量文件混淆。`article_id` 由 persist_raw 的取号前置步骤生成（G1）。
14. 作为知识库维护者，我希望原始 MD 保留来源标题、URL、正文与采集时间元信息，这样后续分析与审计有完整上下文。
15. 作为知识库维护者，我希望 `knowledge/raw/` 中的原始内容文件只可追加不修改不删除，这样原始源数据作为不可变审计证据不会丢失。

### 分析（analyzer）

16. 作为知识库维护者，我希望分析阶段为每条生成 2-4 句、≤150 字的中文摘要，这样我能快速判断是否值得深读。
17. 作为知识库维护者，我希望分析阶段提炼 1-3 条含具体数据的亮点，这样条目的价值点一目了然。
18. 作为知识库维护者，我希望分析阶段给出 1-10 评分及评分理由，这样我能按价值排序审核队列（按 score 排序走文件排序，不新增索引，G8）。
19. 作为知识库维护者，我希望分析阶段给出 3-8 个小写英文标签，这样相同主题可聚合检索。
20. 作为知识库维护者，我希望分析阶段对相同技术主题复用已有标签，以便标签词汇保持一致。
21. 作为知识库维护者，我希望分析阶段给出分类（model_release/paper/tool/tutorial/news），这样条目按类型归档。
22. 作为知识库维护者，我希望分析阶段识别原文语言（zh/en），这样后续分发可做语言处理。
23. 作为知识库维护者，我希望分析产出不直接落盘，这样格式与去重由整理阶段统一把关。
24. 作为知识库维护者，我希望 analyzer 获取 README 时自动尝试 main/master 分支容错，这样单分支 404 不阻塞分析。

### 整理（organizer）

25. 作为知识库维护者，我希望整理阶段做 URL 去重，这样不会出现重复条目。
26. 作为知识库维护者，我希望整理阶段做标题相似度去重，这样同一主题多来源只保留信息量最大的一条，其余归档。去重算法：**同批内**按归一化标题（去标点、小写、去停用词）的 **Jaccard 相似度 ≥ 0.8** 视为重复，保留 `source_score` 最高的一条，其余标 `archived`。阈值由 `src/config/` 配置项 `DEDUP_THRESHOLD` 控制，默认 0.8（G6）。
27. 作为知识库维护者，我希望整理阶段把分析产出（含 score/highlights/score_reason）与采集元信息合并为标准 JSON，这样条目字段完整、不遗漏分析深度信息。
28. 作为知识库维护者，我希望整理阶段先写 DB 事务再投影 JSON 文件再渲染 MD，这样 DB 作为唯一 source of truth、磁盘可重建、MD 可重生成。
29. 作为知识库维护者，我希望条目 JSON 文件名为 `knowledge/articles/<article_id>.json`，这样文件名与业务 ID 一一对应、便于程序定位。
30. 作为知识库维护者，我希望 organizer 为每条知识条目输出 **Markdown** 文件到 `knowledge/articles/<article_id>.md`，以便以人类友好格式阅读条目。
31. 作为知识库维护者，我希望 organizer 同时持久化结构化 JSON 记录（DB 行 + JSON sidecar）作为机器可读的 source of truth，以便工具可以编程查询和渲染条目。
32. 作为知识库维护者，我希望 organizer 在写入前根据知识条目 schema 验证最终条目，以便格式错误的条目不会到达磁盘。
33. 作为知识库维护者，我希望新条目初始 `status: pending`，这样未经审核的内容不会被误分发。
34. 作为知识库维护者，我希望去重落选条目标记为 `archived`，以便保留但不重复发布。
35. 作为知识库维护者，我希望 `article_id` 格式为 `kb-YYYYMMDD-NNNN`（NNNN=DB 自增主键零填充），这样 ID 全局唯一、可排序。
36. 作为知识库维护者，我希望 `article_id` 取号在 persist_raw 的 DB 事务内（INSERT 占位行 -> LAST_INSERT_ID -> 回填），这样并发取号由 InnoDB 自增锁保证（G1）。
37. 作为知识库维护者，我希望 `id > 9999` 时报错而非静默溢出，这样 4 位序号上限有显式护栏。
38. 作为知识库维护者，我希望 JSON 写入前做合法性校验，这样不会因引号未转义导致下游解析失败。

### 失败处理与韧性

39. 作为知识库维护者，我希望单条采集失败不中断整批，这样一次坏链接不会让整日采集报废。
40. 作为知识库维护者，我希望单条分析失败（如 LLM 超时）不中断整批，这样其他条目仍能入库。
41. 作为知识库维护者，我希望单条整理失败（如 DB 冲突）不中断整批，这样已成功的条目不回滚。
42. 作为知识库维护者，我希望每批结束时日志汇总成功/跳过/失败计数，这样我能快速评估运行健康度。
43. 作为知识库维护者，我希望某一阶段失败时记录 ERROR 并将条目留在当前状态，以便可以重试而不损坏数据。

### 流水线编排与触发

44. 作为知识库维护者，我希望流水线通过 `src/main.py --stage collect|analyze|organize|render-md|all` 触发，这样我能单段调试或全量运行（G14：统一为 `organize`，新增 `render-md` 重建 MD，G7）。
45. 作为知识库维护者，我希望重跑同一天不会产生重复条目，这样定时任务的幂等性有保证。
46. 作为知识库维护者，我希望 CronJob 触发全流程，这样无需人工干预即可每日更新知识库。
47. 作为知识库维护者，我希望流水线产出可在 `kb_article` 表查询到对应行，这样 DB 是可查询的权威数据源。
48. 作为知识库维护者，我希望磁盘 JSON 与 DB 行一致、不一致时以 DB 为准，这样灾备可从 DB 重建磁盘。MD 文件视为纯派生态，不纳入一致性校验，可由 `--stage render-md` 从 JSON 重建（G7）。

### Agent 权限模型

49. 作为开发者，我希望采集 Agent 只读只搜（无 Write/Edit/Bash），这样采集侧无法越权落盘。
50. 作为开发者，我希望分析 Agent 只读分析（无 Write/Edit/Bash），这样分析侧无法越权改库。
51. 作为开发者，我希望整理 Agent 唯一可写 `knowledge/articles/`（无 WebFetch/Bash），这样写入入口集中、可审计。persist_raw 的 raw MD 写入与 DB 占位行 INSERT 在 graph 层（organizer 之外）执行。
52. 作为开发者，我希望 agent 角色定义 Markdown 文件准确反映 MD 输出决策和两个数据源，以便 prompt 与实际实现匹配。

### 数据契约与验证

53. 作为开发者，我希望每个 agent 的输出通过 Pydantic 模型验证，以便在交接前捕获契约违规。
54. 作为开发者，我希望有一个端到端测试，输入 mock GitHub Trending 数据并断言最终 MD 输出，以便放心重构。
55. 作为知识库维护者，我希望状态转换遵循 §6.6 矩阵（pending->reviewed->published），这样生命周期可控、不可越级。
56. 作为知识库维护者，我希望 DB 写入用 CAS 条件更新保证并发安全，这样多实例并发不会状态错乱。

### 工程质量

57. 作为知识库维护者，我希望 LLM API Key / GitHub Token 从环境变量读取，这样密钥不入库、不泄露。
58. 作为知识库维护者，我希望日志用 `%s` 占位符且不输出密钥，这样日志安全且生产级别过滤高效。
59. 作为知识库维护者，我希望所有公开函数有类型注解并通过 mypy strict，这样代码可静态维护。
60. 作为知识库维护者，我希望流水线有 ≥80% 覆盖率的 pytest 测试，这样重构有安全网。
61. 作为知识库维护者，我希望事务短小、不含远程调用，这样不会长事务锁争用。raw MD 写入、JSON 投影、MD 渲染均在 DB 事务之外，事务内仅 INSERT/UPDATE（G11）。
62. 作为知识库维护者，我希望 SQL 显式指定字段、不用 `SELECT *`，这样索引有效、列变更无隐患。
63. 作为知识库维护者，我希望 collector 在 INFO 级别记录采集开始/完成，以便监控流水线运行。

---

## 4. 实现决策

### 4.1 架构与编排

- **工作流引擎选用 LangGraph**（已在 `pyproject.toml` 依赖中）。定义一个串行状态机：`collect -> persist_raw -> analyze -> organize`，共 4 节点 = 3 个 Agent 节点 + 1 个 graph 层持久化节点（G4）。`persist_raw` 是 graph 层步骤（非 Agent，在 collector 之外，因 collector 无写权限），负责取号前置与原始内容持久化。
- 状态对象持有：候选列表、原始文件路径、分析结果和最终条目记录，在节点间流转。
- **graph 节点是普通 Python 函数**（G5），调用 `src/collectors/`、`src/analyzers/`、`src/organizers/` 中的业务逻辑，**不通过 OpenCode subagent 运行时**。OpenCode agent 定义（`.opencode/agents/*.md`）仅作为 prompt/权限文档，与 Python 实现解耦。每个节点通过 Pydantic schema 验证输出。
- **CLI 入口复用 `src/main.py`**，扩展现有 `--stage` 分支：`collect/analyze/organize/render-md/all`（G14：`curate` 改名 `organize`；G7：新增 `render-md` 重建缺失 MD）。不新增根目录脚本。
- **调度不动**：维持 `deploy/k8s/06-cronjob.yaml` 的 `0 */6 * * *` 现状（draft PRD 写每日 UTC 0:00，但现有部署已是每 6 小时；本 Spec 不改调度，仅保证幂等使其可安全高频运行）。
- **依赖注入**：graph 节点函数接收一个 `deps` 依赖容器（HTTP fetcher、LLM client、ArticleRepository），生产用真实实现、测试用 fakes。这是单一测试 seam 的基础。

### 4.2 数据传输（回答开放问题 2）

- **阶段间数据用「文件 + 内存 JSON」**：
  - collector 返回内存中的 JSON 数组（不写文件）。
  - persist_raw（graph 层）**取号前置**：DB 事务内 INSERT 占位行 -> 取号 -> 回填 article_id -> commit -> 写 `knowledge/raw/<article_id>.md`，同时把候选元信息（title/url/source/score/collected_at/content_path/article_id）放进 graph 状态（G1）。
  - analyzer 读 MD、产出内存 JSON 放回状态。
  - organizer 合并后 DB 事务内 UPDATE 补全 + commit -> 写 JSON sidecar -> 渲染 MD。
- 每次交接的载荷在传递给下游之前通过 **Pydantic 模型**验证。

### 4.3 输出格式决策（MD vs JSON）

- **JSON sidecar**（`knowledge/articles/<article_id>.json`）和 **MySQL `kb_article` 行**是权威的、可查询的 source of truth（按 AGENTS.md §4）。
- **organizer 额外输出 Markdown** 文件作为面向人类的制品。此 MD 是从结构化条目派生的渲染视图——它不是主存储。
- **写入顺序**：DB（事务）-> JSON sidecar -> Markdown 渲染。如果 MD 渲染失败，条目仍持久化在 DB/JSON 中；MD 可由 `--stage render-md` 从 JSON sidecar 重建（G7）。MD 视为纯派生态，不纳入「一致性」校验，DB 不设 `md_rendered` 标志列。
- MD 内容包括标题、摘要、亮点、标签、分类、来源 URL 和采集/分析时间戳，以人类可读布局呈现。

### 4.4 模块划分（路径遵循 §2.2）

| 模块 | 职责 |
| --- | --- |
| `src/collectors/` | GitHub Trending 采集器、HN 采集器（HN Official API）、关键词过滤、热度排序。HTTP 客户端统一用 `httpx`（G10）。 |
| `src/analyzers/` | LLM 摘要/亮点/评分/标签/分类/语言生成，prompt 构造与响应解析。 |
| `src/organizers/` | URL 去重、标题相似度去重（Jaccard ≥0.8，G6）、标准 JSON 封装、DB 写入、JSON 投影、MD 渲染。 |
| `src/graph/` | LangGraph 状态机定义、节点函数（含 persist_raw 取号前置）、依赖容器、`run()` 入口。 |
| `src/models/` | 复用已有 `enums.py`；新增 Pydantic schema + SQLAlchemy ORM 映射 `kb_article`。 |
| `src/config/` | 环境变量加载、DB 连接串拼装（按 §2.4 字段拼，禁用单一 `DATABASE_URL`）、`DEDUP_THRESHOLD` 配置（默认 0.8）。 |
| `src/utils/` | 复用 `id_gen.py`；新建 `src/utils/http_client.py` 封装 httpx（G10）；新增 slug 生成、相似度计算、JSON 合法性校验工具。`github_api.py` 迁移至 httpx。 |

### 4.5 Pydantic Schema 模型（`src/models/`）

- `CollectorCandidate` - 验证单个 collector 输出项（title, url, source, popularity, summary）。
- `AnalyzerResult` - 验证 analyzer 输出对象（title, summary, highlights, score, score_reason, tags, category, language）。
- `KnowledgeArticle` - 验证完整最终条目（AGENTS.md §4 的所有字段 + 扩展字段）。复用现有 `src/models/enums.py`（ArticleStatus, Category, SourcePlatform）枚举。
- **向后兼容**（G9）：`score`/`highlights`/`score_reason` 在 Pydantic 模型中设为 `Optional` 默认 `None`，以便读取现有 10 个旧 JSON 文件时容错；但 **organizer 写入逻辑强制填值**（写入前断言非 None），确保新条目不遗漏。旧文件不强制迁移。
- 现有 `src/models/enums.py` 中的枚举是枚举值的唯一定义点；Pydantic 模型引用它们。

### 4.6 幂等与重跑（回答开放问题 3）

- **采集侧幂等**：collect 对每条候选先查 DB `kb_article.source_url`，已存在则跳过、不写新 MD、不生成新 id。**删除「无 DB 退化」分支**（G2）——幂等检查一律查 DB，测试时由 repository fake 提供，生产代码不退化。
- **状态转换 CAS**：所有 `UPDATE ... SET status=... WHERE id=... AND status=<期望旧值>`，利用条件更新保证并发安全（§6.6 要点 4）。
- 分发幂等不在本 Spec（out of scope），但整理阶段产出的 `pending` 条目为后续分发幂等（查 `published_channels`）留好字段。

### 4.7 失败处理（回答开放问题 1）

- **逐条隔离**：collect/analyze/organize 各自对每条用 try/except 包裹，失败记 `logger.exception`（带 article_id/url 上下文，不带密钥），跳过该条继续下一条。
- **占位行回滚**（G12）：persist_raw 失败时（如 raw MD 写入失败），**删除已插入的占位 DB 行**，确保最终无半成品 DB 行；raw MD 若已写则保留（符合 raw 只追加），下次重跑时占位行重新插入。analyzer/organizer 失败时，占位行已存在且 status=pending，**保留占位行**（留原态），由重试或人工介入补全——不删除，因其 `source_url` 已占位可防重复采集。
- **批末汇总**：每节点结束记 `INFO`：成功 N / 跳过 M / 失败 K。

### 4.8 进度追踪（回答开放问题 4）

- **DB 行 + 时间戳**：`collected_at`（persist_raw 占位行写入时填）、`analyzed_at`（organizer UPDATE 时填）、`status` 字段。查 `SELECT id, article_id, status, collected_at, analyzed_at FROM kb_article WHERE ...` 即得进度。
- **不引入额外进度表**：避免冗余；`status` 枚举 + 时间戳已足够。

### 4.9 文件命名决策

- **article JSON 文件名 = `<article_id>.json`**（如 `kb-20260727-0001.json`），对齐 §4。
- **article MD 文件名 = `<article_id>.md`**（如 `kb-20260727-0001.md`），与 JSON 同名异后缀。
- **raw MD 文件名 = `<article_id>.md`**，对齐 §6.7。因取号前置（G1），persist_raw 写 raw MD 时 article_id 已生成，文件名一次成型，无需重命名。
- 现有 10 个 `{date}-{source}-{slug}.json` 文件和批量 `github-trending-2026-07-27.json` 属历史产物，新写入必须用 article_id 命名；旧文件迁移为可选项。

### 4.10 Schema 扩展决策（来自实测发现）

- **持久化分析深度字段**：§4 标准 schema 未含 `score`/`highlights`/`score_reason`，但 analyzer 产出它们、实测日志 P1 要求「不能遗漏」。本 Spec 决策：**扩展 `kb_article` 表**增加以下三列，并在磁盘 JSON 投影中写出：

  | 新增列 | 类型 | 说明 |
  | --- | --- | --- |
  | `score` | `TINYINT UNSIGNED NULL` | analyzer 评分 1-10 |
  | `score_reason` | `VARCHAR(500) NULL` | 评分理由 |
  | `highlights` | `JSON NULL` | 亮点数组 |

- **索引决策**（G8）：**不新增 `score` 索引**。按 score 排序审核队列走文件排序（`ORDER BY score`，数据量小可接受），避免单表索引数达 §7.3 上限 5 个。现有 4 个索引（`uk_article_id`、`idx_source_url`、`idx_status_created`、`idx_category`）保持不变。
- 这是对 §7.5 DDL 的有意识扩展，须同步更新 §7.5 与 §4（由实现者在本 Spec 落地时一并改 AGENTS.md——本 Spec 授权此改动）。
- 来源于 `docs/sub-agent-test-log.md` 实测：整理 Agent 首次写入遗漏这三个字段，已列为 P1 修复项。

### 4.11 Article ID 生成（取号前置，G1）

- 复用现有 `src/utils/id_gen.py::build_article_id(db_id, collected_at)`——格式 `kb-YYYYMMDD-NNNN`，NNNN = DB 自增主键零填充至 4 位。无需修改。
- **取号前置流程**（在 persist_raw 节点的 DB 事务内）：
  1. `INSERT` 占位行（`status=pending`，`source_url`/`source_platform`/`source_score`/`collected_at` 已填，其余字段留空/默认）。
  2. 取 `LAST_INSERT_ID()` 得到 `id`。
  3. `build_article_id(id, collected_at)` 生成 `article_id`。
  4. `UPDATE` 回填 `article_id`。
  5. 提交事务。
  6. 写 `knowledge/raw/<article_id>.md`（事务外）。
- 并发安全由 InnoDB 自增锁保证。
- `id > 9999` 时报错（4 位上限），扩位改 `_SEQ_WIDTH` 常量即可。
- **失败回滚**：步骤 1-5 任一失败则回滚事务（占位行不留）；步骤 6 失败则删除占位行（G12）。

### 4.12 状态机

- 与 AGENTS.md §6.6 一致，无变更。新条目以 `pending` 开始（persist_raw 占位行即 pending）。organizer UPDATE 补全后仍为 `pending`。转换为 `reviewed` / `published` / `archived` 遵循现有矩阵。不新增状态。

### 4.13 DB Schema

- `kb_article` 表按 §4.10 扩展三列（score/score_reason/highlights），其余按 AGENTS.md §7.5 不变。
- `content_path` 继续指向 `knowledge/raw/` 中的原始 MD 文件路径；organizer MD 输出路径按约定派生（`knowledge/articles/<article_id>.md`），不存储为单独列。
- **不设 `md_rendered` 标志列**（G7 决策 B）：MD 是派生态，由 `--stage render-md` 重建。

### 4.14 Agent 角色定义文件更新（`.opencode/agents/`）

- **三个文件都将更新**以反映：(a) organizer 输出为 Markdown（含 JSON sidecar + DB 行），(b) GitHub Trending 和 Hacker News 都是 collector 的一等数据源。
- **collector.md**：权限模型不变（read/grep/glob/webfetch 允许；write/edit/bash 禁止）。输出契约不变：候选 JSON 数组。
- **analyzer.md**：权限模型不变（read/grep/glob/webfetch 允许；write/edit/bash 禁止）。输出契约不变：JSON 对象。
- **organizer.md**：权限模型不变（read/grep/glob/write/edit 允许；webfetch/bash 禁止）。**输出契约变更**：organizer 的主要交付物变为 Markdown 文件 + JSON sidecar + DB 行。

### 4.15 LLM 调用

- 通过 OpenAI 兼容 API 调字节模型（`LLM_API_KEY`/`LLM_API_BASE`/`LLM_MODEL` 环境变量）。analyzer 构造 prompt（原文 + 规范要求）-> 解析 JSON 响应 -> 校验字段（摘要长度、标签数量、评分范围、分类枚举）-> 不合法则记 WARNING 跳过。

### 4.16 HTTP 客户端（G10）

- **统一用 `httpx`**（已在 `pyproject.toml` 依赖中，支持 async/重试/连接池）。新建 `src/utils/http_client.py` 封装 httpx 客户端（含速率限制、指数退避、超时配置）。
- **废弃 `urllib` 路径**：现有 `src/utils/github_api.py` 迁移至 httpx，或由 `http_client.py` 取代。
- 速率限制遵守 AGENTS.md §6.1：GitHub API 匿名 ≥2s、带 Token ≥0.5s，HN API ≥1s；指数退避初始 1s 倍增上限 60s 最多 3 次；并发 `max_workers ≤ 5`；单次超时 30s，总超时 10 分钟。

### 4.17 红线对齐

- raw 只追加、published 后不可改内容、source_url 必填、禁 print、禁硬编码密钥、禁跳类型注解、禁 pending 直推、禁采非 AI、禁编造、禁日志泄密、禁 rm -rf、禁改 AGENTS.md（本 Spec 授权的 schema 扩展除外）、禁乱放路径、禁 DB 外键/存储过程/触发器/视图、禁 SELECT *。
- **事务边界**（G11）：raw MD 写入、JSON 投影、MD 渲染均在 DB 事务之外；事务内仅 INSERT/UPDATE，禁止远程调用（AGENTS.md §7.4 规则 6）。

---

## 5. 测试决策

### 5.1 测试理念

- 测试断言**外部行为**（输入 -> 可观察输出），而非实现细节（不测试私有方法或 mock 内部）。
- 优先使用最高、最少的接缝。主接缝为 graph 端到端；Pydantic schema 验证作为契约测试子接缝（测试外部数据契约，非内部实现）。

### 5.2 主接缝：端到端流水线测试

- **位置**：`tests/graph/test_pipeline.py`（镜像 `src/graph/`）。
- **seam = LangGraph graph 的 `run()` 入口**（`src/graph/`）。所有外部 I/O 通过依赖注入替换为 fakes：
  - HTTP fetcher fake：返回固定 HTML/JSON（GitHub Trending 页面片段、HN Official API 响应、README 文本），覆盖成功/404/超时/429 场景。
  - LLM client fake：返回符合 analyzer 输出 schema 的 canned JSON，覆盖正常/字段不合法/超时场景。
  - **DB fake：纯内存 repository fake**（G3 决策 A）——定义 `ArticleRepository` 协议（`insert_placeholder`/`get_by_url`/`update_status`/`update_fields`/`get_last_insert_id`/`delete_by_id`），生产用 SQLAlchemy+MySQL 实现，测试用纯 Python dict 实现。graph 测试驱动 fake，不触 SQL。**禁用 SQLite**（与 MySQL `JSON`/`DATETIME(3)`/`LAST_INSERT_ID()` 特性不兼容，会掩盖问题）。
- **方法**：将固定的 mock GitHub Trending HTML 载荷和固定的 mock HN API 响应输入流水线。运行完整的 `collect -> persist_raw -> analyze -> organize` graph。断言最终 `knowledge/articles/` 输出包含预期的 JSON sidecar（符合 `KnowledgeArticle` schema）和 Markdown 文件（正确结构）。
- 测试中 LLM 支撑的 analyzer 被 stub（返回预设的 `AnalyzerResult`），使测试确定性且不消耗 API 配额。collector 的网络调用也被 mock。
- 不单独为纯函数开 sub-seam：slug 生成、相似度、id_gen 等纯辅助通过 graph seam 的输入-输出间接覆盖；`id_gen` 已有逻辑，graph 测试会驱动 `build_article_id` 的真实调用。
- 边界用例：空采集、全失败、全重复、占位行失败回滚（G1/G12）。

### 5.3 子接缝：Agent 输出 Schema 验证

- **位置**：`tests/models/test_schemas.py`。
- **方法**：用有效和无效载荷单元测试 Pydantic 模型（`CollectorCandidate`、`AnalyzerResult`、`KnowledgeArticle`）。这在不调用任何 LLM 或网络的情况下验证契约——纯数据结构测试。含旧文件容错测试（G9：无 score 字段的 JSON 可解析，score=None）。
- 前例：现有 `src/models/enums.py` 已有 parse/serialize 方法，应在此一并覆盖。

### 5.4 好测试的标准

- 只断言**外部可观察行为**：磁盘 JSON/MD 文件内容（字段完整、shape 符合 §4+扩展）、DB 行（存在性、status、时间戳、article_id 格式）、幂等性（重跑无重复）、失败隔离（一条坏数据不阻断其他条目入库）、日志（成功/跳过/失败计数）、占位行回滚（失败时无半成品行）。
- **不断言**内部私有方法调用顺序、mock 调用次数等实现细节。

### 5.5 测试模块与 prior art

- `tests/graph/test_pipeline.py`：端到端 graph 测试（主 seam）。
- `tests/models/test_schemas.py`：Pydantic schema 契约测试（子 seam）。
- `tests/` 镜像 `src/` 结构（§2.2 规则 2）。
- **prior art**：仓库暂无测试目录，本 Spec 建立测试基线。`src/utils/id_gen.py` 的 `build_article_id` 是现有可测纯函数的范本，graph 测试会覆盖其真实路径。

### 5.6 覆盖率

- 目标 ≥80%（`pyproject.toml` 已配 `fail_under=80`）。graph seam 端到端 + schema 契约测试 + 边界用例应足以达标。

---

## 6. 不在范围内

- **分发**（Telegram/飞书推送、`status: published` 转换）：由 `distribute-message` skill 与后续 Spec 处理。本 Spec 仅产出 `pending` 条目并保留 `published_channels` 字段为 null。
- **审核 UI / 前端**：Vue 前端不在本 Spec。
- **向量数据库 / ChromaDB / RAG 检索**：本 Spec 不涉及向量化；条目仅持久化到 MySQL + JSON + MD。
- **CronJob 调度频率调整**：维持现有 `0 */6 * * *`，不改调度。
- **DB 迁移工具**：`kb_article` DDL 已定义，但此处不引入 Alembic/迁移框架。
- **历史 10 个 slug 命名文件的强制迁移**：新写入用 article_id 命名；旧文件迁移为可选项。
- **归档条目的重新抓取/重新分析**：幂等检查跳过已有 URL；重新处理归档内容是未来关注点。
- **多语言摘要生成**（除 zh 外）：摘要固定中文。
- **AGENTS.md 重写**：仅授权 §4/§7.5 的 schema 扩展同步，不重构 AGENTS.md。

---

## 7. 补充说明

- **MD 输出是渲染视图**（G7）：organizer 写入的 Markdown 从结构化 JSON 条目派生。如果 JSON 变更（如状态转换为 `published`），MD 可由 `--stage render-md` 重新生成。JSON/DB 仍按 AGENTS.md §4 为 source of truth。MD 不纳入一致性校验，DB 不设 `md_rendered` 列。
- **权限模型是核心支柱**：collector 和 analyzer 刻意设为只读（无 write/edit/bash），确保未经审核的数据不会到达磁盘。organizer 是 `knowledge/articles/` 的唯一写入者；persist_raw 的 raw MD 写入与 DB 占位行 INSERT 在 graph 层（organizer 之外）执行，因 collector 无写权限。
- **Agent 权限模型与 Python 实现的关系**（G5）：`.opencode/agents/*.md` 已定义 collector/analyzer/organizer 的权限矩阵，仅作为 prompt/权限文档。本 Spec 的 Python 实现是 graph 节点（普通 Python 函数），由主进程统一执行，**不通过 OpenCode subagent 运行时**。实测日志显示 subagent 因模型 ID 配置（`volcengine/ark-code-latest` 缺 `plan` 前缀）未启动——这是运行时配置问题，不在本 Spec 修复范围，graph 代码不依赖 subagent 隔离即可正确运行。
- **`popularity` vs `source_score` 映射**（G13）：collector 输出字段 `popularity`，DB/JSON 字段 `source_score`。organizer 阶段将 `popularity` 映射为 `source_score` 持久化。GitHub 用总 star 数（与 trending 页面一致）、HN 用 points。
- **README 分支容错**：实测日志 P2 指出单分支 404 阻塞分析。analyzer 的 HTTP fetcher 须自动尝试 `main` 后 `master`。
- **JSON 合法性自检**：实测日志 P2 指出引号未转义导致解析失败。所有 JSON 写入前用 `json.dumps` 序列化后回读校验。
- **`article_id` 与文件名一致性**：实测日志 P3 指出序号与文件名排序不一致。本 Spec 用取号前置（G1）+ `<article_id>.json` 命名从根本上消除该问题。
- **AGENTS.md §4 需要后续编辑**以记录双输出（JSON source of truth + MD 渲染）决策，因为 §4 当前仅指定 JSON。该编辑由此 spec 跟踪，但 AGENTS.md 文件本身应由实现 agent 更新（需维护者批准，按红线第 12 条）。
- **现有 agent 文件是基线**：三个 `.opencode/agents/*.md` 文件已包含详细的、结构良好的角色定义。本 spec 是更新而非从头重写——权限模型、质量自查清单和红线是合理的，应予保留。

---

## 8. 验收标准（Definition of Done）

- [ ] `src/graph/` 串行状态机（collect -> persist_raw -> analyze -> organize）可端到端运行，4 节点（3 Agent + 1 graph 层持久化）（G4）
- [ ] persist_raw 取号前置：INSERT 占位行 -> LAST_INSERT_ID -> 回填 article_id -> 写 raw MD（G1）
- [ ] 产出 `knowledge/articles/<article_id>.json`（JSON sidecar）+ `knowledge/articles/<article_id>.md`（MD 渲染）+ DB 行
- [ ] 新条目 `status: pending`，含 §4 全字段 + `score`/`highlights`/`score_reason` 扩展字段
- [ ] raw MD 为 `knowledge/raw/<article_id>.md` 独立文件，含来源标题/URL/正文/采集时间
- [ ] 写入顺序：DB 事务 -> JSON sidecar -> MD 渲染；MD 失败不回滚 DB/JSON；`--stage render-md` 可重建 MD（G7）
- [ ] 重跑同批不产生重复条目（`source_url` 幂等，查 DB，无退化路径）（G2）
- [ ] 单条失败不中断整批，批末日志汇总成功/跳过/失败计数；占位行失败时删除占位行（G12）
- [ ] 每次 agent 交接通过 Pydantic schema 验证；旧文件容错（score 可 None）（G9）
- [ ] HTTP 速率限制 + 指数退避 + 并发≤5 + 超时 30s/10min；统一用 httpx（G10）
- [ ] 密钥全走环境变量，日志无密钥
- [ ] `kb_article` 表 DDL 扩展 score/highlights/score_reason 三列；不新增 score 索引（G8）（同步更新 AGENTS.md §4/§7.5）
- [ ] 状态转换用 CAS 条件更新
- [ ] 标题去重：同批 Jaccard ≥0.8，保留 source_score 最高，其余 archived（G6）
- [ ] `.opencode/agents/*.md` 三个文件更新（organizer 输出 MD + 双数据源）
- [ ] DB fake 用纯内存 repository 协议，禁用 SQLite（G3）
- [ ] `--stage` 含 `organize`（非 curate）与 `render-md`（G7/G14）
- [ ] `uv run ruff check src/ tests/` 通过
- [ ] `uv run mypy src/` 通过
- [ ] `uv run pytest tests/ --cov=src --cov-fail-under=80` 通过
