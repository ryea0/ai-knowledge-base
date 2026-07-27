# 04 - 分析阶段：LLM analyzer + README 分支容错

> 对应 GitHub Issue: [#7](https://github.com/ryea0/ai-knowledge-base/issues/7)

## 要构建什么

实现 analyzer 节点：读取每份 `knowledge/raw/<article_id>.md`，调用 LLM（OpenAI 兼容 API，环境变量驱动）生成中文摘要、1-3 条含具体数据的亮点、1-10 评分及评分理由、3-8 个小写标签、分类，并识别原文语言。输出为经验证的 `AnalyzerResult`，保留在 graph 状态中（不写磁盘--analyzer 为只读）。包含 sub-agent 测试日志（P2）标记为阻塞项的 README `main`->`master` 分支容错。

本切片交付完整的分析路径：raw MD 输入 -> 状态中经验证的分析 JSON，可通过运行 `--stage analyze` 处理采集切片产出的 raw 文件并检查分析结果来演示。

## 验收标准

- [ ] `src/analyzers/` 实现通过 OpenAI 兼容 API 的 LLM 调用，使用 `LLM_API_KEY` / `LLM_API_BASE` / `LLM_MODEL` 环境变量（§4.15）；client 通过 `Deps` 注入以便测试
- [ ] Prompt 由 raw MD 内容 + 规范要求构造（摘要 2-4 句、≤150 字中文；亮点 1-3 条含具体数据；评分 1-10 含理由，按 §3.4 评分标准；标签 3-8 个小写；分类枚举；语言 zh/en）
- [ ] LLM JSON 响应解析并验证为 `AnalyzerResult`（Pydantic）；字段不合法（摘要过长、标签数量不符、评分超范围、分类错误）记 WARNING 并跳过该条
- [ ] **README 分支容错**（sub-agent 测试日志 P2）：抓取 README/内容时自动先尝试 `main` 再尝试 `master` 分支，单分支 404 不阻塞分析
- [ ] analyzer 从 `knowledge/raw/<article_id>.md` 读取，将 `AnalyzerResult` 写入 graph 状态（不写磁盘--只读权限模型）
- [ ] `--stage analyze` 运行 analyzer 节点处理 raw 文件，将分析结果填入状态
- [ ] Graph 测试（扩展 `tests/graph/test_pipeline.py`），用 LLM client fake 覆盖：正常响应、字段不合法响应（跳过）、超时（跳过）；断言有效结果进入状态且字段 shape 正确
- [ ] 日志中无密钥；LLM key 绝不记入日志（红线第 10 条）
- [ ] `uv run ruff check src/ tests/` 通过
- [ ] `uv run mypy src/` 通过

## 被阻塞

- [#5](./02-walking-skeleton.md)（骨架）--需要 graph 脊柱、`Deps` 容器（LLM client 协议）和 `AnalyzerResult` schema 来接线 analyzer 节点。

---

*tracer-bullet 分析切片。贯穿 LLM 客户端 + prompt + 验证 + 分支容错--一条完整的"raw MD 到分析 JSON"路径。*
