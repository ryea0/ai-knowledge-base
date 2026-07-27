# 07 - 韧性与幂等性加固

> 对应 GitHub Issue: [#10](https://github.com/ryea0/ai-knowledge-base/issues/10)

## 要构建什么

加固现已完整的流水线以应对局部失败，使单条坏数据不会污染整批、且重跑安全。为每个阶段的逐条处理包裹 try/except 隔离，新增批末成功/跳过/失败汇总，实现 persist_raw 占位行回滚（raw MD 写入失败时删除 DB 行），并端到端验证重跑幂等性。

本切片交付容错的全流水线：单个坏链接、LLM 超时或 DB 冲突不再中止当日运行。

## 验收标准

- [ ] collect、analyze、organize 阶段逐条 try/except 隔离：失败条目记 `logger.exception`（含 article_id/url 上下文，**无密钥**）并跳过；批次继续（AC 39/40/41）
- [ ] 每节点批末 `INFO` 汇总："成功 N / 跳过 M / 失败 K"（AC 42）
- [ ] **persist_raw 占位行回滚**（G12）：DB INSERT/UPDATE commit 后若 raw MD 写入失败，**删除**占位 DB 行，确保无半成品行残留；raw MD（若已部分写入）按 raw 只追加规则保留；重跑时重新插入占位行
- [ ] analyzer/organizer 失败时占位行保留不动（status=pending）--**不删除**，因其 `source_url` 已占位可阻止重复采集；通过重试或人工介入恢复（§4.7）
- [ ] 不新增失败态（§4.7）--失败条目留在当前状态并记 ERROR 日志
- [ ] 验证重跑幂等性：对相同数据运行 `--stage all` 两次，不产生重复条目（collector `get_by_url` 跳过已存在；CAS 更新守护状态转换）
- [ ] Graph 测试覆盖边界用例：空采集（0 候选）、全失败批次（每条出错但批次完成）、全重复批次（每个 URL 已存在）、占位行回滚（raw 写入失败 -> 无残留 DB 行）（AC 见 §5.2）
- [ ] `uv run ruff check src/ tests/` 通过
- [ ] `uv run mypy src/` 通过

## 被阻塞

- [#8](./05-organize-stage.md)（整理阶段）--加固包裹的是完整的 collect->persist_raw->analyze->organize 链路，该链路仅在整理切片落地后才存在。

---

*tracer-bullet 韧性切片。使流水线对无人值守的 CronJob 运行具备生产安全性。*
