## Context

现有 `src/llm/client.py` 已有 `RetryStrategy` + `RetryPolicyFactory` + `chat_completion_with_retry` 体系，
按 `LlmErrorType` 枚举自动分派重试策略。该体系与 `LlmCallError` 强耦合，无法覆盖非 LLM 场景
（如 HTTP 采集器 `httpx.TimeoutException`、内容解析 `json.JSONDecodeError`）。

详见 proposal.md - Why 了解动机，§9.5 llm-provider.md 了解现有重试策略表。

## Goals / Non-Goals

**Goals:**

- `with_retry` 装饰器作为独立工具函数，可装饰任意同步函数
- 通过参数显式声明 `retry_on` / `no_retry_on`，使每个调用点的重试边界一眼可查
- 与现有 `RetryPolicyFactory` 体系共存，不修改其行为
- spec 定义异常分类表和参数约束，AI 实现时有明确边界可循

**Non-Goals:**

- 不替换 `chat_completion_with_retry`（现有调用点不改动）
- 不实现异步函数装饰（`async def`）-- 当前 pipeline 全同步，未来需要时再加
- 不实现装饰器内部的时间窗口判定（调用方查表后传参）
- 不实现重试上下文传递（如 trace_id 贯穿重试链）-- 由现有 `src.common.trace` 独立管理

## Decisions

### D1: 装饰器放在 `src/llm/retry_decorator.py` 而非 `src/utils/`

**理由**: 装饰器的主要使用场景是 LLM 调用链（analyzer / client），异常分类表中的异常
大多来自 `src.llm.client` 和 `src.llm.budget`。放在 `src/llm/` 下可使导入路径更短，
且与 §9.5 重试策略文档同目录。

**替代方案**: 放 `src/utils/retry.py` -- 更通用，但当前唯一的调用点是 LLM 场景，
过早抽象为通用工具会导致异常分类表无处归属。

### D2: `retry_on` / `no_retry_on` 用 `tuple[type[Exception], ...]` 而非字符串

**理由**: 类型安全，IDE 自动补全，mypy 可检查。字符串方式（如 `retry_on=("Timeout",)`）
无法静态检查，且与 `LlmErrorType` 枚举值容易混淆。

**替代方案**: 用 `LlmErrorType` 枚举值 -- 但装饰器要支持非 LLM 异常（`httpx.TimeoutException`、
`json.JSONDecodeError`），枚举无法覆盖。

### D3: 时间窗口判定在调用方，不在装饰器内部

**理由**: 装饰器应是纯粹的"重试执行器"，不承担业务策略。时间窗口是业务维度（白天/夜里），
不同调用点可能有不同的时间窗口定义。将判定逻辑放在调用方（如 analyzer 的 `_get_retry_params`），
装饰器只接收最终的 `max_attempts` 数值，职责清晰。

**替代方案**: 装饰器内置 `time_window` 参数 -- 会导致装饰器耦合业务时间概念，
且不同时区/不同业务的时间窗口定义不同，参数化会爆炸。

### D4: jitter 默认开启

**理由**: 多个 pipeline 实例同时重试时，固定退避会导致惊群效应。jitter 抖动到 50%-100% 区间
（`delay * (0.5 + random() * 0.5)`），保留退避的递增趋势同时打散并发重试。

**替代方案**: 默认关闭 -- 单实例运行时不需要 jitter，但默认开启更安全，且对单实例几乎无成本。

### D5: `no_retry_on` 优先于 `retry_on`

**理由**: 安全默认。如果某异常同时出现在两个列表中（通常是配置错误），不重试比浪费钱重试更安全。
装饰器初始化时可以 log warning 提示重叠，但不阻止配置。

## Risks / Trade-offs

- **[双重重试风险]** `with_retry` 装饰的函数内部调用 `chat_completion_with_retry` 时，
  内层已重试 3 次，外层再重试 3 次 = 最多 9 次调用。
  **缓解**: spec 明确声明此行为；analyzer 场景下外层只捕获降级后的异常，
  内层 `LlmCallError` 被 `analyzer.analyze():91` 的 `except` 捕获后降级，
  不会传播到外层装饰器。

- **[异常列表维护成本]** 每个调用点要显式声明异常列表，有重复。
  **缓解**: spec 中的异常分类表是权威来源，调用点直接引用。可后续提取常量元组
  （如 `RETRYABLE_HTTP_EXCEPTIONS`、`NON_RETRYABLE_CONTENT_EXCEPTIONS`）减少重复。

- **[同步限制]** 装饰器不支持 `async def`。
  **缓解**: 当前 pipeline 全同步。若未来引入异步（如 FastAPI 端点直接调用），
  新增 `with_retry_async` 变体，接口一致。
