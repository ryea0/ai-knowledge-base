## Purpose

为 `with_retry` 装饰器定义可重试与不可重试异常的边界、退避参数约束、以及时间窗口策略表，
使重试行为成为 spec 驱动的显式契约而非隐式约定。

## ADDED Requirements

### Requirement: 异常分类表

装饰器 MUST 通过 `retry_on` 和 `no_retry_on` 两个参数显式声明异常白名单。
落入 `retry_on` 的异常触发重试；落入 `no_retry_on` 的异常立即抛出不重试；
同时出现在两个列表中的异常，`no_retry_on` 优先（不重试）。
未出现在任一列表中的异常，默认不重试（安全默认）。

**该重试（瞬时故障 -- 重试大概率能好）**:

| 异常 | 来源 | 说明 |
|------|------|------|
| `httpx.TimeoutException` | httpx | HTTP 请求超时 |
| `httpx.ConnectError` | httpx | TCP 连接失败 |
| `httpx.ReadError` | httpx | 读取响应数据失败 |
| `httpx.RemoteProtocolError` | httpx | 服务端协议错误 |
| `LlmCallError`（error_type=TIMEOUT） | src.llm.client | LLM 请求超时 |
| `LlmCallError`（error_type=RATE_LIMITED） | src.llm.client | LLM 限流 |
| `LlmCallError`（error_type=NETWORK） | src.llm.client | LLM 网络异常 |
| `LlmCallError`（error_type=SERVER_ERROR） | src.llm.client | LLM 服务端 5xx |

**不该重试（内容问题 -- 重试只会浪费钱）**:

| 异常 | 来源 | 说明 |
|------|------|------|
| `json.JSONDecodeError` | 标准库 | JSON 解析失败，内容本身有问题 |
| `KeyError` | 标准库 | 缺少必需字段，内容结构不符合预期 |
| `ValueError` | 标准库 | 内容值域非法（如 score 不是数字） |
| `LlmCallError`（error_type=AUTH_FAILED） | src.llm.client | 鉴权失败，重试不会改变结果 |
| `LlmCallError`（error_type=CLIENT_ERROR） | src.llm.client | 客户端 4xx，请求本身有误 |
| `BudgetExceededError` | src.llm.budget | 预算超限，重试只会花更多钱 |

#### Scenario: timeout 异常触发重试

- **WHEN** 被装饰函数抛出 `httpx.TimeoutException`
- **THEN** 装饰器按 `max_attempts` 和退避参数执行重试

#### Scenario: JSON 解析失败不重试

- **WHEN** 被装饰函数抛出 `json.JSONDecodeError`
- **THEN** 装饰器立即将异常向上抛出，不执行任何重试

#### Scenario: BudgetExceededError 不重试

- **WHEN** 被装饰函数抛出 `BudgetExceededError`
- **THEN** 装饰器立即将异常向上抛出，不执行任何重试

#### Scenario: 未声明的异常默认不重试

- **WHEN** 被装饰函数抛出一个既不在 `retry_on` 也不在 `no_retry_on` 中的异常
- **THEN** 装饰器立即将异常向上抛出，不执行重试

#### Scenario: no_retry_on 优先于 retry_on

- **WHEN** 某异常同时出现在 `retry_on` 和 `no_retry_on` 中
- **THEN** 装饰器将其视为不可重试，立即抛出

### Requirement: 退避参数约束

装饰器 MUST 接受以下参数，每个参数有明确的取值范围约束:

| 参数 | 类型 | 默认值 | 约束 | 说明 |
|------|------|--------|------|------|
| `retry_on` | `tuple[type[Exception], ...]` | `()` | 非空时每个元素须为 Exception 子类 | 触发重试的异常类型 |
| `no_retry_on` | `tuple[type[Exception], ...]` | `()` | 非空时每个元素须为 Exception 子类 | 禁止重试的异常类型 |
| `max_attempts` | `int` | `3` | `>= 1` 且 `<= 10` | 最大尝试次数（含首次调用） |
| `base_delay` | `float` | `1.0` | `> 0.0` 且 `<= 60.0` | 首次重试前等待秒数 |
| `backoff_factor` | `float` | `2.0` | `>= 1.0` 且 `<= 10.0` | 退避倍率 |
| `max_delay` | `float` | `60.0` | `> 0.0` 且 `<= 300.0` | 单次等待上限秒数 |
| `jitter` | `bool` | `True` | -- | 是否添加随机抖动（避免惊群） |

退避公式: `delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)`
当 `jitter=True` 时: `delay = delay * (0.5 + random() * 0.5)`（抖动到 50%-100% 区间）

#### Scenario: 默认参数重试 3 次

- **WHEN** 使用 `@with_retry(retry_on=(httpx.TimeoutException,))` 且不指定 `max_attempts`
- **THEN** 装饰器最多尝试 3 次（首次 + 2 次重试），退避为 1s -> 2s

#### Scenario: max_attempts=1 等于不重试

- **WHEN** 使用 `@with_retry(retry_on=(...), max_attempts=1)`
- **THEN** 装饰器仅调用 1 次，任何异常直接抛出

#### Scenario: 退避不超过 max_delay

- **WHEN** `base_delay=1.0, backoff_factor=2.0, max_delay=10.0`，第 5 次重试
- **THEN** 理论延迟 1*2^4=16s，实际等待被截断为 10s

#### Scenario: 参数越界抛 ValueError

- **WHEN** 传入 `max_attempts=0` 或 `max_attempts=11` 或 `base_delay=-1.0`
- **THEN** 装饰器在初始化时抛出 `ValueError`

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

def _get_retry_params() -> dict:
    hour = datetime.datetime.now().hour  # 本地时间
    if 8 <= hour < 22:
        return {"max_attempts": 3, "base_delay": 1.0, "backoff_factor": 2.0}
    return {"max_attempts": 1}
```

#### Scenario: 白天调用使用 3 次重试

- **WHEN** 当前本地时间 14:00，调用方查策略表得到 `max_attempts=3`
- **THEN** 装饰器接收 `max_attempts=3`，最多重试 2 次

#### Scenario: 夜间调用使用 1 次尝试

- **WHEN** 当前本地时间 23:00，调用方查策略表得到 `max_attempts=1`
- **THEN** 装饰器接收 `max_attempts=1`，任何异常直接抛出不重试

### Requirement: 重试日志

每次重试 MUST 记录 WARNING 级别日志，包含: 函数名、异常类型、异常消息（脱敏后）、当前尝试次数、最大尝试次数、本次等待秒数。
重试耗尽后 MUST 记录 ERROR 级别日志，包含上述信息 + 最终异常堆栈。

禁止在日志中输出 API Key / Token 或其他敏感信息。

#### Scenario: 重试日志包含函数名和次数

- **WHEN** `analyze` 函数第 2 次重试
- **THEN** 日志输出: `WARNING ... analyze 重试 2/3, 等待 2.0s, 异常: TimeoutException`

#### Scenario: 重试耗尽记录 ERROR

- **WHEN** 3 次尝试全部失败
- **THEN** 日志输出: `ERROR ... analyze 重试耗尽 3/3`，并重新抛出异常

### Requirement: 与现有 chat_completion_with_retry 的关系

`with_retry` 装饰器 SHALL NOT 替换或修改现有 `chat_completion_with_retry` 的行为。
两者可共存: `chat_completion_with_retry` 继续用于需要 `RetryPolicyFactory` 自动分派的场景；
`with_retry` 用于需要显式声明异常白名单的场景。

当 `with_retry` 装饰的函数内部调用 `chat_completion_with_retry` 时，外层装饰器的
`retry_on` 仅捕获内层重试耗尽后抛出的 `LlmCallError`，不会导致双重重试
（内层重试已耗尽，外层捕获的是最终异常）。

#### Scenario: 装饰器不修改现有函数行为

- **WHEN** 不在任何函数上添加 `@with_retry` 装饰器
- **THEN** `chat_completion_with_retry` 的行为与添加装饰器前完全一致

#### Scenario: 装饰器包裹 chat_completion_with_retry 不导致双重重试

- **WHEN** `@with_retry(retry_on=(LlmCallError,))` 装饰的函数内部调用 `chat_completion_with_retry`
- **AND** 内层因 TIMEOUT 重试 3 次后耗尽抛出 `LlmCallError`
- **THEN** 外层装饰器捕获 `LlmCallError` 并按自身参数重试，但内层的 3 次重试不会重复执行
