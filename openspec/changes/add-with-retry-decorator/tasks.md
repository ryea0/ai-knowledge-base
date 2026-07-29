## 1. 装饰器核心实现

- [ ] 1.1 创建 `src/llm/retry_decorator.py`，实现 `with_retry` 装饰器函数，支持参数: `retry_on` / `no_retry_on` / `max_attempts` / `base_delay` / `backoff_factor` / `max_delay` / `jitter`
- [ ] 1.2 实现参数校验逻辑: `max_attempts` 1-10、`base_delay` 0-60、`backoff_factor` 1-10、`max_delay` 0-300，越界抛 `ValueError`
- [ ] 1.3 实现退避公式: `delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)`，jitter 时 `delay * (0.5 + random() * 0.5)`
- [ ] 1.4 实现异常分类逻辑: `no_retry_on` 优先于 `retry_on`，未声明异常默认不重试
- [ ] 1.5 实现重试日志: WARNING 级别记录每次重试（函数名/异常类型/异常消息/尝试次数/等待秒数），ERROR 级别记录重试耗尽
- [ ] 1.6 在 `src/llm/__init__.py` 中导出 `with_retry`

## 2. 异常分类常量

- [ ] 2.1 在 `src/llm/retry_decorator.py` 中定义 `RETRYABLE_HTTP_EXCEPTIONS` 常量元组（`httpx.TimeoutException` / `ConnectError` / `ReadError` / `RemoteProtocolError`）
- [ ] 2.2 定义 `NON_RETRYABLE_CONTENT_EXCEPTIONS` 常量元组（`json.JSONDecodeError` / `KeyError` / `ValueError`）
- [ ] 2.3 定义 `NON_RETRYABLE_LLM_EXCEPTIONS` 常量元组（`BudgetExceededError` + 按需筛选 `LlmCallError` 子类型说明）

## 3. 集成到 analyzer

- [ ] 3.1 在 `src/pipeline/analyzer.py` 中添加 `_get_retry_params()` 函数，按时间窗口（08:00-22:00 / 22:00-08:00 本地时间）返回 `max_attempts` 等参数
- [ ] 3.2 在 `analyzer._analyze_with_llm` 上应用 `@with_retry` 装饰器，声明 `retry_on` 含 `LlmCallError`、`no_retry_on` 含 `BudgetExceededError`
- [ ] 3.3 确认装饰器不干扰 `analyzer.analyze():91` 的 `except (LlmCallError, RuntimeError)` 降级逻辑--装饰器重试耗尽后抛出异常，由 `analyze()` 捕获并降级

## 4. 测试

- [ ] 4.1 创建 `tests/llm/test_retry_decorator.py`，测试 timeout 异常触发重试
- [ ] 4.2 测试 JSONDecodeError 不重试，立即抛出
- [ ] 4.3 测试 BudgetExceededError 不重试，立即抛出
- [ ] 4.4 测试未声明异常默认不重试
- [ ] 4.5 测试 `no_retry_on` 优先于 `retry_on`
- [ ] 4.6 测试 `max_attempts=1` 等于不重试
- [ ] 4.7 测试退避不超过 `max_delay`（`base_delay=1, backoff_factor=2, max_delay=10`，第 5 次延迟截断为 10s）
- [ ] 4.8 测试参数越界抛 `ValueError`（`max_attempts=0` / `max_attempts=11` / `base_delay=-1`）
- [ ] 4.9 测试 jitter 开启时延迟在 50%-100% 区间
- [ ] 4.10 测试重试日志包含函数名和次数（使用 `caplog` 断言）
- [ ] 4.11 测试时间窗口策略: `_get_retry_params()` 在白天返回 `max_attempts=3`，夜间返回 `max_attempts=1`

## 5. 质量检查

- [ ] 5.1 `uv run ruff check src/ tests/` 通过
- [ ] 5.2 `uv run mypy src/` 通过
- [ ] 5.3 `uv run pytest tests/ --cov=src --cov-fail-under=80` 通过
- [ ] 5.4 确认现有 `chat_completion_with_retry` 行为未改变（已有测试全绿）
