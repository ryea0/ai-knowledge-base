# 链路追踪（traceId）规范

> 本文件从 AGENTS.md §10 拆分而来，章节编号保持不变。
> 实现见 `src/common/trace.py`、`src/config/logging_config.py`、`src/common/middleware.py`。

---

## §10.1 设计目标

调用链路「采集 -> 分析 -> 整理 -> 分发」中的所有日志须可通过统一 `trace_id` 关联到同一次工作流执行。在多线程、多请求并发场景下，通过 `trace_id` 快速定位一次完整链路的全部日志。

## §10.2 traceId 格式

| 属性 | 规则 |
| ---- | ---- |
| 格式 | UUIDv4 前 8 位十六进制（如 `a1b2c3d4`），短小可读 |
| 唯一性 | 每次工作流执行 / 每个 HTTP 请求生成一个 |
| 大小写 | 全小写 |
| 存储 | `str` 类型，不加密 |

## §10.3 生成与传递规则

**生成点（须在链路入口生成）：**

| 入口 | 生成方式 | 实现位置 | 状态 |
| ---- | -------- | -------- | ---- |
| CLI 执行 | `main()` 启动时生成，注入 `WorkflowState` | `src/main.py` | ✅ 已实现（`setup_logging` + `generate_trace_id`） |
| LangGraph 工作流 | `build_workflow()` 执行前生成，写入 `WorkflowState["trace_id"]` | `src/graph/workflow.py` | ⬜ 待实现 |
| FastAPI 请求 | 从请求头 `X-Request-Id` 提取；未携带时自动生成；响应头回传 `X-Request-Id` | `src/common/middleware.py` | ✅ 已实现（`RequestLogMiddleware`） |

**传递规则：**

1. **工作流链路**：`trace_id` 存入 `WorkflowState["trace_id"]`，各节点函数从 `state` 中读取并传入日志。
2. **跨函数传递**：工作流节点调用的业务函数（采集器 / 分析器 / 整理器 / 分发器）须接收 `trace_id: str` 参数并写入日志。
3. **LLM 调用链**：`chat_completion()` / `record_success()` / `record_failure()` 等函数须接收 `trace_id` 参数，将 LLM 调用日志关联到触发它的工作流。
4. **禁止跨链路复用**：每次工作流执行 / 每个请求生成新的 `trace_id`，禁止复用上一次执行的 ID。

## §10.4 日志注入规则

采用 `contextvars.ContextVar` + `logging.Filter` 实现自动注入，业务代码**无需**手动在每条日志中拼接 `trace_id`（实现见 `src/common/trace.py`）：

1. **ContextVar 声明**：
   ```python
   trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")
   ```

2. **设置 traceId**：链路入口设置 `trace_id_var.set(generated_id)`，后续同线程 / 同协程内的所有日志自动携带。

3. **Logging Filter**：注册全局 `logging.Filter`，从 `trace_id_var` 读取当前值并注入 `LogRecord`。

4. **日志格式**：格式字符串须包含 `%(trace_id)s`：
   ```
   %(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s
   ```

5. **多线程传递**：`ThreadPoolExecutor` 提交任务时，须在子线程入口调用 `trace_id_var.set(parent_trace_id)`，确保子线程日志关联到同一链路。推荐使用 `contextvars.copy_context()` 传递。

## §10.5 WorkflowState 字段扩展

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

## §10.6 节点日志规范

工作流各节点函数（`src/graph/nodes.py`）的日志**须**携带 `trace_id`：

```python
def collect_node(state: WorkflowState) -> WorkflowState:
    trace_id = state.get("trace_id", "-")
    trace_id_var.set(trace_id)
    logger.info("采集节点启动，候选条目数: %d", len(state.get("candidates", [])))
    # trace_id 已通过 Filter 自动注入日志，无需手动拼接
    ...
```

## §10.7 实现清单

| 序号 | 文件 | 改动内容 | 状态 |
| ---- | ---- | -------- | ---- |
| T-01 | `src/common/trace.py` | `trace_id_var` ContextVar + `TraceIdFilter` + `generate_trace_id()` | ✅ 已实现 |
| T-02 | `src/main.py` | `setup_logging(log_level=...)` 替换 `basicConfig` | ✅ 已实现 |
| T-03 | `src/graph/state.py` | `WorkflowState` 增加 `trace_id: str` 字段 | ⬜ 待实现 |
| T-04 | `src/graph/workflow.py` | `build_workflow()` 执行前生成 traceId 写入初始 state | ⬜ 待实现 |
| T-05 | `src/graph/nodes.py` | 各节点函数入口 `trace_id_var.set(state["trace_id"])` | ⬜ 待实现 |
| T-06 | `src/llm/client.py` | `chat_completion()` 增加 `trace_id` 参数，日志携带 | ⬜ 待实现 |
| T-07 | `src/llm/health.py` | `record_success/record_failure/check_provider_health` 增加 `trace_id` 参数；`last_error` 写入前调用 `_sanitize_error()` | ⬜ 待实现 |
| T-08 | `src/llm/service.py` | except 块补充 `exc_info=True`；错误日志调用 `_sanitize_error()` | ⬜ 待实现 |
| T-09 | `src/utils/github_api.py` | 3 处 except 块补充 `exc_info=True` | ⬜ 待实现 |
| T-10 | `src/mcp_knowledge_server.py` | 2 处 except 块补充 `exc_info=True` | ⬜ 待实现 |
