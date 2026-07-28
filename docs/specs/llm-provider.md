# LLM 供应商管理规范

> 本文件从 AGENTS.md §9 拆分而来，章节编号保持不变。
> 代码实现见 `src/llm/`，DDL 见 `deploy/sql/01-04_*.sql`，枚举定义见 `src/models/enums.py`。

---

## §9.1 供应商与模型

**三张表**：

| 表 | 职责 | DDL 文件 |
| -- | ---- | -------- |
| `kb_llm_provider` | 供应商配置 + 健康当前状态（内联） | `deploy/sql/01_kb_llm_provider.sql` |
| `kb_llm_model` | 模型清单（每供应商多个，`is_default` 标记默认） | `deploy/sql/02_kb_llm_model.sql` |
| `kb_llm_health_log` | 健康检查日志（append-only，定期清理） | `deploy/sql/03_kb_llm_health_log.sql` |

**枚举定义**（`src/models/enums.py`）：

| 枚举 | DB 值 | JSON 字符串 | 说明 |
| ---- | ----- | ----------- | ---- |
| `LlmProviderType` | 0/1 | `cloud`/`local` | 供应商类型 |
| `LlmAuthType` | 0/1/2/3 | `bearer`/`oauth`/`header`/`none` | 鉴权方式 |
| `LlmHealthStatus` | 0/1/2/3 | `healthy`/`degraded`/`unhealthy`/`unknown` | 健康状态 |
| `LlmModelSource` | 0/1/2 | `preset`/`discovered`/`manual` | 模型记录来源 |

**鉴权方式统一存储**：

| auth_type | `api_key_encrypted` | `auth_config` JSON | 典型供应商 |
| --------- | ------------------- | ------------------ | ---------- |
| `bearer` (0) | API Key（加密） | `null` 或 `{}` | OpenAI / DeepSeek / Ark / Qwen |
| `oauth` (1) | API Key（加密） | `{"secret_key": "enc:...", "token_url": "..."}` | 百度千帆（二期） |
| `header` (2) | API Key（加密） | `{"header_name": "x-goog-api-key"}` | Google Gemini（二期） |
| `none` (3) | `NULL` | `null` | Ollama / llama.cpp |

`api_key_encrypted` 须用 `LLM_PROVIDER_ENCRYPTION_KEY` 环境变量经 SHA-256 派生 Fernet 密钥加密存储，禁止明文入库。

**一期支持 6 家供应商**（种子数据见 `deploy/sql/04_seed_llm_providers.sql`）：

| provider_code | 类型 | auth_type | litellm_provider | base_url |
| ------------- | ---- | --------- | ---------------- | -------- |
| `ark` | cloud | bearer | `volcengine` | `https://ark.cn-beijing.volces.com/api/v3` |
| `deepseek` | cloud | bearer | `deepseek` | `https://api.deepseek.com/v1` |
| `qwen` | cloud | bearer | `openai` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `openai` | cloud | bearer | `openai` | `https://api.openai.com/v1` |
| `ollama` | local | none | `ollama` | `http://localhost:11434/v1` |
| `llamacpp` | local | none | `openai` | `http://localhost:8080/v1` |

## §9.2 路由规则与健康状态机

**路由查询**：`WHERE is_enabled=1 AND health_status != unhealthy ORDER BY priority, id`。unhealthy 供应商被自动跳过，degraded 仍可尝试。路由实现见 `src/llm/router.py`。

**健康状态机**（类熔断器，实现见 `src/llm/health.py`）：

```
UNKNOWN ──首次检查──▶ HEALTHY
HEALTHY ──失败 1 次──▶ DEGRADED
DEGRADED ──失败达 threshold──▶ UNHEALTHY
UNHEALTHY ──健康检查成功──▶ HEALTHY
任意状态 ──成功──▶ HEALTHY（consecutive_failures 归零）
```

- 所有状态转换使用 CAS（`UPDATE ... WHERE id=? AND health_status=?`）保证并发安全。
- `failure_threshold` 按供应商可配（local 类型建议设高阈值）。
- unhealthy 供应商仅通过定时健康检查恢复，不接受业务调用自愈。
- 健康检查日志写入 `kb_llm_health_log`（append-only），不随业务调用频率膨胀。

## §9.3 模型发现

通过 `GET {base_url}/models` 获取模型 ID 列表，交叉 LiteLLM 注册表（`litellm.model_cost` / `litellm.get_model_info`）补全 `context_window` / `supports_function_calling` / `supports_vision` / 定价等元数据。未命中的模型字段留默认值，`source=discovered`，前端提示用户补全。发现结果不直接写 DB，由前端用户勾选后调用 `create_model` 批量创建。实现见 `src/llm/service.py` 的 `discover_models()`。

## §9.4 安全要求

- `api_key_encrypted` 须用 Fernet 加密存储，密钥从 `LLM_PROVIDER_ENCRYPTION_KEY` 环境变量读取（AGENTS.md 红线 #5 延伸）。
- 日志中禁止输出 `api_key` / `auth_config` 内容（AGENTS.md 红线 #10 延伸）。
- `last_error` 字段须脱敏后写入，移除可能包含的 API Key 片段。
- 供应商删除为软删除（`is_enabled=0`），保留历史日志引用完整性。
