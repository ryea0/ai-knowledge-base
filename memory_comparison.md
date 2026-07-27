# Memory 对比：有 AGENTS.md 规范 vs 无规范

以同一功能（GitHub 仓库信息查询）的两个实现为样本：

- **无 Memory**：`src/utils/github_repo_info.py` -- 未遵循 AGENTS.md 规范
- **有 Memory**：`src/utils/github_api.py` -- 严格遵循 AGENTS.md 规范

---

## 五维度对比

| 维度 | 无 Memory（`github_repo_info.py`） | 有 Memory（`github_api.py`） |
| --- | --- | --- |
| **命名风格** | URL 硬编码在函数体内（`f"https://api.github.com/..."`），无常量命名；文件名以单函数名命名（`github_repo_info`），扩展性差 | API 地址提取为模块级常量 `GITHUB_API_BASE`（`UPPER_SNAKE_CASE`）；文件名 `github_api` 以模块职责命名，可承载多个 API 函数 |
| **docstring** | 无模块级 docstring；函数 docstring 简略，`Returns` 仅写"包含……等字段的字典"，返回结构不明确；`Raises` 只列了 `requests.HTTPError`，未说明触发条件 | 有模块级 docstring（`"""GitHub API 工具模块……"""`）；函数 docstring 详尽，说明 API 端点、`GITHUB_TOKEN` 环境变量行为；`Returns` 逐键列出 `stars`/`forks`/`description` 及类型；`Raises` 列出 `ValueError`/`RuntimeError` 及精确触发条件 |
| **日志方式** | 函数内无任何日志；`__main__` 块用 `print()` 输出结果（违反红线第 4 条）；无 `logging.getLogger` 声明 | 模块顶部声明 `logger = logging.getLogger(__name__)`；用 `logger.error("…%s", err)` 延迟格式化（遵守 §2.3 规则 12）；成功路径用 `logger.info()` 记录关键信息；无 `print()` |
| **错误处理** | 无参数校验；仅 `resp.raise_for_status()` 原样抛出 `HTTPError`，无异常捕获、无上下文、无异常链；调用方需自行猜测失败原因 | 入参校验 `raise ValueError`（规则 6）；`try` 块仅包裹网络调用（规则 9）；分别捕获 `HTTPError`/`URLError`/`JSONDecodeError` 三种具体异常（规则 8）；重新抛出用 `raise RuntimeError(...) from exc` 保留异常链（规则 10）；捕获后先 `logger.error()` 再抛出 |
| **文件位置** | 文件虽在 `src/utils/` 下，但混入了 `if __name__ == "__main__"` 入口逻辑和 `print` 输出，工具模块与入口脚本职责混淆；依赖第三方库 `requests`（未确认项目是否已声明依赖） | 纯工具模块，无入口逻辑，职责单一；仅使用标准库 `urllib`/`json`/`logging`/`os`，无外部依赖风险；与 `__init__.py` 配合构成 `src.utils` 包 |

---

## 结论

两个文件功能完全相同，但代码质量差距显著。**无 Memory** 版本是一段"能跑就行"的脚本：硬编码 URL、`print` 调试、异常裸抛、docstring 含糊，混入入口逻辑使模块无法被其他代码安全复用。**有 Memory** 版本在 AGENTS.md 规范约束下，每个维度都做到了工程化标准——常量提取、日志延迟格式化、异常分层捕获与链式保留、docstring 精确到每个返回字段、模块职责单一。这证明 AGENTS.md 作为"项目记忆"的核心价值：**它不是文档，而是 AI 生成代码时的强制约束层**，将一次性的"能跑"代码提升为可维护、可测试、可复用的工程代码。对于多 Agent 协作场景，这种约束尤为关键——没有统一规范，各 Agent 产出的代码无法组合；有了规范，代码天然具备一致性。
