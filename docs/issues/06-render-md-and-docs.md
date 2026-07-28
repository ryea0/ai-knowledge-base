# 06 - render-md 阶段 + Agent 文档对齐

> 对应 GitHub Issue: [#9](https://github.com/ryea0/ai-knowledge-base/issues/9)

## 要构建什么

新增 `--stage render-md` 重建路径（从 JSON sidecar 重建 Markdown 视图，不触碰 DB），并对齐文档制品与已实现的行为：三个 `.opencode/agents/*.md` 角色定义（organizer 现输出 MD + JSON sidecar + DB 行；collector 覆盖 GitHub Trending 与 Hacker News 双数据源），以及 docs/specs/article-format.md §4 / docs/specs/db-conventions.md §7.5 的 schema 扩展（本 Spec 授权的三个分析深度列）。

本切片交付最终的 CLI 阶段，并消除文档与代码的漂移，使 prompt 与实现一致。

## 验收标准

- [ ] `--stage render-md` 读取 `knowledge/articles/<article_id>.json` sidecar，从中重新生成 `knowledge/articles/<article_id>.md`（G7）；不触碰 DB 或 JSON sidecar
- [ ] MD 重建幂等：运行 `render-md` 两次产出完全相同的 MD 文件
- [ ] 单条条目 MD 渲染失败不中断整批（与逐条隔离一致）
- [ ] CLI `--stage` 选项最终定稿：`collect | analyze | organize | render-md | all`（G7/G14）；移除 `curate`
- [ ] `.opencode/agents/collector.md` 更新：文档说明 GitHub Trending 与 Hacker News 均为一等数据源；权限模型不变（read/grep/glob/webfetch 允许；write/edit/bash 禁止）；输出契约不变（候选 JSON 数组）
- [ ] `.opencode/agents/analyzer.md` 更新：权限模型不变（只读）；输出契约不变；文档说明 README main->master 容错行为
- [ ] `.opencode/agents/organizer.md` 更新：**输出契约变更**--organizer 现交付 Markdown 文件 + JSON sidecar + DB 行（不再仅 JSON）；权限模型不变（read/grep/glob/write/edit 允许；webfetch/bash 禁止）；文件命名更新为 `<article_id>.json` / `<article_id>.md`（不再用 `{date}-{source}-{slug}`）
- [ ] `docs/specs/article-format.md` §4 更新以记录双输出决策（JSON source of truth + MD 渲染视图）及 `score` / `highlights` / `score_reason` 扩展字段（§4.10）；docs/specs/db-conventions.md §7.5 DDL 更新以包含三个新列；**不为 score 新建索引**（G8）--此编辑由 pipeline-design.md §4.10/§7 授权（红线第 12 条例外）
- [ ] 工单 01 中已扩展的 `init.sql` 与此处 docs/specs/db-conventions.md §7.5 更新保持一致
- [ ] Graph 测试覆盖 `render-md`：给定 JSON sidecar，MD 文件以正确结构重新生成；MD 不纳入 DB/JSON 一致性校验（G7）
- [ ] `uv run ruff check src/ tests/` 通过
- [ ] `uv run mypy src/` 通过

## 被阻塞

- [#8](./05-organize-stage.md)（整理阶段）--`render-md` 从 organizer 首次写入的 JSON sidecar 重建；文档更新描述的是工单 8 实现的 organizer 行为。

---

*tracer-bullet 文档+渲染切片。闭合 CLI 表面，使 prompt/spec 与已交付的流水线对齐。*
