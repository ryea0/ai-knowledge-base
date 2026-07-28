-- 一期 6 家供应商种子数据 + 代表性模型
-- 注意：api_key_encrypted 此处为空，部署后由管理后台或脚本填入加密后的凭证
-- 文件命名按执行顺序：01/02/03 为建表，04 为种子数据

INSERT INTO kb_llm_provider
    (provider_code, display_name, provider_type, base_url, litellm_provider, auth_type, priority, timeout_seconds)
VALUES
    ('ark',       '字节火山引擎',    0, 'https://ark.cn-beijing.volces.com/api/v3',           'volcengine', 0, 10,  30),
    ('deepseek',  'DeepSeek',       0, 'https://api.deepseek.com/v1',                        'deepseek',   0, 20,  30),
    ('qwen',      '阿里百炼',        0, 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'openai',     0, 30,  30),
    ('openai',    'OpenAI',         0, 'https://api.openai.com/v1',                          'openai',     0, 40,  30),
    ('ollama',    'Ollama (本地)',   1, 'http://localhost:11434/v1',                          'ollama',     3, 50, 120),
    ('llamacpp',  'llama.cpp',      1, 'http://localhost:8080/v1',                           'openai',     3, 60, 120)
ON DUPLICATE KEY UPDATE display_name = VALUES(display_name);

-- 模型种子数据（provider_id 通过子查询关联，避免硬编码 id）
INSERT INTO kb_llm_model
    (provider_id, model_code, litellm_model, display_name, context_window, max_output_tokens,
     supports_streaming, supports_function_calling, supports_vision,
     input_price_per_1m, output_price_per_1m, is_default, source)
SELECT p.id, m.model_code, m.litellm_model, m.display_name, m.context_window, m.max_output_tokens,
       m.supports_streaming, m.supports_function_calling, m.supports_vision,
       m.input_price_per_1m, m.output_price_per_1m, m.is_default, 0
FROM (
    SELECT 'ark'       AS code, 'doubao-1-5-pro-32k'     AS model_code, 'volcengine/doubao-1-5-pro-32k'     AS litellm_model, 'Doubao 1.5 Pro 32K'   AS display_name, 32000  AS context_window, 4096 AS max_output_tokens, 1 AS supports_streaming, 1 AS supports_function_calling, 1 AS supports_vision, 0.1100 AS input_price_per_1m, 0.2800 AS output_price_per_1m, 1 AS is_default
    UNION ALL SELECT 'ark',       'doubao-1-5-lite-32k',    'volcengine/doubao-1-5-lite-32k',    'Doubao 1.5 Lite 32K',  32000, 4096, 1, 0, 0, 0.0300, 0.0700, 0
    UNION ALL SELECT 'deepseek',  'deepseek-chat',           'deepseek/deepseek-chat',            'DeepSeek-V3',          64000,  8192, 1, 1, 0, 0.2700, 1.1000, 1
    UNION ALL SELECT 'deepseek',  'deepseek-reasoner',       'deepseek/deepseek-reasoner',        'DeepSeek-R1',          64000,  8192, 1, 0, 0, 0.5500, 2.1900, 0
    UNION ALL SELECT 'qwen',      'qwen-max',                'openai/qwen-max',                   'Qwen-Max',             32768,  8192, 1, 1, 0, 2.7600, 8.2800, 1
    UNION ALL SELECT 'qwen',      'qwen-plus',               'openai/qwen-plus',                  'Qwen-Plus',            131072, 8192, 1, 1, 0, 0.4200, 1.2600, 0
    UNION ALL SELECT 'openai',    'gpt-4o',                  'openai/gpt-4o',                     'GPT-4o',               128000, 16384, 1, 1, 1, 2.5000, 10.0000, 1
    UNION ALL SELECT 'openai',    'gpt-4o-mini',             'openai/gpt-4o-mini',                'GPT-4o mini',          128000, 16384, 1, 1, 1, 0.1500, 0.6000, 0
    UNION ALL SELECT 'ollama',    'llama3.2',                'ollama/llama3.2',                   'Llama 3.2 3B',         4096,   4096, 1, 0, 0, 0.0000, 0.0000, 1
    UNION ALL SELECT 'ollama',    'qwen2.5:7b',              'ollama/qwen2.5:7b',                 'Qwen2.5 7B',           4096,   4096, 1, 0, 0, 0.0000, 0.0000, 0
    UNION ALL SELECT 'llamacpp',  'local-model',             'openai/local-model',                'Local Model',          4096,   4096, 1, 0, 0, 0.0000, 0.0000, 1
) AS m
JOIN kb_llm_provider p ON p.provider_code = m.code
ON DUPLICATE KEY UPDATE display_name = VALUES(display_name);
