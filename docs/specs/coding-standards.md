# 编码标准（Coding Standards）

> 本文件从 AGENTS.md §2.3 / §2.4 拆分而来，章节编号保持不变。

---

## §2.3 Python 编码细则（基于 Google Style Guide 精简）

> 以下 20 条规则提炼自 [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)，AI 生成代码时须逐条遵守。

### 命名（Naming）

1. **命名风格**：模块/文件用 `snake_case`；包名用全小写无下划线；类用 `PascalCase`；函数/变量用 `snake_case`；常量用 `UPPER_SNAKE_CASE`。内部成员以 `_` 前缀标识。
2. **避免歧义命名**：禁止单字母 `l`、`O`、`I`（与 `0`/`1` 混淆）；循环计数器可用 `i`/`j`/`k`。命名须具描述性，避免无意义缩写（通用术语 `url`/`http` 除外）。
3. **异常命名**：自定义异常类名以 `Error` 结尾，须继承已有异常基类，避免 `FooModule.FooError` 式重复前缀。
4. **可见性约定**：受保护成员用 `_name`；**禁止**用 `__name` 双下划线触发名称改写（除非需严格防止子类覆盖）。模块级私有常量用 `_MAX_VALUE` 格式。
5. **避免可变默认参数**：函数默认值禁止使用 `list`/`dict`/`set` 等可变对象，须用 `None` 哨兵并在函数体内初始化。

### 异常处理（Exceptions）

6. **优先内置异常**：参数校验失败用 `ValueError`，类型错误用 `TypeError`，运行时状态异常用 `RuntimeError`。仅在内置异常无法表达语义时自定义。
7. **禁止 assert 替代校验**：`assert` 仅用于不可达路径的内部不变式断言，**不可**用于参数校验或业务逻辑（测试代码除外）。`assert` 在 `-O` 模式下会被移除。
8. **禁止裸 except**：禁止 `except:` 或 `except Exception:` 捕获全部异常，除非在该块内重新 `raise` 或位于线程最外层隔离点。须捕获具体异常类型。
9. **try 块最小化**：仅包裹可能抛出异常的具体语句，禁止大段代码包裹在 `try` 中。资源清理统一用 `finally` 或上下文管理器（`with` 语句）。
10. **异常链保留**：重新抛出异常时必须用 `raise NewError(...) from exc` 保留原始 traceback，禁止裸 `raise NewError(...)` 丢失上下文。

### 日志（Logging）

11. **日志器规范**：每个模块顶部声明 `logger = logging.getLogger(__name__)`，禁止 `print()`，禁止 `logging.basicConfig()` 在库代码中调用（仅入口脚本可配置）。
12. **延迟格式化**：日志消息用 `%s` 占位符 + 参数传递（如 `logger.error("失败: %s", err)`），**禁止** f-string / `.format()` / `+` 拼接（无法利用级别过滤跳过格式化开销）。
13. **日志级别约定**：`DEBUG` = 详细的变量值/调用栈；`INFO` = 关键流程节点（采集开始/分析完成/发布成功）；`WARNING` = 可恢复的降级行为（重试、跳过）；`ERROR` = 操作失败但系统可继续；`CRITICAL` = 系统不可用。生产环境默认 `INFO`。
14. **异常日志规范**：`except` 块内**必须**使用 `logger.exception("描述")` 或 `logger.error("描述", exc_info=True)` 附加完整 traceback，**禁止**仅记录 `str(exc)` 丢失调用栈（兜底隔离点除外）。日志须包含操作上下文（模块名、操作类型、关键标识），但**禁止输出** API Key / Token / 密码等敏感字段。外部异常消息（httpx / requests 等）入库前须经脱敏处理（如 `src/llm/client.py` 的 `_sanitize_error()`），`health.py` / `service.py` 等模块的 `last_error` 字段写入时**必须调用同一脱敏函数**，禁止直接截断入库。

### 并发（Concurrency）

15. **禁止依赖内置类型原子性**：`dict`/`list` 的操作不保证线程安全（`__hash__`/`__eq__` 可被重写），多线程共享可变数据必须显式加锁或使用 `queue.Queue`。
16. **线程池优先**：并发任务优先使用 `concurrent.futures.ThreadPoolExecutor`（I/O 密集）或 `ProcessPoolExecutor`（CPU 密集），禁止裸 `threading.Thread` 创建不受管理的线程。
17. **锁粒度最小化**：临界区内只做内存操作，**禁止**在持锁状态下执行 I/O（网络请求、文件读写、`time.sleep`），避免死锁。优先使用 `threading.Condition` 进行线程间协调。
18. **异步不混用**：`asyncio` 事件循环内禁止直接调用阻塞 I/O；须用 `asyncio.to_thread()` 或 `run_in_executor()` 桥接。禁止在同一个事件循环中混用 `threading.Lock` 与 `asyncio.Lock`。
19. **全局可变状态禁令**：模块级可变变量（全局 list/dict/连接池）须避免。确需共享时，用 `threading.local()` 隔离或显式锁保护，并在声明处注释说明设计原因。
20. **资源释放保证**：线程/进程池须用 `with` 语句管理生命周期；`Queue` / `Lock` / `Semaphore` 等同步原语在异常路径下须通过 `finally` 释放，禁止遗漏导致资源泄漏。

---

## §2.4 环境变量约定

所有密钥与外部服务配置须通过环境变量读取（`.env` 文件已 gitignore，不入库），禁止硬编码。命名规则：`<服务>_<用途>`，全大写 `SNAKE_CASE`。新增变量须同步更新下表与 `.env.example`。

| 变量名                      | 用途                          | 必填 | 示例 / 默认              |
| --------------------------- | ----------------------------- | ---- | ------------------------ |
| `MYSQL_HOST`                | MySQL 主机                    | 是   | `127.0.0.1`              |
| `MYSQL_PORT`                | MySQL 端口                    | 否   | `3306`                   |
| `MYSQL_USER`                | MySQL 用户名                  | 是   | `kb_app`                 |
| `MYSQL_PASSWORD`            | MySQL 密码                    | 是   |                          |
| `MYSQL_DATABASE`            | MySQL 库名                    | 是   | `ai_knowledge_base`      |
| `LLM_PROVIDER_ENCRYPTION_KEY` | LLM 供应商 API Key 加密主密钥 | 是   | 任意 passphrase，SHA-256 派生 Fernet 密钥 |
| `LLM_DEFAULT_PROVIDER_CODE` | 启动时默认供应商代码          | 否   | `deepseek`               |
| `LLM_API_KEY`               | （废弃）单供应商 API Key，保留向后兼容 | 否   |                          |
| `LLM_API_BASE`              | （废弃）单供应商端点，保留向后兼容     | 否   | 国产模型默认端点         |
| `LLM_MODEL`                 | （废弃）单供应商模型名，保留向后兼容   | 否   | `doubao-pro`             |
| `TELEGRAM_BOT_TOKEN`        | Telegram Bot Token            | 否\* | 未配置则跳过该渠道       |
| `FEISHU_WEBHOOK_URL`        | 飞书 Webhook 地址             | 否\* | 未配置则跳过该渠道       |
| `GITHUB_TOKEN`              | GitHub API Token（提升限速）  | 否   | 未配置走匿名（限速更低） |

\* `TELEGRAM_BOT_TOKEN` 与 `FEISHU_WEBHOOK_URL` 至少配置一个，否则分发无可用渠道。

DB 连接串须由上述字段拼装（`mysql+pymysql://{user}:{password}@{host}:{port}/{database}`），禁止用单一 `DATABASE_URL` 混合拼接。
