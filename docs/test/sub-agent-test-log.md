# Sub-Agent 测试日志：采集 -> 分析 -> 整理 三步流水线

## 1. 测试概览

| 项目 | 内容 |
| --- | --- |
| 测试日期 | 2026-07-27 |
| 测试场景 | 采集 GitHub Trending AI 热门项目 Top 10 -> 深度分析 -> 整理入库 |
| 测试结果 | 功能完整性验证通过，10 条知识条目成功入库；subagent 权限隔离未生效 |

### Agent 角色与执行方式

| Agent | 角色定义文件 | 期望权限 | 禁止权限 | 实际执行方式 |
| --- | --- | --- | --- | --- |
| Collector（采集 Agent） | `.opencode/agents/collector.md` | read / grep / glob / webfetch | write / edit / bash | 降级为主 Agent 直接执行 |
| Analyzer（分析 Agent） | `.opencode/agents/analyzer.md` | read / grep / glob / webfetch | write / edit / bash | 降级为主 Agent 直接执行 |
| Organizer（整理 Agent） | `.opencode/agents/organizer.md` | read / grep / glob / write / edit | webfetch / bash | 降级为主 Agent 直接执行 |

### 降级原因

三个 Agent 的 subagent 均因模型 ID 配置错误未能启动，全部降级为主 Agent 直接执行。

- 配置位置：Agent 角色定义文件 frontmatter
- 错误配置：`model: volcengine/ark-code-latest`
- 正确配置：`model: volcengine-plan/ark-code-latest`
- 缺陷描述：缺少 `plan` 前缀，导致模型 ID 与实际可用模型不匹配，subagent 启动失败

---

## 2. 逐 Agent 评估

### 2.1 Collector（采集 Agent）

#### 角色定义

从 GitHub Trending / Hacker News 搜索采集技术动态，提取标题/链接/热度/摘要，初步筛选并按热度排序，输出 JSON 候选列表，不落盘。

#### 角色执行评估

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 数据源选择 | 通过 | 使用 WebFetch 访问 `github.com/trending?since=weekly` |
| 关键词过滤 | 通过 | 从 24 个仓库筛选出 10 个 AI 相关项目 |
| 信息提取 | 通过 | 每条含 title / url / source / popularity / summary 五字段 |
| 热度排序 | 通过 | 首次排序错误，二次修正后通过 |
| 产出数量 | 部分 | 质量自查要求 >=15 条，实际 10 条（用户指定 Top 10，合理偏差） |

#### 越权行为检查

| 权限 | 是否允许 | 实际行为 | 是否越权 |
| --- | --- | --- | --- |
| WebFetch | 允许 | 正常使用 | 否 |
| Write | 禁止 | **主 Agent 直接 Write 写入 `knowledge/raw/github-trending-2026-07-27.json`** | **是 -- 越权** |
| Edit | 禁止 | **主 Agent 使用 Edit 修复 JSON 引号问题** | **是 -- 越权** |
| Bash | 禁止 | **主 Agent 使用 Bash 运行 Python 验证 JSON** | **是 -- 越权** |

#### 产出质量

| 维度 | 评价 |
| --- | --- |
| 优点 | 数据来源真实，URL 指向真实 GitHub 仓库；中文摘要准确；star 数与 Trending 页面一致 |
| 问题 1 | JSON 首次写入时中文引号未转义导致解析失败 |
| 问题 2 | 首次排序未按 popularity 降序，需重写文件 |
| 问题 3 | popularity 字段为总 star 数而非周新增，存在歧义 |

#### 需要调整

| 序号 | 调整项 | 说明 |
| --- | --- | --- |
| 1 | 修复 Agent 模型配置 | `volcengine/ark-code-latest` -> `volcengine-plan/ark-code-latest` |
| 2 | JSON 写入前校验合法性 | 避免引号未转义导致解析失败 |
| 3 | popularity 语义明确 | 明确为总 star 数还是周新增 |
| 4 | 采集 Agent 不应落盘 | subagent 修复后权限隔离才能生效 |

---

### 2.2 Analyzer（分析 Agent）

#### 角色定义

读取 `knowledge/raw/` 原始内容，生成摘要/亮点/评分/标签，输出 JSON，不落盘。

#### 角色执行评估

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 读取原始内容 | 通过 | 正常读取采集阶段产出 |
| 补充上下文 | 通过 | 使用 WebFetch 获取 10 个项目 README |
| 中文摘要 | 通过 | 2-4 句，含"是什么 + 关键特性 + 影响" |
| 亮点提炼 | 通过 | 每条 3 条亮点，含具体数据 |
| 评分 (1-10) | 通过 | 评分 7-9，附理由 |
| 标签建议 | 通过 | 5-8 个小写英文标签 |
| 分类 | 通过 | 覆盖 tool / tutorial / paper |
| 不落盘 | 部分 | 分析结果以对话输出返回，符合角色定义 |

#### 越权行为检查

| 权限 | 是否允许 | 实际行为 | 是否越权 |
| --- | --- | --- | --- |
| WebFetch | 允许 | 正常使用 | 否 |
| Read | 允许 | 正常使用 | 否 |
| Write | 禁止 | 未写文件 | 否 |
| Edit | 禁止 | 未编辑文件 | 否 |
| Bash | 禁止 | 未执行 Bash | 否 |

#### 产出质量

| 维度 | 评价 |
| --- | --- |
| 优点 1 | 分析深度高，主动获取 README 全文提取技术细节 |
| 优点 2 | 评分有据，9 分 / 8 分 / 7 分层次清晰 |
| 优点 3 | 亮点具体，含数据指标 |
| 优点 4 | 标签跨条目复用，支持聚合检索 |
| 问题 1 | 部分仓库 README 获取超时或 404，需手动换分支重试 |
| 问题 2 | 分析产出中 score / highlights / score_reason 未被整理 Agent 首次写入条目 |

#### 需要调整

| 序号 | 调整项 | 说明 |
| --- | --- | --- |
| 1 | README 获取容错 | 自动尝试 main 和 master 分支 |
| 2 | 分析产出字段对齐 | 明确包含 score / score_reason / highlights 并与整理 Agent 字段映射 |
| 3 | subagent 隔离 | 修复模型配置后在 subagent 中执行 |

---

### 2.3 Organizer（整理 Agent）

#### 角色定义

去重检查、格式化标准 JSON、存入 `knowledge/articles/`，不从外部获取信息。

#### 角色执行评估

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 去重检查 | 通过 | 确认 `knowledge/articles/` 为空，10 条 source_url 互不重复 |
| 格式化标准 JSON | 通过 | 15 个字段完整 |
| 文件命名 | 通过 | `{date}-{source}-{slug}.json` 格式 |
| status 初始值 | 通过 | 全部 pending |
| content_path | 部分 | 指向批量文件而非每个条目独立的原始 Markdown |
| 不从外部获取信息 | 通过 | 未使用 WebFetch |

#### 越权行为检查

| 权限 | 是否允许 | 实际行为 | 是否越权 |
| --- | --- | --- | --- |
| Write | 允许 | 正常写入 10 个 JSON 文件 | 否 |
| Edit | 允许 | 正常补全 score / highlights / score_reason 字段 | 否 |
| WebFetch | 禁止 | 未使用 | 否 |
| Bash | 禁止 | **主 Agent 使用 Bash 运行 Python 验证 JSON** | **是 -- 越权** |

#### 产出质量

| 维度 | 评价 |
| --- | --- |
| 优点 1 | 去重检查完整（URL + article_id + 文件名唯一性） |
| 优点 2 | 字段格式规范，必填字段完整，可空字段写 null |
| 优点 3 | 验证脚本完善，批量校验全部通过 |
| 问题 1 | 首次写入遗漏 score / score_reason / highlights 三个字段 |
| 问题 2 | content_path 指向批量文件而非独立原始文件 |
| 问题 3 | article_id 序号与文件名排序不一致 |

#### 需要调整

| 序号 | 调整项 | 说明 |
| --- | --- | --- |
| 1 | 分析字段全量映射 | score / score_reason / highlights 不能遗漏 |
| 2 | content_path 规范化 | 指向独立原始文件 `knowledge/raw/<article_id>.md` |
| 3 | 避免使用 Bash 验证 | 整理 Agent 权限禁止 Bash |
| 4 | article_id 与文件名映射一致性 | 确保序号与文件名排序对应 |

---

## 3. 综合评估

### 权限隔离情况

| Agent | 权限隔离状态 | 越权行为 | 根本原因 |
| --- | --- | --- | --- |
| Collector | 未生效 | **Write / Edit / Bash** | subagent 未启动 |
| Analyzer | 未生效 | 无（但未在 subagent 执行） | subagent 未启动 |
| Organizer | 未生效 | **Bash** | subagent 未启动 |
| -- | -- | -- | 模型 ID 配置不匹配 |

### 产出质量总评

| 维度 | 评分 | 说明 |
| --- | --- | --- |
| 数据准确性 | 8 / 10 | 数据来源真实，star 数与 Trending 页面一致 |
| 分析深度 | 9 / 10 | 主动获取 README 全文，评分有据 |
| 格式规范性 | 7 / 10 | 首次写入遗漏字段，content_path 不规范 |
| 流程完整性 | 7 / 10 | 三步流水线功能完整，subagent 未启动 |
| 去重可靠性 | 9 / 10 | URL + article_id + 文件名三重校验 |

### 优先修复项

| 优先级 | 修复项 | 影响 Agent | 说明 |
| --- | --- | --- | --- |
| P0 | 修复 Agent 模型配置（`volcengine/ark-code-latest` -> `volcengine-plan/ark-code-latest`） | 全部 Agent | 根因修复，修复后权限隔离才能生效 |
| P1 | 整理 Agent 补全分析字段（score / score_reason / highlights） | Organizer | 首次写入遗漏，需全量映射分析产出 |
| P1 | content_path 指向独立原始文件 | Collector + Organizer | 当前指向批量文件，应改为 `knowledge/raw/<article_id>.md` |
| P2 | JSON 写入前自检 | Collector | 避免引号未转义导致解析失败 |
| P2 | README 获取分支容错 | Analyzer | 自动尝试 main 和 master 分支 |
| P3 | popularity 语义明确 | Collector | 明确为总 star 数还是周新增 |

---

## 4. 测试产出文件清单

### 采集阶段

| 文件 | 说明 |
| --- | --- |
| `knowledge/raw/github-trending-2026-07-27.json` | 10 条采集数据 |

### 分析阶段

| 产出 | 说明 |
| --- | --- |
| 对话内 JSON 数组（未落盘） | 10 条深度分析结果 |

### 整理阶段（10 个文件）

| 文件名 | article_id |
| --- | --- |
| `knowledge/articles/20260727-gh-pi-agent-harness.json` | kb-20260727-0001 |
| `knowledge/articles/20260727-gh-worldmonitor.json` | kb-20260727-0002 |
| `knowledge/articles/20260727-gh-awesome-claude-skills.json` | kb-20260727-0003 |
| `knowledge/articles/20260727-gh-ai-engineering-from-scratch.json` | kb-20260727-0004 |
| `knowledge/articles/20260727-gh-kronos.json` | kb-20260727-0005 |
| `knowledge/articles/20260727-gh-omniroute.json` | kb-20260727-0006 |
| `knowledge/articles/20260727-gh-deeptutor.json` | kb-20260727-0007 |
| `knowledge/articles/20260727-gh-orca.json` | kb-20260727-0008 |
| `knowledge/articles/20260727-gh-code-review-graph.json` | kb-20260727-0009 |
| `knowledge/articles/20260727-gh-ai-agent-book.json` | kb-20260727-0010 |

---

## 5. 结论

本次测试验证了三步流水线的功能完整性，10 条知识条目成功入库。存在两个核心问题：

1. **subagent 未实际启动**：模型 ID 配置错误（`volcengine/ark-code-latest` 缺少 `plan` 前缀）导致权限隔离完全失效，三个 Agent 均降级为主 Agent 直接执行，Collector 和 Organizer 出现越权行为（Write / Edit / Bash）。
2. **分析字段遗漏**：整理 Agent 首次写入遗漏 score / score_reason / highlights，分析产出与整理阶段的字段映射不够明确。

**下一步行动**：修复 P0（模型配置）后应重新执行完整测试，验证 subagent 权限隔离是否生效，并确认 P1 修复项（分析字段全量映射、content_path 规范化）是否解决。
