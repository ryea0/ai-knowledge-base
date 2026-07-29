## Why

当前重试逻辑硬编码在 `chat_completion_with_retry` 内部，与 `RetryPolicyFactory` + `LlmCallError` 强耦合。
半年后回看：timeout 到底重试几次？base_delay 多少？为什么不重试 JSONDecodeError？
这些边界散落在代码里，没有 spec 约束，AI 每次都要重猜。

更深的问题：现有重试只覆盖 LLM 调用层（`LlmCallError`），不覆盖内容解析层
（`JSONDecodeError` / `KeyError`）。两类异常的「该不该重试」语义完全不同——
瞬时故障重试大概率能好，内容问题重试只会浪费钱——但当前没有统一的地方定义这条边界。

## What Changes

- 新增 `with_retry` 装饰器（`src/llm/retry_decorator.py`），通过参数声明
  `retry_on` / `no_retry_on` / `max_attempts` / `base_delay` / `backoff_factor` / `max_delay`
- 装饰器独立于现有 `RetryPolicyFactory` 体系，可作用于任意函数（LLM 调用、HTTP 采集、内容解析等）
- 现有 `chat_completion_with_retry` 保持不变，装饰器作为新调用点的可选增强
- 定义异常分类表（瞬时故障 vs 内容问题），作为 spec 的核心契约
- 定义时间窗口策略表（白天/夜里不同 max_attempts），通过装饰器参数 `max_attempts` 传入
- analyzer 的 `analyze()` 在 LLM 失败后降级为 `_fallback_analyze`，不重试内容解析异常

## Capabilities

### New Capabilities

- `llm-retry`: with_retry 装饰器的参数约束、异常分类表（该重试 vs 不该重试）、时间窗口策略表、退避算法规范

### Modified Capabilities

（无——现有 `chat_completion_with_retry` 和 `RetryPolicyFactory` 的行为不变，spec 不改）

## Impact

- **新增文件**: `src/llm/retry_decorator.py`、`tests/llm/test_retry_decorator.py`
- **修改文件**: `src/pipeline/analyzer.py`（在 `_analyze_with_llm` 上挂装饰器，显式声明重试/不重试异常）
- **不影响**: `src/llm/client.py` 的 `chat_completion_with_retry` 逻辑不变
- **spec 同步**: 新增 `docs/specs/` 无需改动（OpenSpec spec 独立管理），但 `docs/specs/llm-provider.md` §9.5 可补充装饰器引用
