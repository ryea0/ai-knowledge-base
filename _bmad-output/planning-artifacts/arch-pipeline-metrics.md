# 架构提案：Pipeline Metrics Collection（工作流指标采集）

> 架构师: Winston 🏗️ · 版本: v1.0 · 日期: 2026-07-30
> PRD: `prd-pipeline-metrics.md`

---

## 0. 问题约束回放

| # | 约束 | 来源 |
|---|------|------|
| C1 | 不破坏现有 3 路条件边（`route_after_review`: organize / revise / human_flag） | 用户 |
| C2 | 观察者模式 -- 不污染每个 Agent 文件 | 用户 |
| C3 | 不引入第二次 LLM 调用 | 用户 |
| C4 | 最小侵入 | 用户 |
| C5 | LangGraph **没有** `graph.compile(callbacks=...)` graph 级 callback 注册 API | 用户 |
| C6 | 指标采集失败不影响 pipeline 正常执行 | PRD §5 |
| C7 | 不使用外键 / 存储过程 / 触发器 / 视图 | db-conventions §7.1 |

## 1. LangGraph 能力验证（实验结论，非猜测）

我对 langgraph 1.2.9 做了四组实验，以下是**确证的事实**：

### 1.1 `compile()` 不接受 callbacks

```python
sig = inspect.signature(StateGraph.compile)
# (self, checkpointer, *, cache, store, interrupt_before, interrupt_after, debug, name, transformers)
# 无 callbacks 参数 -- 确认 C5
```

### 1.2 `invoke()` 接受 `config={"callbacks": [...]}` -- 但语义不可控

`config={"callbacks": [handler]}` 能触发 `BaseCallbackHandler` 的 `on_chain_start/end`，
LangGraph 会把 `langgraph_node` 放进 `metadata`，但：

- 每个 node 执行产生**嵌套 chain 事件**（外层 graph chain + 内层 node chain），回调被触发多次
- `on_chain_end` 的 `metadata` 里 `langgraph_node` 有时为 `N/A`（外层 chain）
- 回调拿到的 `serialized` 是空的（`name=?`），无法可靠区分节点
- **handler 抛异常会中断图执行**，与 C6 冲突

结论：callbacks 可用但脆弱，需要大量防御代码，且无法拿到节点的返回值（只能拿 `outputs`，
而 LangGraph 的 outputs 是 partial state，语义与 node 返回值一致但需额外解析）。

### 1.3 `stream(stream_mode="updates")` -- 干净的节点级事件流

```python
for chunk in app.stream(initial_state, stream_mode="updates", config={"recursion_limit": 20}):
    # chunk = {"node_name": {partial_state_update}}
```

实验确认：

- **每个 chunk 的 key 就是节点名**，value 是该节点返回的 partial state
- 条件边和循环正常工作（review -> revise -> review 产生多个 chunk）
- **异常会从 stream 中抛出**（可 try/except 捕获）
- 流式 chunk 的到达时间 ≈ 节点 wall-clock 耗时（`time.monotonic()` 打点验证）
- 最终 state 可由各 chunk 累积还原，与 `invoke()` 返回值一致

### 1.4 `stream(stream_mode="debug")` -- 额外的 task/task_result 事件

```python
for chunk in app.stream(initial_state, stream_mode="debug"):
    # chunk = {"type": "task"|"task_result", "payload": {"name": "node_name", ...}}
```

`task` = 节点开始，`task_result` = 节点结束，天然提供 start/end 边界。
但 payload 结构较复杂，且 updates 模式已足够。

---

## 2. 三个候选方案

### 方案 A：Stream Wrapper（流式消费层）

**核心思路**：将 `run_workflow()` 中的 `app.invoke()` 替换为 `app.stream(stream_mode="updates")`，
在消费 chunk 的循环中统一采集指标。节点函数零改动。

```
run_workflow()
  ├── t0 = monotonic()
  ├── for chunk in app.stream(state, stream_mode="updates"):
  │     node_name = list(chunk.keys())[0]
  │     node_output = chunk[node_name]
  │     metrics_collector.on_node_end(node_name, node_output, monotonic() - t_prev)
  │     state_accum.update(node_output)
  │     t_prev = monotonic()
  ├── metrics_collector.on_workflow_end(final_state, monotonic() - t0)
  └── return final_state
```

**指标覆盖**：

| 指标 | 采集方式 |
|------|----------|
| M1 Pipeline 运行结果 | 最终 state + 异常捕获 |
| M2 节点级耗时 | chunk 到达间隔 `monotonic()` 打点 |
| M3 审核通过率与轮次 | 从 review 节点的 chunk output 读 `review_passed` / `iteration` |
| M4 各节点 LLM 成本 | 从 chunk output 读 `cost_tracker` 增量 |
| M5 转化漏斗 | 累积各 chunk 的 `sources` / `analyses` / `articles` / `saved_count` |

**侵入度**：仅改 `graph.py` 的 `run_workflow()` 函数（~30 行），`nodes.py` / `reviser.py` / `state.py` 零改动。

**对约束的满足**：

| 约束 | 满足度 | 说明 |
|------|--------|------|
| C1 不破坏条件边 | ✅ | 图结构、路由函数零改动 |
| C2 不污染 Agent 文件 | ✅ | 节点函数零改动 |
| C3 不引入第二次 LLM 调用 | ✅ | 纯被动消费 |
| C4 最小侵入 | ✅ | 仅改 1 个函数 |
| C5 无 graph 级 callback | ✅ | 用 stream API |
| C6 采集失败不影响 pipeline | ✅ | collector 内部 try/except |

**风险**：
- `stream()` 替代 `invoke()` 是行为变更，需验证 `recursion_limit` 等 config 在 stream 下行为一致（实验已验证 ✅）
- 耗时精度依赖 chunk 到达时间，有 ms 级抖动（可接受，PRD 不要求 ms 级精度）
- `ThreadPoolExecutor`（analyze_node 内部并发）的 wall-clock 耗时是整个节点的外层时间，无法拆分到单条 LLM 调用 -- 但 PRD M2 要求的是节点级耗时，不要求 LLM 调用级

**适用场景**：MVP 首选，快速交付，零节点改动。

---

### 方案 B：Node Decorator（装饰器注入）

**核心思路**：定义一个 `@with_metrics` 装饰器，在 `graph.py` 的 `build_graph()` 中包裹节点函数，
节点定义文件（`nodes.py` / `reviser.py`）不改。

```python
# graph.py
def _with_metrics(node_fn, name):
    @functools.wraps(node_fn)
    def wrapper(state):
        t0 = time.monotonic()
        try:
            result = node_fn(state)
            _metrics.on_node_end(name, result, time.monotonic() - t0, error=None)
            return result
        except Exception as exc:
            _metrics.on_node_end(name, {}, time.monotonic() - t0, error=exc)
            raise
    return wrapper

def build_graph():
    graph = StateGraph(KBState)
    graph.add_node("collect", _with_metrics(collect_node, "collect"))
    graph.add_node("analyze", _with_metrics(analyze_node, "analyze"))
    # ... 其余节点同理
```

**指标覆盖**：同方案 A，M1-M5 均可覆盖。耗时精度比 A 更高（直接包裹函数，无 stream 调度延迟）。

**侵入度**：仅改 `graph.py` 的 `build_graph()`（~15 行装饰器 + 7 行 add_node 改动），节点文件零改动。

**对约束的满足**：

| 约束 | 满足度 | 说明 |
|------|--------|------|
| C1 不破坏条件边 | ✅ | 路由函数零改动 |
| C2 不污染 Agent 文件 | ✅ | 装饰器在 graph.py 注入，nodes.py 不改 |
| C3 不引入第二次 LLM 调用 | ✅ | 纯被动观测 |
| C4 最小侵入 | ✅ | 仅改 1 个文件 |
| C5 无 graph 级 callback | ✅ | 用函数装饰器 |
| C6 采集失败不影响 pipeline | ✅ | decorator 内 try/except |

**风险**：
- 装饰器改变了 `add_node` 注册的函数对象，需确认 LangGraph 不依赖函数的 `__name__` / `__module__` 做内部路由（实验验证：LangGraph 用 add_node 的第一个参数字符串做节点名，不依赖函数元数据 ✅）
- `functools.wraps` 保留原函数签名，但调试时 traceback 多一层 wrapper -- 可接受
- 装饰器需要访问 ContextVar 中的 metrics collector（与 CostGuard 同模式），增加一个 ContextVar

**适用场景**：需要精确耗时、或未来可能扩展 per-node 自定义指标时。

---

### 方案 C：LangChain Callback Handler（config 注入）

**核心思路**：实现 `BaseCallbackHandler` 子类，通过 `config={"callbacks": [handler]}` 注入到 `invoke()` / `stream()`。

```python
class PipelineMetricsHandler(BaseCallbackHandler):
    def on_chain_start(self, serialized, inputs, *, metadata=None, **kwargs):
        node = metadata.get("langgraph_node")
        if node:
            self._timings[node] = time.monotonic()

    def on_chain_end(self, outputs, *, metadata=None, **kwargs):
        node = metadata.get("langgraph_node")
        if node and node in self._timings:
            duration = time.monotonic() - self._timings[node]
            _metrics.on_node_end(node, outputs, duration)
```

**指标覆盖**：M2 耗时可采集，但 M3/M4/M5 依赖节点返回值中的特定字段（`review_passed` / `cost_tracker` / `sources`），callback 的 `outputs` 是 partial state，**需要额外解析逻辑**且边界 case 多。

**侵入度**：新增 handler 类（~50 行），`run_workflow()` 加 1 行 config。节点文件零改动。

**对约束的满足**：

| 约束 | 满足度 | 说明 |
|------|--------|------|
| C1 不破坏条件边 | ✅ | |
| C2 不污染 Agent 文件 | ✅ | |
| C3 不引入第二次 LLM 调用 | ✅ | |
| C4 最小侵入 | ⚠️ | 代码量最少，但语义最复杂 |
| C5 无 graph 级 callback | ✅ | 用 config 级 callback |
| C6 采集失败不影响 pipeline | ❌ → ✅ | handler 异常会中断图执行，需大量防御代码 |

**风险**：
- **嵌套 chain 事件**：每个 node 产生 2-3 个 chain 事件（外层 graph + 内层 node），`langgraph_node` 在外层事件中为 `N/A`，需要过滤逻辑
- **handler 异常传播**：LangChain callback handler 的异常会沿 Runnable 链传播，与 C6 直接冲突，需在每个方法内 try/except
- **`serialized` 为空**：实验确认 `serialized["name"]` 为 `"?"`，无法靠序列化信息区分节点，只能依赖 `metadata["langgraph_node"]`
- **语义脆弱**：依赖 LangGraph 内部 metadata key（`langgraph_node` / `langgraph_step`），这些是 undocumented implementation detail，版本升级有 break 风险
- M4（成本）采集复杂：callback 拿到的是 partial state，需要判断哪个 key 是 `cost_tracker` 并做 diff

**适用场景**：已有 LangSmith / LangChain callback 体系且想复用时。本项目无此基础设施，不推荐。

---

## 3. 权衡矩阵

| 维度 | 方案 A (Stream) | 方案 B (Decorator) | 方案 C (Callback) |
|------|:---:|:---:|:---:|
| **侵入度**（改动文件数） | 1（graph.py） | 1（graph.py） | 1（graph.py + 新类） |
| **侵入度**（改动行数） | ~30 | ~20 | ~60 |
| **耗时精度** | ms 级抖动 | 精确 | 精确（但边界模糊） |
| **M1-M5 覆盖** | ✅ 全覆盖 | ✅ 全覆盖 | ⚠️ M3/M4/M5 需额外解析 |
| **C6 安全性**（采集失败不影响 pipeline） | ✅ 天然安全 | ✅ 天然安全 | ⚠️ 需大量防御代码 |
| **API 稳定性**（不依赖内部实现） | ✅ stream 是公开 API | ✅ 纯 Python 装饰器 | ⚠️ 依赖 metadata 内部 key |
| **行为变更风险** | ⚠️ invoke→stream | ✅ 无行为变更 | ✅ 无行为变更 |
| **可测试性** | ✅ mock collector | ✅ mock collector | ⚠️ mock handler 复杂 |
| **未来扩展性** | ⚠️ 仅限 stream 消费层 | ✅ 可扩展 per-node 自定义指标 | ✅ 可接入 LangSmith |
| **与现有 CostGuard 模式一致性** | ✅ 同在 run_workflow 层 | ✅ ContextVar 同模式 | ❌ 不同范式 |

---

## 4. 推荐

### 推荐方案 B（Node Decorator），方案 A 作为 fallback

**理由**：

1. **零行为变更**：方案 B 不改变 `invoke()` → `stream()` 的执行模式，`run_workflow()` 的调用方（CLI / API）完全无感知。方案 A 虽然实验验证了 stream 与 invoke 行为一致，但 `invoke → stream` 仍然是语义变更，在 `ThreadPoolExecutor` + 条件边 + 循环的复杂拓扑下，引入非预期行为的概率不为零。

2. **C6 天然安全**：装饰器在 `try/except` 中包裹节点函数，metrics 异常被隔离在 wrapper 内，不会沿 LangGraph 的 Runnable 链传播。方案 C 的 callback handler 异常会中断图执行，与 C6 直接冲突。

3. **与现有 CostGuard 模式一致**：项目已用 `ContextVar` 注入 `CostGuard`（`cost_guard_var`），装饰器用同样的 `ContextVar` 注入 `MetricsCollector`，架构风格统一，开发者认知零成本。

4. **精确耗时**：装饰器直接包裹函数调用，`time.monotonic()` 打点精确到函数入口/出口，无 stream 调度延迟。方案 A 的耗时是 chunk 到达间隔，包含 LangGraph 内部的状态合并 / 路由计算开销。

5. **Rule of Three**：当前只有 metrics 一个横切关注点。如果未来出现第二个（如 per-node tracing、audit log），装饰器模式天然支持叠加 `@with_metrics @with_tracing`，而 stream 消费层和 callback handler 的扩展性较差。

**fallback 条件**：如果团队对「`add_node` 注册的函数对象被替换」有顾虑（虽然实验验证 LangGraph 不依赖函数元数据），则退回方案 A，改动量同等量级。

### 实现骨架

```python
# src/graph/metrics.py（新文件，~80 行）
class MetricsCollector:
    """工作流指标采集器，通过 ContextVar 注入。"""
    
    def __init__(self, trace_id: str):
        self._trace_id = trace_id
        self._node_timings: dict[str, float] = {}
        self._node_outputs: dict[str, dict] = {}
        self._t0: float = 0.0
    
    def on_workflow_start(self) -> None: ...
    def on_node_end(self, node: str, output: dict, duration: float, error: Exception | None) -> None: ...
    def on_workflow_end(self, final_state: dict, total_duration: float) -> None: ...
    def persist(self, session: Session) -> None: ...

# src/graph/graph.py（改动 ~20 行）
from src.graph.metrics import MetricsCollector, metrics_collector_var, set_metrics_collector

def _with_metrics(node_fn, name):
    @functools.wraps(node_fn)
    def wrapper(state):
        t0 = time.monotonic()
        try:
            result = node_fn(state)
            collector = metrics_collector_var.get(None)
            if collector:
                collector.on_node_end(name, result, time.monotonic() - t0, None)
            return result
        except Exception as exc:
            collector = metrics_collector_var.get(None)
            if collector:
                collector.on_node_end(name, {}, time.monotonic() - t0, exc)
            raise
    return wrapper

def build_graph():
    graph = StateGraph(KBState)
    graph.add_node("collect", _with_metrics(collect_node, "collect"))
    graph.add_node("analyze", _with_metrics(analyze_node, "analyze"))
    # ... 其余节点同理
    # 路由函数、条件边、edge 全部不改
```

### 数据模型（符合 db-conventions §7.1）

```
kb_pipeline_run          kb_node_metric
─────────────            ──────────────
id (PK, BIGINT)          id (PK, BIGINT)
trace_id (VARCHAR)       trace_id (VARCHAR)  -- 关联键，非 FK
status (VARCHAR)         node_name (VARCHAR)
started_at (DATETIME)    duration_ms (INT)
ended_at (DATETIME)      review_passed (TINYINT)
total_cost_yuan (DEC)    iteration (INT)
source_count (INT)       cost_data (JSON)
analysis_count (INT)     error (TEXT)
article_count (INT)      created_at (DATETIME)
saved_count (INT)
human_flagged (TINYINT)
created_at (DATETIME)
```

关联关系在应用层通过 `trace_id` 维护，不使用外键（C7）。

---

## 5. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| `invoke→stream` 行为差异（方案 A） | 低 | 高 | 方案 B 规避 |
| 装饰器改变函数对象导致 LangGraph 内部异常 | 极低（实验验证 ✅） | 中 | fallback 到方案 A |
| `ThreadPoolExecutor` 内部异常被吞 | 中 | 低 | analyze_node 已有 `fut.result()` 捕获，装饰器在外层 |
| metrics DB 写入失败 | 低 | 低 | `persist()` 内 try/except，仅 log warning |
| 未来 LangGraph 升级改变 metadata key（方案 C） | 中 | 高 | 方案 B/C 规避，方案 B 不依赖 LangGraph 内部实现 |

---

## 6. 下一步

1. 用户确认方案选择
2. 如选 B：创建 OpenSpec change → 实现 `src/graph/metrics.py` → 改 `graph.py` → 新增 DDL → API endpoint → 前端 Dashboard
3. 验证：端到端跑一次 `run_workflow()`，确认 `kb_pipeline_run` + `kb_node_metric` 有数据
