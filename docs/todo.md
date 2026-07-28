# P0 待办（业务跑不通，必须先做）

- [x] 1. kb_article DDL + ORM + Schema
- [ ] 2. Article Service 层（CRUD + 状态流转 CAS + DB->JSON 双写）
- [ ] 3. trace.py + logging 配置（traceId 基础设施，AGENTS.md §10.7 T-01~T-10）
- [ ] 4. 统一 HTTP 客户端（含重试/限流/超时，src/utils/http_client.py）

# P1 待办（核心业务链路）

- [ ] 5. GitHub Trending 采集器（src/collectors/github_trending.py）
- [ ] 6. HackerNews 采集器（src/collectors/hackernews.py）
- [ ] 7. LLM 分析器（src/analyzers/llm_analyzer.py）
- [ ] 8. Article Organizer（src/organizers/article_organizer.py）
- [ ] 9. Telegram 分发器（src/distributors/telegram.py）
- [ ] 10. 飞书分发器（src/distributors/feishu.py）
- [ ] 11. 工作流节点实现（src/graph/nodes.py 填充真实逻辑）

# P2 待办（前端可用的 API）

- [ ] 12. API 路由（articles / llm / workflow / distributors，src/api/）
- [ ] 13. CORS + traceId 中间件
- [ ] 14. 统计 API + 缓存

# P3 待办（增强能力）

- [ ] 15. ChromaDB 语义去重
- [ ] 16. 工作流执行历史表 + 分发历史表
- [ ] 17. LLM 调用计量
