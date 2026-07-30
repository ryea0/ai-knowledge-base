# PRD: Pipeline Metrics Collection（工作流指标采集）

> 版本: v1.0 · 状态: Draft · 作者: John (PM) · 日期: 2026-07-30

---

## 1. Problem Statement

知识库 Pipeline 已在生产稳定运行（每日采集 ~20 条，经采集 → 分析 → 审核 → 整理/修订 → 保存），但**全链路不可观测**。当 pipeline 出问题时，运维和内容运营无法回答以下问题：

- 「昨晚的 pipeline 卡在哪一步？采集了 0 条还是审核没过？」
- 「review 平均几轮才能通过？是分析质量差还是审核标准太严？」
- 「哪个 Agent（collect / analyze / review / organize）最烧 token 和钱？」

现状：`cost_tracker` 和 `CostGuard` 只在工作流运行时存在于内存中，运行结束后落到 `knowledge/cost_report_*.json` 散文件，**无结构化存储、无查询能力、无时序对比**。`trace_id` 虽已贯穿日志，但日志只供人工 grep，没有面向业务方的可视化视图。

目标：在不改变现有工作流执行逻辑的前提下，为 pipeline 增加**结构化指标采集与查询 API**，支撑知识库健康度 Dashboard。

## 2. Users（谁看 Dashboard）

| 用户角色 | 核心诉求 | 频率 |
| -------- | -------- | ---- |
| **内容运营** | 知识库健康度：每日入库量、审核通过率、内容质量趋势 | 每日 1-2 次 |
| **Tech Lead / 运维** | Pipeline 运行状态：昨晚跑没跑、卡在哪、有没有报错 | 每日 + 出问题时 |
| **成本管理者** | LLM 成本：每天/每节点花了多少钱、预算消耗比 | 每周复盘 |

## 3. Must-have Metrics（MVP · 5 个）

以下指标均按**单次工作流执行（trace_id 粒度）**采集，可向上聚合为日/周维度：

| # | 指标 | 数据来源 | 说明 |
| - | ---- | -------- | ---- |
| M1 | **Pipeline 运行结果** | `run_workflow()` 最终状态 | 每次执行的 trace_id、起止时间、终态（success / human_flagged / error）、各节点执行状态。回答「昨晚卡在哪」。 |
| M2 | **节点级耗时** | 各节点函数入口/出口打点 | collect / analyze / review / organize / save 每个节点的 wall-clock 耗时。回答「哪一步慢」。 |
| M3 | **审核通过率与轮次** | `review_node` 返回值 | 一次执行中 review 的 iteration 次数、是否最终 passed、是否走 human_flag。回答「review 几轮才过」。 |
| M4 | **各节点 LLM 成本** | `CostGuard.records`（已有） | 按节点分组的 prompt_tokens / completion_tokens / cost_yuan。回答「哪个 Agent 最烧钱」。当前 `CostGuard.get_report()` 已产出此数据，**MVP 只需持久化到 DB**。 |
| M5 | **采集→入库转化漏斗** | `sources` → `analyses` → `articles` → `saved_count` | 采集 N 条 → 分析后 M 条 → 过滤去重后 K 条 → 最终保存 K 条。回答「内容从采集到入库的损耗在哪」。 |

## 4. Nice-to-have

- **错误明细聚合**：按 node 维度统计 error 类型与频次（需结构化 errors 列表）。
- **审核维度评分趋势**：review_node 5 维度（summary_quality / technical_depth / relevance / originality / formatting）历史趋势，识别质量退化方向。
- **每节点 LLM 调用次数**（call_count），区分「重试导致的多次调用」与「正常调用」。
- **日均成本趋势图**与预算消耗比预警。
- **采集器维度拆分**：GitHub Trending vs Hacker News 各采集多少条、转化率差异。

## 5. Success Criteria

| 维度 | 验收标准 | 验证方式 |
| ---- | -------- | -------- |
| **可观测性** | Pipeline 执行后，可通过 API 查询最近 N 次执行的 M1-M5 指标 | 调用 `GET /api/metrics/runs` 返回结构化数据 |
| **低侵入** | 现有节点函数签名与图结构不改动，指标采集通过装饰器/回调注入 | `nodes.py` diff 仅增加 metrics 打点调用，无逻辑变更 |
| **数据持久化** | 指标写入 MySQL，可通过 trace_id 关联一次完整执行的全部指标 | 新增 `kb_pipeline_run` + `kb_node_metric` 表，符合 db-conventions §7.1 |
| **前端可用** | 内容运营在 Dashboard 页面看到「每日入库量、审核通过率、成本趋势」3 张卡片 | kb-web 新增 `/metrics` 路由页面，数据来自 metrics API |
| **不破坏现有流程** | metrics 采集失败不影响 pipeline 正常执行 | metrics 写入包裹在 try/except 中，异常仅记日志 |

## 6. Out of Scope

- **实时流式指标推送**（WebSocket / SSE）—— MVP 仅支持事后查询，不做实时推送。
- **告警系统**（预算超限自动飞书通知 / pipeline 失败自动报警）—— 属于后续迭代。
- **指标数据清理**（历史数据 TTL 自动归档）—— MVP 假设数据量可控，不做自动清理。
- **多 Pipeline 对比**（A/B 测试不同 prompt 或模型的指标对比）—— 当前只有单 pipeline。
- **自定义指标注册机制**—— MVP 指标列表固定，不支持运行时动态注册。
- **Prometheus / Grafana 接入**—— MVP 用 MySQL + 内置 Dashboard，不引入独立监控系统。

---

## 附录：技术方向提示（非 PRD 约束，供 Architect 参考）

- 指标采集：在 `run_workflow()` 包装层统一采集，或用装饰器包裹各 node 函数。
- 数据模型：`kb_pipeline_run`（一次执行 = 一行）+ `kb_node_metric`（每节点一行，FK 到 run）。两张表均为纯追加日志表（仅需 `id` + `created_at`，符合 db-conventions §7.1 例外）。
- 复用现有 `CostGuard.get_report()` 的 `by_node` 结构，直接序列化写入 `kb_node_metric.cost_data` JSON 列。
- `trace_id` 作为关联键贯穿 run 表和 node 表，同时复用 `src/common/trace.py` 现有基础设施。
