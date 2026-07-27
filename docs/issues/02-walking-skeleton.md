# 02 - 骨架：LangGraph 四节点脊柱 + 依赖容器 + CLI

> 对应 GitHub Issue: [#5](https://github.com/ryea0/ai-knowledge-base/issues/5)

## 要构建什么

搭建 LangGraph 状态机骨架，供真实的 collector/analyzer/organizer 节点后续填充。本切片交付单一的测试接缝（graph 的 `run()` 入口），通过依赖容器串联，stub 节点能端到端传递有类型的载荷。此时不做真实的 HTTP 或 LLM 调用——仅验证脊柱与注入点。

定义 graph 状态对象（候选列表、原始文件路径、分析结果、最终条目记录）、4 节点串行拓扑（`collect -> persist_raw -> analyze -> organize`）、持有 HTTP fetcher / LLM client / `ArticleRepository` 协议的 `Deps` 容器，以及 CLI 分发至 `graph.run()`。端到端 stub 测试证明 fakes 能流经每个节点。

## 验收标准

- [ ] `src/graph/` 定义 LangGraph 串行状态机，恰好 4 个节点：`collect`、`persist_raw`、`analyze`、`organize`（3 个 Agent 节点 + 1 个 graph 层持久化节点，G4）
- [ ] Graph 状态对象持有：候选列表、原始文件路径、分析结果、最终条目记录——有类型的载荷在节点间流转
- [ ] `persist_raw` 是 graph 层步骤（非 Agent）——是 `src/graph/` 中的普通 Python 函数，因 collector 无写权限而由节点调用
- [ ] `Deps` 依赖容器已定义（HTTP fetcher 协议、LLM client 协议、`ArticleRepository`）；生产装配与测试 fake 在 `run()` 时可切换
- [ ] Graph 节点是普通 Python 函数，调用 `src/collectors/` / `src/analyzers/` / `src/organizers/` 中的业务逻辑——**不通过** OpenCode subagent 运行时执行（G5）
- [ ] 每个节点在交给下一阶段前，通过工单 01 的 Pydantic schema 验证其输出
- [ ] `src/main.py --stage` 选项更新为 `collect | analyze | organize | render-md | all`（G14：`curate` 改名 `organize`；G7：新增 `render-md`）；`all` 分发至 `graph.run()`
- [ ] `--stage all` 以 stub 节点（无真实 I/O）端到端运行 4 节点 graph 并返回成功摘要
- [ ] `tests/graph/test_pipeline.py` 端到端 stub 测试：向 `Deps` 注入 fakes，运行 `graph.run()`，断言 graph 完成且 stub 记录出现在状态中——建立主测试接缝
- [ ] `tests/` 目录结构按 §2.2 规则 2 镜像 `src/`
- [ ] `uv run ruff check src/ tests/` 通过
- [ ] `uv run mypy src/` 通过

## 被阻塞

- [#4](./01-foundation.md)（基础设施：数据契约 + 持久化协议 + 配置）——需要 Pydantic schema、`ArticleRepository` 协议和 `Deps` 形态的配置来接线脊柱。

---

*tracer-bullet 骨架切片。在任何真实 I/O 落地之前，验证编排脊柱与单一测试接缝。*
