## Why

当前重试逻辑硬编码在 `chat_completion_with_retry` 内部，与 `RetryPolicyFactory` + `LlmCallError` 强耦合。
半年后回看：timeout 到底重试几次？base_delay 多少？为什么不重试 JSONDecodeError？
这些边界散落在代码里，没有 spec 约束，AI 每次都要重猜。

更深的问题：现有重试只覆盖 LLM 调用层（`LlmCallError`），不覆盖内容解析层
（`JSONDecodeError` / `KeyError`）。两类异常的「该不该重试」语义完全不同--
瞬时故障重试大概率能好，内容问题重试只会浪费钱--但当前没有统一的地方定义这条边界。

此外，`LlmCallError` 使用 `error_type` 实例属性区分错误类型（而非子类层级），
`with_retry` 的 `type[Exception]` 匹配无法直接按 error_type 细分。
需要引入适配层将不可重试的 `LlmCallError` 转换为独立异常类型，才能实现 per-error_type 的重试/不重试区分。

## What Changes

- 新增 `with_retry` 装饰器（`src/llm/retry_decorator.py`），通过参数声明
  `retry_on` / `no_retry_on` / `max_attempts` / `base_delay` / `backoff_factor` / `max_delay`
- 新增 `NonRetryableLlmError` 异常类（`src/llm/retry_decorator.py`），继承 `Exception`，
  携带原始 `LlmCallError` 引用，用于适配层转换不可重试的 LLM 错误
- 新增适配层 `chat_for_analysis`（`src/pipeline/llm_call_adapter.py`），内部调用
  `chat_completion`（无重试版），按 `error_type` 将不可重试的 `LlmCallError` 转换为 `NonRetryableLlmError`
- 装饰器独立于现有 `RetryPolicyFactory` 体系，可作用于任意函数（LLM 调用、HTTP 采集、内容解析等）
- 现有 `chat_completion_with_retry` 保持不变，装饰器作为新调用点的可选增强
- 定义异常分类表（瞬时故障 vs 内容问题），作为 spec 的核心契约
- 定义时间窗口策略表（白天/夜里不同 max_attempts），通过装饰器参数 `max_attempts` 传入
- analyzer 的 `analyze()` 在 LLM 失败后降级为 `_fallback_analyze`，不重试内容解析异常
- `analyze()` 的 `except` 子句增加 `BudgetExceededError`，确保预算耗尽时降级而非崩溃

## Capabilities

### New Capabilities

- `llm-retry`: with_retry 装饰器的参数约束、异常分类表（该重试 vs 不该重试）、
  LLM 调用适配层（per-error_type 转换）、时间窗口策略表、退避算法规范

### Modified Capabilities

（无--现有 `chat_completion_with_retry` 和 `RetryPolicyFactory` 的行为不变，spec 不改）

## Impact

- **新增文件**: `src/llm/retry_decorator.py`、`src/pipeline/llm_call_adapter.py`、`tests/llm/test_retry_decorator.py`、`tests/pipeline/test_llm_call_adapter.py`
- **修改文件**: `src/pipeline/analyzer.py`（在 `chat_for_analysis` 上挂 `@with_retry`，`analyze()` 的 `except` 增加 `BudgetExceededError`）
- **不影响**: `src/llm/client.py` 的 `chat_completion` / `chat_completion_with_retry` 逻辑不变
- **spec 同步**: 新增 `docs/specs/` 无需改动（OpenSpec spec 独立管理），但 `docs/specs/llm-provider.md` §9.5 可补充装饰器引用
