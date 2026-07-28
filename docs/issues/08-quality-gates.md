# 08 - 质量门：80% 覆盖率、lint、mypy strict、边界用例

> 对应 GitHub Issue: [#11](https://github.com/ryea0/ai-knowledge-base/issues/11)

## 要构建什么

通过清除全部三个项目强制质量门（`ruff`、`mypy strict`、`pytest --cov-fail-under=80`）并补齐覆盖率暴露的剩余测试缺口，来收尾流水线。这是验证切片，证明整条流水线可交付。

## 验收标准

- [ ] `uv run ruff check src/ tests/` 干净通过
- [ ] `uv run mypy src/` 干净通过（strict 模式）
- [ ] `uv run pytest tests/ --cov=src --cov-fail-under=80` 通过，覆盖率 ≥ 80%
- [ ] 补齐覆盖率缺口：低于阈值的模块补充测试（优先 `src/graph/`、`src/collectors/`、`src/analyzers/`、`src/organizers/`、`src/config/`、`src/utils/http_client.py`）
- [ ] 测试套件覆盖 pipeline-design.md §8 完整的 Definition of Done 清单：
  - [ ] 4 节点 graph 端到端运行（G4）
  - [ ] persist_raw 取号前置（G1）
  - [ ] 产出 JSON sidecar + MD + DB 行
  - [ ] 新条目 `status: pending`，含 §4 全字段 + score/highlights/score_reason
  - [ ] 写入顺序 DB -> JSON -> MD；MD 失败不回滚 DB/JSON（G7）
  - [ ] 通过 source_url 实现重跑幂等（G2）
  - [ ] 逐条失败隔离 + 批末汇总 + 占位行回滚（G12）
  - [ ] 每次交接通过 Pydantic 验证；旧文件容错（G9）
  - [ ] HTTP 速率限制 + 退避 + 并发 ≤5 + 超时 30s/10min；统一 httpx（G10）
  - [ ] 密钥仅来自环境变量；日志无密钥
  - [ ] DDL 扩展 3 列，无 score 索引（G8）
  - [ ] CAS 条件更新
  - [ ] Jaccard ≥0.8 标题去重，保留 source_score 最高，其余 archived（G6）
  - [ ] `--stage` 含 organize（非 curate）与 render-md（G7/G14）
- [ ] 无回归：此前通过的测试仍全部通过
- [ ] 所有公开函数有完整类型注解（红线第 6 条）

## 被阻塞

- [#9](./06-render-md-and-docs.md)（render-md + Agent 文档对齐）--覆盖率度量仅在容错路径存在后才有意义。
- [#10](./07-resilience.md)（韧性与幂等性加固）--最终的 CLI 表面与文档驱动的行为必须就位后，才能断言完整 DoD 覆盖。

---

*tracer-bullet 质量切片。变绿工单--证明流水线达到项目的交付门槛。*
