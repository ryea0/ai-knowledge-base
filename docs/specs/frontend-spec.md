# 前端页面规范

> 本文件从 AGENTS.md §11 拆分而来，章节编号保持不变。
> 前端工程位于 `kb-web/`，技术栈见 AGENTS.md §1（Vue 3 Composition API + TypeScript + Element Plus）。
> 页面级组件统一放 `kb-web/src/views/`，与路由一一对应；路由定义见 `kb-web/src/router/index.ts`。

---

## §11.1 页面总览

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

## §11.2 仪表盘（DashboardView）

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

## §11.3 知识条目列表（ArticleListView）

| 要素 | 说明 |
| ---- | ---- |
| 路由 | `/articles` |
| 组件 | `kb-web/src/views/ArticleListView.vue`（已存在，需增强） |
| API | `GET /articles`（分页列表） |
| 已有功能 | 状态筛选、分类筛选、关键词搜索、分页、行点击跳转详情 |
| 需增强 | |

1. **标签筛选**：新增标签下拉多选筛选器，支持按标签过滤。
2. **来源平台筛选**：新增来源平台下拉（github_trending / hackernews / 全部）。
3. **批量操作**：列表增加多选 checkbox，支持批量审核（pending->reviewed）、批量归档。
4. **列展示优化**：标签列以 `el-tag` 展示前 3 个标签，超出显示 `+N`。

## §11.4 条目详情（ArticleDetailView）

| 要素 | 说明 |
| ---- | ---- |
| 路由 | `/articles/:id`（`:id` = `article_id`） |
| 组件 | `kb-web/src/views/ArticleDetailView.vue`（已存在，需增强） |
| API | `GET /articles/:id`（条目详情）、`GET /articles/:id/raw`（原始 Markdown 内容）、`PATCH /articles/:id/status`（状态流转）、`POST /articles/:id/distribute`（触发分发） |
| 功能区块 | |

1. **基础信息区**：标题、来源链接（外链跳转）、来源平台、热度、分类、标签、语言、状态标签、各时间戳（采集 / 分析 / 发布）。
2. **AI 摘要区**：`summary` 字段渲染，突出展示。
3. **原始内容区（采集内容阅读）**：调用 `GET /articles/:id/raw` 获取 `content_path` 对应的 Markdown 原文，使用 Markdown 渲染组件展示。原始内容只读，禁止编辑（AGENTS.md 红线 #1）。
4. **状态操作区**：
   - `pending` -> 「审核」按钮（转为 `reviewed`）。
   - `reviewed` -> 「分发」按钮（选择渠道触发推送）+ 「归档」按钮。
   - `published` -> 显示已推送渠道列表（`published_channels`）+ 「归档」按钮。
   - `archived` -> 仅展示，无操作按钮。
   - 状态转换须遵循 [content-spec.md §6.6](content-spec.md) 转换矩阵，前端按当前 `status` 控制按钮可见性。
5. **分发渠道状态**：若 `published_channels` 非空，展示各渠道推送状态（图标 + 时间）。

## §11.5 LLM 供应商列表（LlmProviderListView）

| 要素 | 说明 |
| ---- | ---- |
| 路由 | `/llm/providers` |
| 组件 | `kb-web/src/views/LlmProviderView.vue`（已存在，需重构为完整 CRUD） |
| API | `GET /llm/providers`（列表）、`POST /llm/providers`（创建）、`PATCH /llm/providers/:id`（更新）、`POST /llm/providers/:id/health-check`（手动健康检查） |
| 已有功能 | 供应商列表只读展示 |
| 需增强 | |

1. **新增供应商**：对话框表单，字段见 `ProviderCreate`（[llm-provider.md §9.1](llm-provider.md)），API Key 输入框为 password 类型，提交后明文传输至后端加密存储。
2. **编辑供应商**：行内「编辑」按钮，打开预填表单；API Key 字段留空表示不修改。
3. **启用/禁用切换**：`el-switch` 直接切换 `is_enabled`，禁用即软删除（[llm-provider.md §9.4](llm-provider.md)）。
4. **手动健康检查**：行内「检查」按钮，调用 `POST /llm/providers/:id/health-check`，刷新健康状态。
5. **跳转详情**：行点击或「详情」按钮跳转 `/llm/providers/:id`。
6. **健康状态展示**：`el-tag` 颜色映射 healthy=success / degraded=warning / unhealthy=danger / unknown=info。

## §11.6 LLM 供应商详情（LlmProviderDetailView）

| 要素 | 说明 |
| ---- | ---- |
| 路由 | `/llm/providers/:id` |
| 组件 | `kb-web/src/views/LlmProviderDetailView.vue`（新增） |
| API | `GET /llm/providers/:id`、`PATCH /llm/providers/:id`、`GET /llm/providers/:id/models`、`POST /llm/providers/:id/models`、`PATCH /llm/models/:id`、`POST /llm/providers/:id/discover`（模型发现）、`GET /llm/providers/:id/health-logs`（健康日志） |
| 布局 | `el-tabs` 多 Tab 页，Tab 切换不离开路由 |
| 功能 Tab | |

1. **Tab: 供应商信息** - 供应商完整字段展示与编辑（同 §11.5 编辑表单），含 `last_check_at` / `last_success_at` / `last_failure_at` / `consecutive_failures` / `last_error` 只读展示。
2. **Tab: 模型管理** - 该供应商下所有模型列表（`GET /llm/providers/:id/models`），支持：
   - 新增模型（对话框表单，字段见 `ModelCreate`）。
   - 编辑模型（`ModelUpdate`）。
   - 启用/禁用模型（`el-switch`）。
   - 设为默认模型（`is_default`，同供应商仅一个默认）。
   - 列展示：模型代码、LiteLLM 标识、上下文窗口、函数调用/多模态支持、输入/输出价格、来源（preset/discovered/manual）、启用状态、默认标记。
3. **Tab: 模型发现** - 点击「发现模型」按钮调用 `POST /llm/providers/:id/discover`，返回 `DiscoveredModel[]` 候选列表：
   - 表格展示候选模型，含 `already_exists` 标记（已存在行灰显）。
   - 用户勾选未存在的模型，点击「批量导入」调用 `POST /llm/providers/:id/models` 批量创建。
   - 未命中 LiteLLM 注册表的字段（如定价、上下文窗口）提示用户补全。
4. **Tab: 模型健康状态** - 表格展示 `kb_llm_health` 当前状态：
   - 列：模型、健康状态、连续失败次数/阈值、最近检查时间、延迟（ms）、最近错误（脱敏后）。
   - 支持手动重置健康状态（`POST /llm/health/:model_id/reset`）。

## §11.7 工作流管理（WorkflowView）

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
   - 按 `trace_id` 查询关联日志，展示各节点（collect->analyze->curate->distribute）的执行时间线。
   - 错误信息展示（`errors` 列表）。

## §11.8 分发渠道（DistributionView）

| 要素 | 说明 |
| ---- | ---- |
| 路由 | `/distributors` |
| 组件 | `kb-web/src/views/DistributionView.vue`（新增） |
| API | `GET /distributors/channels`（渠道配置状态）、`GET /distributions`（分发历史分页）、`POST /articles/:id/distribute`（手动重发） |
| 功能区块 | |

1. **渠道配置卡片**：
   - Telegram：展示 `TELEGRAM_BOT_TOKEN` 配置状态（已配置/未配置），不展示 Token 明文。
   - 飞书：展示 `FEISHU_WEBHOOK_URL` 配置状态（已配置/未配置），不展示 URL 明文。
   - 渠道状态卡片以图标 + 状态标签展示，敏感信息脱敏（AGENTS.md 红线 #10）。
2. **分发历史列表**：
   - 列：条目标题、渠道（telegram/feishu）、推送时间、结果（success/skipped/failed）、错误信息。
   - 支持按渠道、结果筛选。
   - 分页。
3. **手动重发**：失败行提供「重发」按钮，调用 `POST /articles/:id/distribute` 重新推送（须遵循分发幂等，[content-spec.md §6.6](content-spec.md) 第 5 条）。

## §11.9 前端通用约定

1. **API 请求封装**：所有请求经 `kb-web/src/utils/request.ts`（axios 实例），统一处理 `X-Request-Id` 请求头注入与响应拦截（[trace-spec.md §10.3](trace-spec.md)）。
2. **类型定义**：与后端 Pydantic schema 对应的 TypeScript interface 放 `kb-web/src/types/` 或各 `api/*.ts` 内联定义。
3. **状态管理**：跨页面共享状态用 Pinia store（`kb-web/src/stores/`），页面内局部状态用 `ref`/`reactive`。
4. **状态流转前端校验**：所有状态操作按钮须按 [content-spec.md §6.6](content-spec.md) 转换矩阵控制可见性，前端做第一道校验，后端做权威校验。
5. **敏感信息脱敏**：前端展示 API Key / Token / Webhook URL 时仅显示掩码（如 `sk-****xxxx`），禁止明文展示（AGENTS.md 红线 #10 延伸）。
6. **Markdown 渲染**：原始内容渲染须使用 Markdown 解析库（如 `markdown-it`），渲染前不做任何内容修改（AGENTS.md 红线 #1 延伸）。
7. **路由懒加载**：所有页面组件使用 `() => import()` 动态导入，首屏仅加载 Dashboard。
