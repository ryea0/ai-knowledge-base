## Purpose

为 `with_retry` 装饰器定义可重试与不可重试异常的边界、退避参数约束、以及时间窗口策略表，
使重试行为成为 spec 驱动的显式契约而非隐式约定。

### Requirement: 异常分类表

装饰器 MUST 通过 `retry_on` 和 `no_retry_on` 两个参数显式声明异常白名单。
匹配语义为 `isinstance`：被装饰函数抛出的异常如果 `isinstance` 匹配 `retry_on` 中的任一类型则触发重试；
如果匹配 `no_retry_on` 中的任一类型则立即抛出不重试。
`no_retry_on` 优先于 `retry_on`：同时匹配两个列表时，不重试。
未匹配任一列表的异常，默认不重试（安全默认）。

> **设计约束**: `retry_on` / `no_retry_on` 接收 `tuple[type[Exception], ...]`，
> 匹配基于 Python `isinstance`（子类匹配父类声明）。
> 因此无法直接按 `LlmCallError.error_type` 属性区分 "TIMEOUT 重试 / AUTH_FAILED 不重试"。
> 解决方案见 [Requirement: LLM 调用适配层] -- 适配层函数将不可重试的 `LlmCallError`
> 转换为 `NonRetryableLlmError`，使装饰器能按类型区分。

**该重试（瞬时故障 -- 重试大概率能好）**:

| 异常类型 | 来源 | 说明 |
|----------|------|------|
| `httpx.TimeoutException` | httpx | HTTP 请求超时 |
| `httpx.ConnectError` | httpx | TCP 连接失败 |
| `httpx.ReadError` | httpx | 读取响应数据失败 |
| `httpx.RemoteProtocolError` | httpx | 服务端协议错误 |
| `LlmCallError`（error_type=TIMEOUT） | src.llm.client | LLM 请求超时 |
| `LlmCallError`（error_type=RATE_LIMITED） | src.llm.client | LLM 限流 |
| `LlmCallError`（error_type=NETWORK） | src.llm.client | LLM 网络异常 |
| `LlmCallError`（error_type=SERVER_ERROR） | src.llm.client | LLM 服务端 5xx |

> 注意: 上表中 `LlmCallError` 的 per-error_type 细分在适配层实现，
> 装饰器侧 `retry_on` 只声明 `LlmCallError` 整体类型。
> 适配层将 `error_type` 为 AUTH_FAILED / CLIENT_ERROR 的 `LlmCallError` 转换为
> `NonRetryableLlmError`，使其不匹配 `retry_on`，从而不被重试。

> **异常包装边界**: `chat_completion()` 内部 `except Exception`（`src/llm/client.py:313`）
> 会捕获 `litellm.completion()` 抛出的**所有**异常（含 OpenAI SDK 的
> `APITimeoutError` / `APIConnectionError` / `RateLimitError` / `APIStatusError` /
> `AuthenticationError` / `InternalServerError` 等），经 `_classify_exception()` 映射为
> `LlmCallError(error_type=...)` 后抛出。因此：
>
> - OpenAI SDK 原生异常**不会**以原始类型到达 `with_retry` 装饰器，全部已包装为 `LlmCallError`
> - 装饰器的 `retry_on` / `no_retry_on` **不需要**也不应该声明 `openai.*` 异常类型
> - `httpx.*` 异常出现在分类表中是因为 HTTP 采集器（非 LLM 调用链）直接使用 httpx 且不经 `chat_completion` 包装
> - `BudgetExceededError` 由 `chat_completion` 内 `BudgetGuard.check_pre_call`（try/except **之前**，line 308）抛出，
>   绕过包装，以原始类型到达装饰器
> - `build_auth_context` 的配置/解密错误同样在 try/except 之前（line 266），以原始类型到达装饰器，
>   归类为"未声明异常默认不重试"

**不该重试（内容问题 -- 重试只会浪费钱）**:

| 异常类型 | 来源 | 说明 |
|----------|------|------|
| `json.JSONDecodeError` | 标准库 | JSON 解析失败，内容本身有问题 |
| `KeyError` | 标准库 | 缺少必需字段，内容结构不符合预期 |
| `ValueError` | 标准库 | 内容值域非法（如 score 不是数字） |
| `NonRetryableLlmError` | src.llm.retry_decorator | 不可重试的 LLM 错误（由适配层转换） |
| `BudgetExceededError` | src.llm.budget | 预算超限，重试只会花更多钱 |

#### Scenario: timeout 异常触发重试

- **WHEN** 被装饰函数抛出 `httpx.TimeoutException`
- **THEN** 装饰器按 `max_attempts` 和退避参数执行重试

#### Scenario: 可重试的 LlmCallError 触发重试

- **WHEN** 适配层函数抛出 `LlmCallError`（error_type=TIMEOUT 或 RATE_LIMITED 或 NETWORK 或 SERVER_ERROR）
- **THEN** 装饰器捕获 `LlmCallError`（`retry_on` 声明了该类型）并执行重试

#### Scenario: 不可重试的 LlmCallError 转换后不重试

- **WHEN** `chat_completion` 抛出 `LlmCallError`（error_type=AUTH_FAILED 或 CLIENT_ERROR）
- **AND** 适配层将其转换为 `NonRetryableLlmError`
- **THEN** 装饰器不匹配 `retry_on`（`NonRetryableLlmError` 不是 `LlmCallError` 子类），立即抛出

#### Scenario: BudgetExceededError 不重试

- **WHEN** 被装饰函数抛出 `BudgetExceededError`
- **THEN** 装饰器匹配 `no_retry_on`，立即抛出不重试

#### Scenario: JSON 解析失败不重试

- **WHEN** 被装饰函数抛出 `json.JSONDecodeError`
- **THEN** 装饰器立即将异常向上抛出，不执行任何重试

#### Scenario: 未声明的异常默认不重试

- **WHEN** 被装饰函数抛出一个既不在 `retry_on` 也不在 `no_retry_on` 中的异常
- **THEN** 装饰器立即将异常向上抛出，不执行重试

#### Scenario: no_retry_on 优先于 retry_on

- **WHEN** 某异常同时 `isinstance` 匹配 `retry_on` 和 `no_retry_on` 中的类型
- **THEN** 装饰器将其视为不可重试，立即抛出

#### Scenario: 异常子类匹配父类声明

- **WHEN** `retry_on=(httpx.HTTPError,)` 且函数抛出 `httpx.TimeoutException`（`HTTPError` 子类）
- **THEN** `isinstance` 匹配成功，装饰器执行重试

### Requirement: LLM 调用适配层

由于 `LlmCallError` 使用 `error_type` **实例属性**（而非子类层级）区分错误类型，
`with_retry` 的 `type[Exception]` 匹配无法直接按 error_type 细分重试/不重试。

SHALL 新增 `src/pipeline/llm_call_adapter.py` 模块，定义适配层函数 `chat_for_analysis`：

1. 内部调用 `chat_completion`（**无重试版**，非 `chat_completion_with_retry`），避免双重重试
2. 捕获 `LlmCallError`，检查 `error_type`：
   - `TIMEOUT` / `RATE_LIMITED` / `NETWORK` / `SERVER_ERROR` -> **原样抛出**（匹配装饰器 `retry_on`）
   - `AUTH_FAILED` / `CLIENT_ERROR` / `UNKNOWN` -> **转换为 `NonRetryableLlmError` 抛出**（不匹配 `retry_on`）
3. `BudgetExceededError` 原样穿透（由 `chat_completion` 内 `BudgetGuard.check_pre_call` 抛出，匹配 `no_retry_on`）

`NonRetryableLlmError` 定义在 `src/llm/retry_decorator.py`，继承 `Exception`（非 `LlmCallError`），
携带原始 `LlmCallError` 引用供日志和调试。

#### Scenario: 适配层转换不可重试的 LlmCallError

- **WHEN** `chat_completion` 抛出 `LlmCallError`（error_type=AUTH_FAILED）
- **THEN** `chat_for_analysis` 捕获并转换为 `NonRetryableLlmError` 抛出
- **AND** `NonRetryableLlmError.original` 指向原始 `LlmCallError` 实例

#### Scenario: 适配层保留可重试的 LlmCallError

- **WHEN** `chat_completion` 抛出 `LlmCallError`（error_type=TIMEOUT）
- **THEN** `chat_for_analysis` 原样抛出 `LlmCallError`，不转换

#### Scenario: 适配层不使用 chat_completion_with_retry

- **WHEN** `chat_for_analysis` 内部调用 LLM
- **THEN** 调用的是 `chat_completion`（无重试），而非 `chat_completion_with_retry`
- **AND** 不发生双重重试（内层无重试，外层 `with_retry` 负责全部重试）

### Requirement: 退避参数约束

装饰器 MUST 接受以下参数，每个参数有明确的取值范围约束:

| 参数 | 类型 | 默认值 | 约束 | 说明 |
|------|------|--------|------|------|
| `retry_on` | `tuple[type[Exception], ...]` | `()` | 非空时每个元素须为 `type` 且 `issubclass(x, Exception)` | 触发重试的异常类型 |
| `no_retry_on` | `tuple[type[Exception], ...]` | `()` | 非空时每个元素须为 `type` 且 `issubclass(x, Exception)` | 禁止重试的异常类型 |
| `max_attempts` | `int` | `3` | `>= 1` 且 `<= 10` | 最大尝试次数（含首次调用） |
| `base_delay` | `float` | `1.0` | `> 0.0` 且 `<= 60.0` | 首次重试前等待秒数 |
| `backoff_factor` | `float` | `2.0` | `>= 1.0` 且 `<= 10.0` | 退避倍率 |
| `max_delay` | `float` | `60.0` | `> 0.0` 且 `<= 300.0` | 单次等待上限秒数 |
| `jitter` | `bool` | `True` | -- | 是否添加随机抖动（避免惊群） |

退避公式: `delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)`
当 `jitter=True` 时: `delay = delay * (0.5 + random() * 0.5)`（抖动到 50%-100% 区间）

#### Scenario: 默认参数重试 3 次（jitter=False）

- **WHEN** 使用 `@with_retry(retry_on=(httpx.TimeoutException,), jitter=False)` 且不指定 `max_attempts`
- **THEN** 装饰器最多尝试 3 次（首次 + 2 次重试），退避为 1s -> 2s

#### Scenario: max_attempts=1 等于不重试

- **WHEN** 使用 `@with_retry(retry_on=(...), max_attempts=1)`
- **THEN** 装饰器仅调用 1 次，任何异常直接抛出

#### Scenario: 退避不超过 max_delay（jitter=False）

- **WHEN** `base_delay=1.0, backoff_factor=2.0, max_delay=10.0, jitter=False`，第 5 次重试
- **THEN** 理论延迟 1*2^4=16s，实际等待被截断为 10s

#### Scenario: 参数越界抛 ValueError

- **WHEN** 传入 `max_attempts=0` 或 `max_attempts=11` 或 `base_delay=-1.0` 或 `backoff_factor=0.5` 或 `max_delay=0.0`
- **THEN** 装饰器在初始化时抛出 `ValueError`

#### Scenario: jitter 开启时延迟在 50%-100% 区间

- **WHEN** `jitter=True, base_delay=1.0, backoff_factor=2.0, max_delay=10.0`
- **THEN** 每次实际延迟 = 理论延迟 × (0.5 + random() × 0.5)，落在理论延迟的 50%-100% 区间

### Requirement: 时间窗口策略表

当业务需要按时间窗口区分重试强度时，调用方 SHALL 在装饰器参数中传入不同的 `max_attempts` 值。
时间窗口的判定逻辑在调用方（而非装饰器内部），装饰器只接收最终的 `max_attempts` 数值。

**策略表（定义在 spec 中，代码中通过查表传入）**:

| 时间窗口 | max_attempts | base_delay | backoff_factor | 适用场景 |
|----------|-------------|------------|----------------|---------|
| 白天 (08:00-22:00 UTC+8) | 3 | 1.0 | 2.0 | 正常运行，容忍多次重试 |
| 夜间 (22:00-08:00 UTC+8) | 1 | -- | -- | 定时任务，失败不重试，避免长时间阻塞 |

调用方示例（非装饰器内部逻辑）:

```python
import datetime

def _get_retry_params(now: datetime.datetime | None = None) -> dict:
    """获取当前时间窗口的重试参数。

    Args:
        now: 可注入的当前时间，用于测试。默认 ``datetime.datetime.now()``。
    """
    current = now or datetime.datetime.now()
    hour = current.hour
    if 8 <= hour < 22:
        return {"max_attempts": 3, "base_delay": 1.0, "backoff_factor": 2.0}
    return {"max_attempts": 1}
```

#### Scenario: 白天调用使用 3 次重试

- **WHEN** 当前时间 14:00（通过注入 `now` 模拟），调用方查策略表得到 `max_attempts=3`
- **THEN** 装饰器接收 `max_attempts=3`，最多重试 2 次

#### Scenario: 夜间调用使用 1 次尝试

- **WHEN** 当前时间 23:00（通过注入 `now` 模拟），调用方查策略表得到 `max_attempts=1`
- **THEN** 装饰器接收 `max_attempts=1`，任何异常直接抛出不重试

### Requirement: 重试日志

每次重试 MUST 记录 WARNING 级别日志，包含: 函数名、异常类型名、异常消息（脱敏后）、当前尝试次数、最大尝试次数、本次等待秒数。
重试耗尽后 MUST 记录 ERROR 级别日志，包含上述信息 + 最终异常堆栈。

禁止在日志中输出 API Key / Token 或其他敏感信息。

> **jitter 与日志**: 当 `jitter=True` 时，日志中记录的等待秒数为**实际等待值**（已含抖动），
> 非理论值。测试时可通过 `jitter=False` 或固定 `random.seed` 断言精确值。

#### Scenario: 重试日志包含函数名和次数（jitter=False）

- **WHEN** `jitter=False`，`analyze` 函数第 2 次重试
- **THEN** 日志输出包含: 函数名 `analyze`、`2/3`、等待 `2.0s`、异常类型 `TimeoutException`

#### Scenario: 重试耗尽记录 ERROR

- **WHEN** 3 次尝试全部失败
- **THEN** 日志输出 ERROR 级别，包含 `3/3`，并重新抛出异常

#### Scenario: 异常消息脱敏

- **WHEN** 异常消息中包含 `sk-xxxx` 格式的 API Key
- **THEN** 日志中的异常消息已脱敏，不包含原始 Key

### Requirement: 与现有 chat_completion_with_retry 的关系

`with_retry` 装饰器 SHALL NOT 替换或修改现有 `chat_completion_with_retry` 的行为。
两者可共存: `chat_completion_with_retry` 继续用于需要 `RetryPolicyFactory` 自动分派的场景；
`with_retry` 用于需要显式声明异常白名单的场景。

使用 `with_retry` 的调用点 MUST 在装饰的函数内部调用 `chat_completion`（无重试版），
SHALL NOT 调用 `chat_completion_with_retry`，以避免双重重试。

#### Scenario: 装饰器不修改现有函数行为

- **WHEN** 不在任何函数上添加 `@with_retry` 装饰器
- **THEN** `chat_completion_with_retry` 的行为与添加装饰器前完全一致

#### Scenario: 装饰器包裹 chat_completion 不导致双重重试

- **WHEN** `@with_retry(retry_on=(LlmCallError,))` 装饰的函数内部调用 `chat_completion`（无重试版）
- **AND** `chat_completion` 因 TIMEOUT 抛出 `LlmCallError`
- **THEN** 外层装饰器捕获 `LlmCallError` 并重试，内层 `chat_completion` 每次只执行 1 次调用
- **AND** 总调用次数 = 外层 `max_attempts`（无内层重试放大）

### Requirement: BudgetExceededError 传播路径

`BudgetExceededError` 由 `chat_completion` 内部的 `BudgetGuard.check_pre_call` 抛出
（`src/llm/client.py:308`），继承 `Exception`，不是 `LlmCallError` 或 `RuntimeError` 的子类。

在使用 `with_retry` 装饰的适配层函数中:
- `BudgetExceededError` MUST 出现在 `no_retry_on` 中，确保不被重试
- 适配层函数 SHALL NOT 捕获 `BudgetExceededError`，让其原样穿透到装饰器

在 analyzer 集成中:
- `analyze()` 的 `except` 子句 MUST 能捕获 `BudgetExceededError` 或让其由更高层处理
- 若 `analyze()` 不处理 `BudgetExceededError`，则该异常会终止当前条目的处理流程
  （这是预期行为: 预算耗尽应停止 LLM 调用）

#### Scenario: BudgetExceededError 穿透适配层

- **WHEN** `chat_completion` 内 `BudgetGuard.check_pre_call` 抛出 `BudgetExceededError`
- **THEN** 适配层不捕获该异常，原样抛出
- **AND** 装饰器匹配 `no_retry_on=(BudgetExceededError,)`，立即抛出不重试

#### Scenario: BudgetExceededError 被 analyze 捕获降级

- **WHEN** `BudgetExceededError` 传播到 `analyze()` 方法
- **THEN** `analyze()` 的 `except` 子句捕获该异常并降级为规则分析
- **AND** 日志记录 WARNING 级别的降级信息
