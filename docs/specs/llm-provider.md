# LLM 供应商管理规范

> 本文件从 AGENTS.md §9 拆分而来，章节编号保持不变。
> 代码实现见 `src/llm/`，DDL 见 `deploy/sql/01-04_*.sql`，枚举定义见 `src/models/enums.py`。

---

## §9.1 供应商与模型

### 三张表

| 表 | 职责 | DDL 文件 |
| -- | ---- | -------- |
| `kb_llm_provider` | 供应商连接配置、鉴权信息（不含健康状态） | `deploy/sql/01_kb_llm_provider.sql` |
| `kb_llm_model` | 模型清单（每供应商多个，`is_default` 标记默认） | `deploy/sql/02_kb_llm_model.sql` |
| `kb_llm_health` | 模型级当前健康状态（upsert 语义，非 append-only） | `deploy/sql/03_kb_llm_health.sql` |

> 另有 `kb_llm_call_log`（`deploy/sql/08_kb_llm_call_log.sql`）记录每次 LLM 调用的 token 用量和成本，属于计量日志，不在本规范范围内。

### 枚举定义

枚举定义于 `src/models/enums.py`，DB 存整数值，JSON 写 `.name` 小写形式。

| 枚举 | DB 值 | JSON 字符串 | 说明 |
| ---- | ----- | ----------- | ---- |
| `LlmProviderType` | 0/1 | `cloud`/`local` | 供应商类型（云 / 本地），影响 `timeout_seconds` 建议值和前端分组展示 |
| `LlmAuthType` | 0/1/2/3 | `bearer`/`oauth`/`header`/`none` | 鉴权方式，决定凭证字段的填充规则 |
| `LlmHealthStatus` | 0/1/2/3 | `healthy`/`degraded`/`unhealthy`/`unknown` | 模型级健康状态（类熔断器） |
| `LlmModelSource` | 0/1/2 | `preset`/`discovered`/`manual` | 模型记录来源 |

### 协议兼容分类

按 LiteLLM 的 `litellm_provider` 值区分协议族。**一期 6 家供应商中 5 家走 OpenAI 兼容协议**，只有 Ollama 保留原生协议（利用 LiteLLM 的模型管理能力）。

| 协议族 | litellm_provider | 鉴权方式 | 模型前缀 | 一期供应商 | 二期扩展 |
| ------ | ---------------- | -------- | -------- | ---------- | -------- |
| **OpenAI 兼容** | `openai` | bearer / none | `openai/{model_code}` | openai, deepseek, ark(火山), qwen, llamacpp | 百度千帆, Moonshot, Together, OpenRouter |
| **Ollama 原生** | `ollama` | none | `ollama/{model_code}` | ollama | -- |
| **Anthropic 原生** | `anthropic` | header | `anthropic/{model_code}` | -- | Claude 系列 |
| **Gemini 原生** | `gemini` | header | `gemini/{model_code}` | -- | Google Gemini |
| **Azure OpenAI** | `azure` | bearer | `azure/{deployment_name}` | -- | 企业 Azure |

**`litellm_model` 命名规则**：`f"{litellm_provider}/{model_code}"`，由 `service.py` 在创建/发现模型时自动拼接。

**种子数据调整**（相比旧设计）：

| provider_code | litellm_provider（旧 -> 新） | litellm_model 示例（旧 -> 新） |
| ------------- | --------------------------- | ----------------------------- |
| ark | `volcengine` -> `openai` | `volcengine/doubao-*` -> `openai/doubao-*` |
| deepseek | `deepseek` -> `openai` | `deepseek/deepseek-chat` -> `openai/deepseek-chat` |
| qwen | `openai`（不变） | 不变 |
| openai | `openai`（不变） | 不变 |
| ollama | `ollama`（不变） | 不变 |
| llamacpp | `openai`（不变） | 不变 |

### 鉴权方式与凭证存储

**废弃 `auth_config` JSON 列**，拆为显式列，避免密钥与配置混装、无法 DB 级约束：

| auth_type | `api_key_encrypted` | `secret_key_encrypted` | `header_name` | `token_url` | 典型供应商 |
| --------- | ------------------- | --------------------- | ------------- | ----------- | ---------- |
| `bearer` (0) | 加密 API Key | NULL | NULL | NULL | OpenAI / DeepSeek / Ark / Qwen |
| `oauth` (1) | 加密 API Key | 加密 Secret Key | NULL | OAuth token 交换地址 | 百度千帆（二期） |
| `header` (2) | 加密 API Key | NULL | 自定义 header 名（如 `x-api-key`） | NULL | Anthropic / Gemini（二期） |
| `none` (3) | NULL | NULL | NULL | NULL | Ollama / llama.cpp |

**安全要求**：
- `api_key_encrypted` 和 `secret_key_encrypted` 须用 `LLM_PROVIDER_ENCRYPTION_KEY` 环境变量经 SHA-256 派生 Fernet 密钥加密存储，禁止明文入库。
- 日志中禁止输出 `api_key_encrypted` / `secret_key_encrypted` / `header_name` / `token_url` 内容（AGENTS.md 红线 #10 延伸）。
- `last_error` 字段须脱敏后写入，移除可能包含的 API Key 片段。

### `kb_llm_provider` 表结构

```sql
CREATE TABLE kb_llm_provider (
    id                      BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    provider_code           VARCHAR(40)      NOT NULL                COMMENT '供应商代码，如 deepseek/ark/openai/ollama',
    display_name            VARCHAR(80)      NOT NULL                COMMENT '展示名称',
    provider_type           TINYINT UNSIGNED NOT NULL DEFAULT 0      COMMENT '类型 0=cloud 1=local，枚举 LlmProviderType',
    base_url                VARCHAR(255)     NOT NULL                COMMENT 'API 基础 URL',
    litellm_provider        VARCHAR(40)      NOT NULL                COMMENT 'LiteLLM 供应商标识，决定协议族和模型前缀',
    -- 鉴权
    auth_type               TINYINT UNSIGNED NOT NULL DEFAULT 0      COMMENT '鉴权方式 0=bearer 1=oauth 2=header 3=none，枚举 LlmAuthType',
    api_key_encrypted       VARCHAR(255)     NULL                    COMMENT '加密主凭证，none 类型为 NULL',
    secret_key_encrypted    VARCHAR(255)     NULL                    COMMENT '加密二次凭证，仅 auth_type=oauth 使用',
    header_name             VARCHAR(100)     NULL                    COMMENT '自定义鉴权 header 名，仅 auth_type=header 使用',
    token_url               VARCHAR(255)     NULL                    COMMENT 'OAuth token 交换地址，仅 auth_type=oauth 使用',
    -- 路由与限流
    is_enabled              TINYINT(1) UNSIGNED NOT NULL DEFAULT 1   COMMENT '是否启用',
    priority                INT              NOT NULL DEFAULT 100    COMMENT '路由优先级，数值越小越高',
    timeout_seconds         INT              NOT NULL DEFAULT 30     COMMENT '单次请求超时秒数',
    max_retries             INT              NOT NULL DEFAULT 3      COMMENT '最大重试次数上限（按错误类型策略取 min）',
    rpm_limit               INT              NOT NULL DEFAULT 0      COMMENT '每分钟请求上限，0=不限速（预留，一期不实现）',
    -- 软删除
    is_deleted              TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否软删除',
    deleted_at              DATETIME(3)      NULL                    COMMENT '软删除时间',
    provider_code_guard     VARCHAR(46)      AS (CASE WHEN is_deleted=0 THEN CONCAT('code:',provider_code) ELSE NULL END) STORED COMMENT 'provider_code 唯一约束辅助列',
    created_at              DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at              DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_provider_code_guard (provider_code_guard),
    KEY idx_enabled_priority (is_enabled, priority),
    KEY idx_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM 供应商表';
```

**相比旧设计**：删除 9 个内联健康字段（`health_status` / `health_check_enabled` / `last_check_at` / `last_success_at` / `last_failure_at` / `consecutive_failures` / `failure_threshold` / `last_error`），健康状态移至 `kb_llm_health` 表（模型级）。删除 `auth_config` JSON 列，拆为 4 个显式列。

### `kb_llm_model` 表结构

见 `deploy/sql/02_kb_llm_model.sql`。关键列说明：

| 列 | 类型 | 默认 | 说明 |
| -- | ---- | ---- | ---- |
| `context_window` | INT | 4096 | 上下文窗口大小 tokens |
| `max_output_tokens` | INT | 4096 | 最大输出 tokens |
| `supports_streaming` | TINYINT(1) | 1 | 是否支持流式输出 |
| `supports_function_calling` | TINYINT(1) | 0 | 是否支持函数调用 |
| `supports_vision` | TINYINT(1) | 0 | 是否支持视觉/多模态 |
| `supports_reasoning` | TINYINT(1) | 0 | 是否为推理模型（详见 §9.7） |
| `task_type` | JSON | NULL | 任务类型数组，如 `["TextGeneration"]`、`["VisualQuestionAnswering"]`，由模型发现时从供应商 API 提取（详见 §9.4） |
| `input_price_per_1m` | DECIMAL(10,4) | 0.0000 | 输入每百万 token 价格 USD，local=0 |
| `output_price_per_1m` | DECIMAL(10,4) | 0.0000 | 输出每百万 token 价格 USD，local=0 |
| `source` | TINYINT | 0 | 来源 0=preset 1=discovered 2=manual |

### `kb_llm_health` 表结构

**替代旧的 `kb_llm_health_log`**。从 append-only 日志表改为模型级当前状态表（upsert 语义），继承 BaseEntity 全部标准字段。

```sql
CREATE TABLE kb_llm_health (
    id                      BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    provider_id             BIGINT UNSIGNED  NOT NULL                COMMENT '供应商 kb_llm_provider.id',
    model_id                BIGINT UNSIGNED  NOT NULL                COMMENT '模型 kb_llm_model.id（每个模型一行）',
    health_status           TINYINT UNSIGNED NOT NULL DEFAULT 3      COMMENT '健康状态 0=healthy 1=degraded 2=unhealthy 3=unknown',
    consecutive_failures    INT              NOT NULL DEFAULT 0      COMMENT '连续失败次数，成功时归零',
    failure_threshold       INT              NOT NULL DEFAULT 5      COMMENT '连续失败达此值时转 unhealthy',
    health_check_enabled    TINYINT(1) UNSIGNED NOT NULL DEFAULT 1   COMMENT '是否启用健康检查',
    last_check_at           DATETIME(3)      NULL                    COMMENT '最近健康检查时间',
    last_success_at         DATETIME(3)      NULL                    COMMENT '最近成功时间',
    last_failure_at         DATETIME(3)      NULL                    COMMENT '最近失败时间',
    last_latency_ms         INT              NULL                    COMMENT '最近检查延迟毫秒',
    last_error              VARCHAR(500)     NULL                    COMMENT '最近错误信息（须脱敏）',
    -- 软删除
    is_deleted              TINYINT(1) UNSIGNED NOT NULL DEFAULT 0   COMMENT '是否软删除',
    deleted_at              DATETIME(3)      NULL                    COMMENT '软删除时间',
    model_health_guard      VARCHAR(30)      AS (CASE WHEN is_deleted=0 THEN CONCAT('mh:',model_id) ELSE NULL END) STORED COMMENT 'model_id 唯一约束辅助列，每模型至多一行健康状态',
    created_at              DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at              DATETIME(3)      NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_model_health_guard (model_health_guard),
    KEY idx_provider_status (provider_id, health_status),
    KEY idx_model_id (model_id),
    KEY idx_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM 模型健康状态表';
```

**设计要点**：
- 每个模型至多一行（`uk_model_health_guard` 保证），upsert 语义：首次 INSERT，后续 UPDATE。
- `failure_threshold` 按模型可配（local 模型建议设高阈值），从 provider 级下放到模型级。
- 创建模型时（`service.create_model`）自动创建对应 `kb_llm_health` 行（`health_status=unknown`）。
- 删除模型时同步软删除 health 行。

### 一期参考数据

6 家供应商 + 11 个模型 + 11 行健康状态（全部 `unknown`），通过管理后台或 API 创建，不再使用种子 SQL。

| provider_code | provider_type | auth_type | litellm_provider | base_url |
| ------------- | ------------- | --------- | ---------------- | -------- |
| `ark` | cloud | bearer | `openai` | `https://ark.cn-beijing.volces.com/api/v3` |
| `deepseek` | cloud | bearer | `openai` | `https://api.deepseek.com/v1` |
| `qwen` | cloud | bearer | `openai` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `openai` | cloud | bearer | `openai` | `https://api.openai.com/v1` |
| `ollama` | local | none | `ollama` | `http://localhost:11434/v1` |
| `llamacpp` | local | none | `openai` | `http://localhost:8080/v1` |

---

## §9.2 模型级健康状态机

### 状态定义

健康状态存于 `kb_llm_health` 表，粒度为 **(provider, model)**，而非供应商级。同一供应商下不同模型可独立熔断/恢复。

```
UNKNOWN ──首次检查/调用──▶ HEALTHY
HEALTHY ──失败 1 次──▶ DEGRADED
DEGRADED ──失败达 threshold──▶ UNHEALTHY
UNHEALTHY ──健康检查成功──▶ HEALTHY
任意状态 ──成功──▶ HEALTHY（consecutive_failures 归零）
```

### 状态转换规则

| 触发事件 | 操作 | CAS 条件 |
| -------- | ---- | -------- |
| 业务调用成功 | `consecutive_failures=0`, `health_status=healthy`, 更新 `last_success_at` | `WHERE model_id=? AND is_deleted=0` |
| 业务调用失败 | `consecutive_failures+1`，达阈值转 `unhealthy`，否则转 `degraded`，更新 `last_failure_at` + `last_error` | `WHERE model_id=? AND is_deleted=0` |
| 定时健康检查 | 检查结果写入 `last_check_at` / `last_latency_ms`，成功转 `healthy`，失败转 `degraded` | `WHERE model_id=? AND is_deleted=0` |
| 手动重置 | `health_status=unknown`, `consecutive_failures=0`, `last_error=NULL` | `WHERE model_id=? AND is_deleted=0` |

- 所有状态转换使用 CAS（`UPDATE ... WHERE model_id=? AND health_status=?`）保证并发安全。
- `failure_threshold` 按模型可配（`kb_llm_health.failure_threshold`），local 类型建议设高阈值。
- unhealthy 模型被路由跳过，仅通过定时健康检查恢复，不接受业务调用自愈。

### 路由规则

路由查询按 **(provider, model, health)** 三元组筛选：

```sql
SELECT p.*, m.*, h.health_status
FROM kb_llm_provider p
JOIN kb_llm_model m ON m.provider_id = p.id AND m.is_default = 1 AND m.is_enabled = 1 AND m.is_deleted = 0
JOIN kb_llm_health h ON h.model_id = m.id AND h.is_deleted = 0
WHERE p.is_enabled = 1 AND p.is_deleted = 0
  AND h.health_status != 2  -- 排除 unhealthy
ORDER BY p.priority, p.id
```

- unhealthy 模型被自动跳过，degraded 仍可尝试。
- 若某 provider 的 default model 不可用，但同 provider 下有其他 enabled model 可用，一期不自动降级到非默认模型（路由只取 default model）。二期可扩展为同 provider 内 model fallback。

实现见 `src/llm/router.py`。

---

## §9.3 鉴权适配器

### 设计目标

将鉴权逻辑从 `client.py` / `health.py` / `service.py` 三处收拢到 **单一入口** `src/llm/auth_adapter.py`，按 `auth_type` 构造统一的 `AuthContext`。

### AuthContext

```python
@dataclass
class AuthContext:
    """鉴权后供 LiteLLM / httpx 调用的统一参数。"""
    api_key: str | None = None           # LiteLLM api_key 参数（bearer / oauth ）
    api_base: str | None = None          # LiteLLM api_base 参数
    extra_headers: dict[str, str] | None = None  # 自定义 header（header 鉴权）
    extra_kwargs: dict[str, Any] | None = None   # 协议特有参数（如 Azure api_version，二期）
```

### build_auth_context

```python
def build_auth_context(provider: LlmProvider) -> AuthContext:
    """根据 provider 的 auth_type 构造鉴权上下文（唯一入口）。"""
```

适配逻辑：

| auth_type | 构造逻辑 |
| --------- | -------- |
| `none` | `AuthContext(api_base=provider.base_url)` |
| `bearer` | `decrypt(api_key_encrypted)` -> `AuthContext(api_key=<plaintext>, api_base=base_url)` |
| `header` | `decrypt(api_key_encrypted)` -> `AuthContext(extra_headers={header_name: <plaintext>}, api_base=base_url)` |
| `oauth` | `decrypt(api_key_encrypted)` + `decrypt(secret_key_encrypted)` -> POST `token_url` 换 access_token -> `AuthContext(api_key=<access_token>, api_base=base_url)` |

### OAuth token 缓存

OAuth 类型需用 api_key + secret_key 换 access_token，不能每次调用都换：

- 模块级缓存 `_oauth_cache: dict[int, _TokenEntry]`，按 `provider_id` 索引。
- `_TokenEntry` 存 `access_token` + `expires_at`。
- token 未过期直接返回缓存，否则重新换取。
- 进程重启后缓存丢失，首次调用重新换 token（可接受）。
- 二期实现，一期无 oauth 类型供应商。

### 调用方改造

| 调用方 | 旧逻辑 | 新逻辑 |
| ------ | ------ | ------ |
| `client.py` `chat_completion()` | 硬编码 `api_key` + `api_base` | `ctx = build_auth_context(provider)` -> 填入 `call_kwargs` |
| `health.py` `check_model_health()` | 硬编码 header 构造 | `ctx = build_auth_context(provider)` -> 从 `ctx.extra_headers` / `ctx.api_key` 取 |
| `service.py` `discover_models()` | 硬编码 header 构造 | `ctx = build_auth_context(provider)` -> 同上 |

---

## §9.4 模型发现

### 两条路径

| 路径 | 适用协议族 | 端点 | 响应格式 |
| ---- | ---------- | ---- | -------- |
| **A. 远程 `/models`** | OpenAI 兼容 / Ollama | `GET {base_url}/models` | `{data: [{id, object, created, owned_by}]}` |
| **B. LiteLLM 注册表 fallback** | Anthropic / Gemini / Azure / 远程不可用时 | `litellm.models_by_provider[provider.litellm_provider]` | `set[str]` |

### 流程

```
discover_models(provider_id):
  1. 按 protocol_type（litellm_provider）选择端点适配器：
     - openai / ollama -> GET {base_url}/models，解析 data[].id
     - anthropic / gemini / azure -> 跳过远程，直接用 LiteLLM 注册表
     - 远程请求失败 -> fallback 到 LiteLLM 注册表

  2. 获取模型 ID 后，构造 litellm_model = f"{litellm_provider}/{model_code}"
     交叉 LiteLLM 注册表（litellm.model_cost / litellm.get_model_info）补全：
     context_window / max_output_tokens / supports_* / input_price / output_price

  3. 与 DB 已有 model_code 比对去重，标记 already_exists

  4. 返回候选列表（不直接写 DB，由前端用户勾选后调用 create_model 批量创建）
```

### 元数据提取器（策略模式）

不同供应商的 `/models` 响应结构差异较大，通过 `get_metadata_extractor(provider)` 工厂按供应商返回对应的提取器：

| 提取器 | 适用供应商 | 数据来源 | 提取字段 |
| ------ | ---------- | -------- | -------- |
| `ArkModelMetadataExtractor` | ark / ark-plan / ark-coding-plan | 内联 `token_limits` / `features` / `modalities` / `task_type` | context_window / max_output_tokens / supports_function_calling / supports_vision / supports_reasoning / task_type |
| `OllamaModelMetadataExtractor` | ollama | `POST /api/show` 返回 `model_info` + `capabilities` | context_window / supports_function_calling / supports_vision / supports_reasoning / task_type（capabilities 映射） |
| `LlamaCppModelMetadataExtractor` | llamacpp | `/models` 内联 `meta.n_ctx` | context_window |
| `OpenAICompatModelMetadataExtractor` | DeepSeek / Qwen 等 | API 仅返回 id / object / owned_by | 全 None（回退 LiteLLM 注册表） |

**ARK 系区分逻辑**：ARK 供应商的 `litellm_provider` 为 `openai`，但 `base_url` 含 `ark`，通过检测 `base_url` 区分。

**Ollama capabilities -> task_type 映射**：

| Ollama capability | task_type |
| ----------------- | --------- |
| `completion` | `TextGeneration` |
| `embedding` | `TextEmbedding` |
| `vision` | `VisualQuestionAnswering` |
| `tools` / `thinking` | 归入 `TextGeneration` |

**合并优先级**：`merge_metadata(api_meta, litellm_info)` 按 **API 响应 > LiteLLM 注册表 > 默认值** 合并，`task_type` 仅从 API 提取，LiteLLM 注册表无此字段。

实现见 `src/llm/metadata_extractor.py`。

### 鉴权

模型发现的 HTTP 请求统一使用 `build_auth_context(provider)` 构造鉴权参数，与 `chat_completion` 共用同一套逻辑。

实现见 `src/llm/service.py` 的 `discover_models()`。

---

## §9.5 重试策略

重试策略按错误类型分类（策略模式），由 `RetryPolicyFactory` 自动选择。`provider.max_retries` 作为供应商级上限，实际重试次数取 `min(strategy_default, provider.max_retries)`。

| 错误类型 | 策略 | 默认最大次数 | 退避 |
| -------- | ---- | ----------- | ---- |
| `TIMEOUT` | 指数退避 | 3 | 1s -> 2s -> 4s |
| `RATE_LIMITED` | 指数退避 + 基础延迟 | 3 | 5s -> 10s -> 20s |
| `NETWORK` | 短退避 | 2 | 1s -> 2s |
| `SERVER_ERROR` | 指数退避 | 2 | 2s -> 4s |
| `AUTH_FAILED` | 不重试 | 0 | -- |
| `CLIENT_ERROR` | 不重试 | 0 | -- |
| `UNKNOWN` | 不重试 | 0 | -- |

实现见 `src/llm/client.py` 的 `RetryStrategy` / `RetryPolicyFactory` / `chat_completion_with_retry()`。

---

## §9.6 安全要求

- `api_key_encrypted` 和 `secret_key_encrypted` 须用 Fernet 加密存储，密钥从 `LLM_PROVIDER_ENCRYPTION_KEY` 环境变量读取（AGENTS.md 红线 #5 延伸）。
- 日志中禁止输出 `api_key_encrypted` / `secret_key_encrypted` / `header_name` / `token_url` 内容（AGENTS.md 红线 #10 延伸）。
- `last_error` 字段须脱敏后写入，移除可能包含的 API Key 片段。
- 供应商删除为软删除（`is_enabled=0`），保留历史日志引用完整性。
- 模型删除时同步软删除对应的 `kb_llm_health` 行。

---

## §9.7 LLM 调用与响应处理

> 实现见 `src/llm/client.py` / `src/llm/response.py` / `src/llm/response_extractor.py` / `src/llm/cost.py`。

### 调用入口

| 函数 | 返回类型 | 适用场景 |
| ---- | -------- | -------- |
| `chat_completion(provider, model, messages, ...)` | `LLMResponse`（非流式）/ 原始对象（流式） | 需要指定供应商/模型的精细调用 |
| `chat_completion_with_retry(provider, model, messages, ...)` | 同上 | 在 `chat_completion` 基础上增加策略重试（§9.5） |
| `quick_chat(prompt, session, ...)` | `str` | 便捷调用，自动路由 + 重试，仅需文本结果 |

**调用约定**：

- 非流式调用（`stream=False`，默认）统一返回 `LLMResponse`，调用方不再直接操作 LiteLLM 原始响应。
- 流式调用（`stream=True`）返回 LiteLLM 原始响应对象，不封装为 `LLMResponse`（流式场景需要逐 chunk 处理）。
- `quick_chat` 始终返回 `str`（从 `LLMResponse.content` 提取），适合摘要生成、标签提取等简单场景。

### LLMResponse 统一返回体

```python
@dataclass(frozen=True)
class LLMResponse:
    content: str                              # 已提取的回复文本
    usage: TokenUsage                         # Token 用量统计
    cost: CostEstimate                        # 成本估算（USD）
    model_code: str                           # 模型代码
    provider_code: str                        # 供应商代码
    latency_ms: int                           # 调用耗时（毫秒）
    raw: dict[str, Any] | object              # 原始 LiteLLM 响应（高级用途）
```

**设计要点**：

- `frozen=True`，不可变，防止调用方意外修改。
- 通过 `LLMResponse.from_litellm_response(response, model, ...)` 工厂方法构造，内部自动调用 `extract_content` + `estimate_cost`，调用方无需关心提取逻辑。
- `raw` 字段保留原始 LiteLLM 响应，供 tool_calls 解析等高级用途使用。
- `usage` 和 `cost` 在响应无 `usage` 字段或模型无定价时返回零值，不抛异常。

**调用方使用**：

```python
resp = chat_completion_with_retry(provider, model, messages, session=session)
print(resp.content)                  # "你好！"
print(resp.usage.total_tokens)       # 128
print(resp.cost.total_cost_usd)      # 0.000123
```

### 推理模型响应提取（策略模式）

不同供应商的推理模型将回复内容放在不同字段中：

| 模型类型 | 响应字段 | 示例供应商 | 提取器 |
| -------- | -------- | ---------- | ------ |
| 标准 | `message.content` | GPT-4o, DeepSeek-Chat, Ollama | `StandardExtractor` |
| 推理 | `message.reasoning_content`（`content` 为空时） | DeepSeek-R1/V4, Qwen3, Volcengine doubao | `ReasoningExtractor` |
| Thinking 块 | `message.thinking_blocks`（`content` 为空时） | Claude extended thinking | `ThinkingBlockExtractor` |

**`supports_reasoning` 字段语义**：

- `kb_llm_model.supports_reasoning`（TINYINT(1)，默认 0）标记模型是否为推理模型。
- `supports_reasoning=True` 时使用 `ReasoningExtractor`，`False` 时使用 `StandardExtractor`。
- 模型发现（`discover_models`）时优先从供应商 API 提取（ARK 的 `max_reasoning_token_length > 0`、Ollama 的 `capabilities` 含 `thinking`），API 无此字段时回退 LiteLLM 注册表的 `supports_reasoning` 布尔值。
- 手动创建模型时默认为 `False`，可由管理后台修改。

**提取策略**：

- **StandardExtractor**：直接取 `message.content`。
- **ReasoningExtractor**：`content` 非空则返回 `content`；`content` 为空则回退 `reasoning_content`。这是因为推理模型在 `max_tokens` 不足时可能仅输出 `reasoning_content` 而 `content` 为空。
- **ThinkingBlockExtractor**：`content` 非空则返回 `content`；否则从 `thinking_blocks` 列表中拼接 `thinking` 文本；最终回退 `reasoning_content`。

**统一入口**：

```python
from src.llm.response_extractor import extract_content

content = extract_content(response, model)
```

`extract_content(response, model)` 内部按 `model.supports_reasoning` 自动选择提取器，调用方无需关心字段差异。`extract_content` / `estimate_cost` 作为独立函数保留，供单元测试和 `LLMResponse.from_litellm_response` 内部调用。

### 成本估算

```python
@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

@dataclass(frozen=True)
class CostEstimate:
    usage: TokenUsage
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float
```

**定价来源**：`kb_llm_model.input_price_per_1m` / `output_price_per_1m`（每百万 token 的 USD 价格），由模型发现时从 LiteLLM 注册表自动填充，或手动配置。local 类型模型（Ollama / llama.cpp）定价为 0。

**计算公式**：

```
input_cost  = (prompt_tokens / 1,000,000) * input_price_per_1m
output_cost = (completion_tokens / 1,000,000) * output_price_per_1m
total_cost  = input_cost + output_cost
```

**精度**：成本保留 6 位小数（`round(x, 6)`）。

**使用方式**：

```python
from src.llm.cost import estimate_cost

cost = estimate_cost(response, model)
# 或通过 LLMResponse 直接访问
resp = chat_completion_with_retry(provider, model, messages)
resp.cost.total_cost_usd
```

### 模块文件索引

| 文件 | 职责 |
| ---- | ---- |
| `src/llm/client.py` | LiteLLM 封装、调用入口、重试策略、`quick_chat` |
| `src/llm/response.py` | `LLMResponse` dataclass + `from_litellm_response()` 工厂 |
| `src/llm/response_extractor.py` | 响应内容提取器（策略模式：Standard / Reasoning / ThinkingBlock） |
| `src/llm/metadata_extractor.py` | 模型元数据提取器（策略模式：Ark / Ollama / LlamaCpp / OpenAICompat）+ `merge_metadata` |
| `src/llm/cost.py` | `TokenUsage` / `CostEstimate` dataclass + `extract_usage` / `estimate_cost` |
| `src/llm/router.py` | 供应商路由（按优先级 + 健康状态选择可用供应商-模型对） |

### 公开导出

以下符号从 `src.llm` 包顶层导出（`src/llm/__init__.py`）：

- 调用入口：`chat_completion`、`chat_completion_with_retry`、`quick_chat`
- 返回体：`LLMResponse`、`TokenUsage`、`CostEstimate`
- 独立函数：`extract_content`、`estimate_cost`、`extract_usage`
- 元数据提取：`ModelMetadata`、`get_metadata_extractor`、`merge_metadata`、各提取器类
- CRUD：`batch_delete_models`
- 路由：`select_first_available`
