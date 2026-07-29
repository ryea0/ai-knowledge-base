## 1. 装饰器核心实现

- [ ] 1.1 创建 `src/llm/retry_decorator.py`，定义 `NonRetryableLlmError(Exception)` 类，
      含 `original: LlmCallError` 属性，docstring 说明用途
- [ ] 1.2 实现 `with_retry` 装饰器函数，支持参数: `retry_on` / `no_retry_on` / `max_attempts` / `base_delay` / `backoff_factor` / `max_delay` / `jitter`
- [ ] 1.3 实现参数校验逻辑: `max_attempts` 1-10、`base_delay` >0 且 <=60、`backoff_factor` >=1 且 <=10、`max_delay` >0 且 <=300，
      `retry_on` / `no_retry_on` 每个元素须为 `type` 且 `issubclass(x, Exception)`，越界抛 `ValueError`
- [ ] 1.4 实现退避公式: `delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)`，
      jitter 时 `delay * (0.5 + random() * 0.5)`
- [ ] 1.5 实现异常分类逻辑: `isinstance` 语义匹配，`no_retry_on` 优先于 `retry_on`，未声明异常默认不重试
- [ ] 1.6 实现重试日志: WARNING 级别记录每次重试（函数名/异常类型名/异常消息/当前尝试次数/最大尝试次数/实际等待秒数），
      异常消息须经过 `sanitize_secrets` 脱敏；ERROR 级别记录重试耗尽（含异常堆栈）
- [ ] 1.7 在 `src/llm/__init__.py` 中导出 `with_retry` 和 `NonRetryableLlmError`

## 2. 异常分类常量

- [ ] 2.1 在 `src/llm/retry_decorator.py` 中定义 `RETRYABLE_HTTP_EXCEPTIONS` 常量元组
      （`httpx.TimeoutException` / `ConnectError` / `ReadError` / `RemoteProtocolError`）
- [ ] 2.2 定义 `NON_RETRYABLE_CONTENT_EXCEPTIONS` 常量元组
      （`json.JSONDecodeError` / `KeyError` / `ValueError`）
- [ ] 2.3 定义 `RETRYABLE_LLM_ERROR_TYPES` 常量 frozenset
      （`LlmErrorType.TIMEOUT` / `RATE_LIMITED` / `NETWORK` / `SERVER_ERROR`），
      供适配层 `chat_for_analysis` 引用，避免硬编码 error_type 列表

## 3. LLM 调用适配层

- [ ] 3.1 创建 `src/pipeline/llm_call_adapter.py`，实现 `chat_for_analysis` 函数
- [ ] 3.2 `chat_for_analysis` 内部调用 `chat_completion`（无重试版），不调用 `chat_completion_with_retry`
- [ ] 3.3 捕获 `LlmCallError`，检查 `error_type`：
      若在 `RETRYABLE_LLM_ERROR_TYPES` 中则原样抛出；否则转换为 `NonRetryableLlmError` 抛出
- [ ] 3.4 `BudgetExceededError` 不捕获，原样穿透（由 `chat_completion` 内 `BudgetGuard.check_pre_call` 抛出）

## 4. 集成到 analyzer

- [ ] 4.1 在 `src/pipeline/analyzer.py` 中添加 `_get_retry_params(now=None)` 函数，
      按时间窗口（08:00-22:00 / 22:00-08:00）返回 `max_attempts` 等参数
- [ ] 4.2 将 `_analyze_with_llm` 中的 `quick_chat` 调用替换为 `@with_retry` 装饰的 `chat_for_analysis` 调用，
      声明 `retry_on` 含 `LlmCallError` + `RETRYABLE_HTTP_EXCEPTIONS`，
      `no_retry_on` 含 `BudgetExceededError` + `NonRetryableLlmError` + `NON_RETRYABLE_CONTENT_EXCEPTIONS`
- [ ] 4.3 修改 `analyze():91` 的 `except` 子句，增加 `BudgetExceededError` 和 `NonRetryableLlmError`，
      确保预算耗尽和不可重试 LLM 错误均降级为规则分析

## 5. 测试 -- 装饰器

- [ ] 5.1 创建 `tests/llm/test_retry_decorator.py`，测试 `httpx.TimeoutException` 触发重试
- [ ] 5.2 测试 `json.JSONDecodeError` 不重试，立即抛出
- [ ] 5.3 测试 `BudgetExceededError` 不重试，立即抛出
- [ ] 5.4 测试未声明异常默认不重试
- [ ] 5.5 测试 `no_retry_on` 优先于 `retry_on`（异常同时匹配两个列表时不重试）
- [ ] 5.6 测试异常子类匹配父类声明（`retry_on=(httpx.HTTPError,)` + 抛 `httpx.TimeoutException` -> 重试）
- [ ] 5.7 测试 `max_attempts=1` 等于不重试
- [ ] 5.8 测试退避不超过 `max_delay`（`base_delay=1, backoff_factor=2, max_delay=10, jitter=False`，第 5 次延迟截断为 10s）
- [ ] 5.9 测试参数越界抛 `ValueError`（`max_attempts=0` / `max_attempts=11` / `base_delay=-1` / `base_delay=61` / `backoff_factor=0.5` / `backoff_factor=11` / `max_delay=0` / `max_delay=301`）
- [ ] 5.10 测试 `retry_on` / `no_retry_on` 传入非 Exception 子类抛 `ValueError`（如 `retry_on=(str,)`）
- [ ] 5.11 测试 `jitter=True` 时延迟在理论值的 50%-100% 区间（固定 random.seed 断言范围）
- [ ] 5.12 测试重试日志包含函数名和次数（`jitter=False` + `caplog` 断言精确值）
- [ ] 5.13 测试重试耗尽记录 ERROR 级别日志
- [ ] 5.14 测试异常消息脱敏（构造含 `sk-xxxx` 的异常，断言日志中已脱敏）
- [ ] 5.15 测试 `NonRetryableLlmError` 类: 继承 `Exception` 而非 `LlmCallError`，`original` 属性指向原始异常

## 6. 测试 -- 适配层

- [ ] 6.1 创建 `tests/pipeline/test_llm_call_adapter.py`
- [ ] 6.2 测试 `chat_for_analysis` 调用 `chat_completion`（非 `chat_completion_with_retry`），mock 验证调用目标
- [ ] 6.3 测试可重试的 `LlmCallError`（TIMEOUT）原样抛出，不转换
- [ ] 6.4 测试不可重试的 `LlmCallError`（AUTH_FAILED / CLIENT_ERROR / UNKNOWN）转换为 `NonRetryableLlmError`
- [ ] 6.5 测试 `NonRetryableLlmError.original` 指向原始 `LlmCallError` 实例
- [ ] 6.6 测试 `BudgetExceededError` 原样穿透，不被捕获

## 7. 测试 -- analyzer 集成

- [ ] 7.1 测试 `_get_retry_params(now=14:00)` 返回 `max_attempts=3`
- [ ] 7.2 测试 `_get_retry_params(now=23:00)` 返回 `max_attempts=1`
- [ ] 7.3 测试 `analyze()` 捕获 `BudgetExceededError` 降级为 `_fallback_analyze`
- [ ] 7.4 测试 `analyze()` 捕获 `NonRetryableLlmError` 降级为 `_fallback_analyze`
- [ ] 7.5 测试 `analyze()` 捕获 `LlmCallError`（重试耗尽后）降级为 `_fallback_analyze`

## 8. 质量检查

- [ ] 8.1 `uv run ruff check src/ tests/` 通过
- [ ] 8.2 `uv run mypy src/` 通过
- [ ] 8.3 `uv run pytest tests/ --cov=src --cov-fail-under=80` 通过
- [ ] 8.4 确认现有 `chat_completion_with_retry` 行为未改变（已有测试全绿）
- [ ] 8.5 确认 `RETRYABLE_HTTP_EXCEPTIONS` 和 `NON_RETRYABLE_CONTENT_EXCEPTIONS` 有引用方（analyzer 集成中使用），无死代码
