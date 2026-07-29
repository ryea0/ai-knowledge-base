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

### D3: 新增适配层 `chat_for_analysis` 解决 `LlmCallError` per-error_type 细分问题

**问题**: `LlmCallError` 使用 `error_type` **实例属性**（`LlmErrorType` 枚举值）区分错误类型，
而非子类层级。`with_retry` 的 `retry_on` 接收 `type[Exception]`，匹配基于 `isinstance`，
无法区分 "TIMEOUT 的 `LlmCallError` 重试 / AUTH_FAILED 的 `LlmCallError` 不重试"。

**方案**: 新增 `src/pipeline/llm_call_adapter.py`，定义适配层函数 `chat_for_analysis`：

1. 内部调用 `chat_completion`（**无重试版**），而非 `chat_completion_with_retry`
2. 捕获 `LlmCallError`，按 `error_type` 分类:
   - `TIMEOUT` / `RATE_LIMITED` / `NETWORK` / `SERVER_ERROR` -> 原样抛出（匹配 `retry_on=(LlmCallError,)`）
   - `AUTH_FAILED` / `CLIENT_ERROR` / `UNKNOWN` -> 转换为 `NonRetryableLlmError`（继承 `Exception`，
     不匹配 `retry_on` 中的 `LlmCallError`）
3. `BudgetExceededError` 原样穿透

`NonRetryableLlmError` 定义在 `src/llm/retry_decorator.py`，继承 `Exception`（非 `LlmCallError`），
携带 `original: LlmCallError` 属性供日志和调试。

**替代方案 A**: 给装饰器增加 `predicate` 参数支持属性级匹配 -- 增加装饰器复杂度，
且 predicate 函数无法静态类型检查。

**替代方案 B**: 将 `LlmCallError` 重构为子类层级（`LlmTimeoutError` / `LlmAuthError` 等）--
改动面过大，影响 `RetryPolicyFactory` 和所有 `except LlmCallError` 的调用点，超出本 change scope。

**替代方案 C**: 不做细分，`LlmCallError` 整体重试或不重试 -- 退化为现有 `chat_completion_with_retry`
的能力，AUTH_FAILED 也会被重试，浪费资源。

### D4: 适配层调用 `chat_completion` 而非 `chat_completion_with_retry`

**理由**: 避免双重重试。`chat_completion` 是无重试的单次调用，
`chat_completion_with_retry` 内部已有基于 `RetryPolicyFactory` 的重试逻辑。
如果适配层调用 `chat_completion_with_retry`，外层 `with_retry` 再重试，
总调用次数 = 外层 max_attempts × 内层 max_attempts（最多 9 次），浪费资源且行为不可预测。

调用链: `analyze()` -> `@with_retry` 装饰的 `chat_for_analysis()` -> `chat_completion()` -> `litellm.completion()`

- `chat_completion` 每次只调用 1 次 `litellm.completion`
- `with_retry` 负责全部重试逻辑
- 总调用次数 = 外层 `max_attempts`

**替代方案**: 适配层调用 `chat_completion_with_retry` 并声明 "内层重试已耗尽，外层捕获的是最终异常" --
但内层重试耗尽后抛出的仍是 `LlmCallError`，外层会再次触发内层的完整重试周期，
总调用次数仍会放大，且内层的退避参数与外层不同步，行为难以预测。

### D5: 时间窗口判定在调用方，不在装饰器内部

**理由**: 装饰器应是纯粹的"重试执行器"，不承担业务策略。时间窗口是业务维度（白天/夜里），
不同调用点可能有不同的时间窗口定义。将判定逻辑放在调用方（如 analyzer 的 `_get_retry_params`），
装饰器只接收最终的 `max_attempts` 数值，职责清晰。

**替代方案**: 装饰器内置 `time_window` 参数 -- 会导致装饰器耦合业务时间概念，
且不同时区/不同业务的时间窗口定义不同，参数化会爆炸。

`_get_retry_params` 接受可选的 `now: datetime.datetime` 参数，便于测试注入时间，
避免直接 `datetime.datetime.now()` 导致的不可测试问题。

### D6: jitter 默认开启

**理由**: 多个 pipeline 实例同时重试时，固定退避会导致惊群效应。jitter 抖动到 50%-100% 区间
（`delay * (0.5 + random() * 0.5)`），保留退避的递增趋势同时打散并发重试。

**替代方案**: 默认关闭 -- 单实例运行时不需要 jitter，但默认开启更安全，且对单实例几乎无成本。

**测试影响**: jitter=True 时日志中的等待秒数为实际值（含抖动），非理论值。
测试通过 `jitter=False` 断言精确值，或固定 `random.seed` 断言范围。

### D7: `no_retry_on` 优先于 `retry_on`

**理由**: 安全默认。如果某异常同时匹配两个列表（通常是配置错误），不重试比浪费钱重试更安全。

### D8: `BudgetExceededError` 传播与 `analyze()` 降级

**问题**: `BudgetExceededError` 由 `chat_completion` 内 `BudgetGuard.check_pre_call` 抛出，
继承 `Exception`，不是 `LlmCallError` 或 `RuntimeError` 的子类。
现有 `analyze():91` 的 `except (LlmCallError, RuntimeError)` 无法捕获它，
会导致 `BudgetExceededError` 直接传播终止 pipeline。

**方案**: `analyze()` 的 `except` 子句增加 `BudgetExceededError`，将其降级为规则分析。
预算耗尽时停止 LLM 调用是预期行为，降级而非崩溃。

调用链: `chat_completion` -> `BudgetGuard.check_pre_call` -> `BudgetExceededError`
-> `chat_for_analysis`（不捕获，原样穿透） -> `with_retry`（`no_retry_on` 匹配，立即抛出）
-> `analyze()`（`except` 捕获，降级为 `_fallback_analyze`）

### D9: OpenAI SDK 原生异常不进入装饰器异常分类表

**事实**: `chat_completion()` 的 `except Exception`（`src/llm/client.py:313`）会捕获
`litellm.completion()` 抛出的**所有**异常，经 `_classify_exception()` 按类名映射为
`LlmCallError(error_type=...)` 后抛出。OpenAI SDK 的 `APITimeoutError` / `APIConnectionError` /
`RateLimitError` / `APIStatusError` / `AuthenticationError` / `InternalServerError` 等
全部被包装为 `LlmCallError`，**不会以原始类型到达 `with_retry` 装饰器**。

**影响**: 装饰器的 `retry_on` / `no_retry_on` 不需要也不应该声明 `openai.*` 异常类型。
spec 异常分类表中只列出 `LlmCallError`（包装后）和 `httpx.*`（HTTP 采集器直接使用，不经 `chat_completion` 包装）。

**绕过包装的异常**:
- `BudgetExceededError` -- 由 `BudgetGuard.check_pre_call`（try/except **之前**，line 308）抛出
- `build_auth_context` 的配置/解密错误 -- 同样在 try/except 之前（line 266）

这些异常以原始类型到达装饰器，通过 `no_retry_on` 或"未声明异常默认不重试"规则处理。

**替代方案**: 在 `retry_on` 中同时声明 `openai.APITimeoutError` 等类型 -- 无意义且误导，
因为这些异常永远不会以原始类型到达装饰器。声明它们会给读者造成"装饰器直接处理 OpenAI 异常"的错误印象。

## Risks / Trade-offs

- **[适配层维护成本]** `chat_for_analysis` 需要手动维护 error_type 到 "重试/不重试" 的映射，
  与 `RetryPolicyFactory` 的策略表有重复。
  **缓解**: spec 中的异常分类表是权威来源，适配层直接引用常量元组减少重复。
  未来可考虑让 `RetryPolicyFactory` 提供查询接口，适配层调用而非硬编码。

- **[NonRetryableLlmError 丢失类型信息]** 转换后的 `NonRetryableLlmError` 不再是 `LlmCallError`，
  上层 `except LlmCallError` 无法捕获它。
  **缓解**: `analyze()` 的 `except` 同时捕获 `NonRetryableLlmError`（或在适配层上层处理）。
  `NonRetryableLlmError.original` 保留原始 `LlmCallError` 供日志和调试。

- **[同步限制]** 装饰器不支持 `async def`。
  **缓解**: 当前 pipeline 全同步。若未来引入异步（如 FastAPI 端点直接调用），
  新增 `with_retry_async` 变体，接口一致。
