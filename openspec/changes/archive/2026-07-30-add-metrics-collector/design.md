## Context

The metrics collection layer is fully implemented: `MetricsCollector` in `src/graph/metrics.py` writes to `kb_pipeline_run` and `kb_node_metric` tables; `write_call_log` in `src/llm/log_call.py` writes to `kb_llm_call_log`. DDL exists (`deploy/sql/10_kb_pipeline_metrics.sql`, `deploy/sql/08_kb_llm_call_log.sql`). The workflow wires all 7 nodes with `with_metrics` decorators and calls `collector.persist()` in a `finally` block.

The read side is entirely missing -- no API endpoint reads from these tables, and the frontend has no metrics page. The existing API has one router (`src/api/llm_routes.py`, prefix `/llm`) and inline health routes in `app.py`. The frontend has 7 views with a sidebar layout in `DefaultLayout.vue`.

## Goals / Non-Goals

**Goals:**
- Expose 4 read-only REST endpoints under `/api/metrics/` that query existing tables
- Build a `/metrics` frontend dashboard with summary cards, runs table (drill-down), and cost breakdown
- Follow existing project patterns: `Result[T]`/`PageResult[T]` envelope, Pydantic schemas, service layer, Element Plus components
- Zero DDL changes, zero modifications to workflow/collection/LLM code

**Non-Goals:**
- Real-time streaming (WebSocket/SSE) -- out of scope per PRD
- Alerting or budget threshold notifications
- Data TTL/cleanup jobs
- Prometheus/Grafana integration
- Modifying the metrics collection layer (`src/graph/metrics.py`)

## Decisions

### D1: Router module location -- `src/api/metrics_routes.py`

**Decision:** Create `src/api/metrics_routes.py` with `APIRouter(prefix="/api/metrics", tags=["指标监控"])`, registered in `app.py` via `app.include_router(metrics_router)`.

**Rationale:** Follows the existing pattern (`llm_routes.py` is at `src/api/llm_routes.py`). Keeps all API routers in one directory. The `/api/` prefix is included in the router prefix (not just `/metrics`) because the frontend axios `baseURL` is `/api` -- the router must match the full path the frontend sends.

**Alternative considered:** Placing routes under `src/metrics/` as a self-contained module. Rejected because the project convention puts all API route files in `src/api/`.

### D2: Service layer -- `src/api/metrics_service.py` (co-located with router)

**Decision:** Put query logic in `src/api/metrics_service.py` rather than a new `src/services/` directory. The service functions take a `Session` parameter and return Pydantic schema objects, matching the `src/llm/service.py` pattern.

**Rationale:** The project has no `src/services/` directory; service logic lives alongside its domain (e.g., `src/llm/service.py`). Co-locating with the router in `src/api/` keeps the metrics feature self-contained without creating a new top-level directory.

**Alternative considered:** `src/metrics/service.py`. Rejected because there's no `src/metrics/` package and creating one would fragment the API layer across directories.

### D3: Pydantic schemas -- `src/api/metrics_schemas.py`

**Decision:** Define request/response Pydantic models in `src/api/metrics_schemas.py`, following the `src/llm/schemas.py` pattern.

**Schemas:**
- `RunSummaryResponse`: flat run fields (id, trace_id, status, counts, cost, etc.)
- `RunDetailResponse`: extends `RunSummaryResponse` with `nodes: list[NodeMetricResponse]`
- `NodeMetricResponse`: node_name, duration_ms, cost_data, review_passed, iteration, error, created_at
- `DailySummary`: date, run_count, success_count, source_count, article_count, saved_count, review_passed_count, total_cost_yuan
- `SummaryResponse`: daily list + totals object
- `LlmCostItem`: provider_id, provider_code, model_id, model_code, call_count, success_count, token totals, total_cost, currency
- `LlmCostResponse`: items list + grand_total object

### D4: Query strategy for summary aggregation -- SQL GROUP BY in DB

**Decision:** For `GET /api/metrics/summary`, use SQL `GROUP BY DATE(started_at)` aggregation rather than loading all runs into Python and aggregating in-memory.

**Rationale:** With ~20 articles/day and 1 run/day, the data volume is small enough that either approach works. However, SQL aggregation is the idiomatic approach, avoids transferring unnecessary columns, and scales better if run frequency increases. Days with no runs are filled in Python by generating the full date range and left-joining DB results.

**Alternative considered:** Load all runs for the range and aggregate in Python. Simpler code but less efficient and doesn't follow the SQLAlchemy query pattern used elsewhere.

### D5: LLM cost query joins `kb_llm_provider` and `kb_llm_model`

**Decision:** The `GET /api/metrics/llm-cost` endpoint joins `kb_llm_call_log` with `kb_llm_provider` (for `provider_code`) and `kb_llm_model` (for `model_code`) to return human-readable names alongside IDs.

**Rationale:** The frontend needs display names (`provider_code`, `model_code`) not just numeric IDs. Joining at the query level avoids N+1 lookups from the frontend.

**Note:** Per db-conventions §7.1, no foreign keys exist between these tables. The join is done via `provider_id` / `model_id` columns in application-layer SQL, which is the standard pattern in this project.

### D6: Frontend structure -- single `MetricsView.vue` with composable

**Decision:** Create `kb-web/src/views/MetricsView.vue` as the main page, with a `kb-web/src/composables/useMetrics.ts` composable to manage data fetching and state. API client functions in `kb-web/src/api/metrics.ts`, types in `kb-web/src/types/metrics.ts`.

**Rationale:** Follows the existing frontend pattern (views in `views/`, API in `api/`, composables in `composables/`). The composable encapsulates the three parallel API calls (summary, runs, llm-cost) and exposes loading states.

**Alternative considered:** Inline all fetch logic in `MetricsView.vue`. Rejected because the page has 3 independent data sources and the logic would be unwieldy.

### D7: No chart library dependency -- use Element Plus table + cards only

**Decision:** Use `el-table`, `el-card`, and `el-tag` components for the dashboard. No ECharts or additional chart library.

**Rationale:** The PRD mentions "3 cards" as the MVP frontend requirement. The existing frontend has no chart library installed (checked `package.json`). Adding ECharts is a heavyweight dependency for an MVP. Tables and cards can display all required data. A future enhancement can add charts.

**Alternative considered:** Install `echarts` + `vue-echarts`. Rejected for MVP scope -- adds build complexity and a new dependency for marginal value when tables suffice.

### D8: Date range as `days` parameter, not calendar date pickers

**Decision:** The summary and llm-cost endpoints accept a `days` parameter (1-90). The runs endpoint accepts `start_date`/`end_date` for precise filtering. The frontend date range selector maps to `days` for summary/llm-cost and computes `start_date` for the runs table.

**Rationale:** Summary aggregation is naturally "last N days". The runs table benefits from explicit date bounds for precise filtering. The frontend unifies this with a single selector (7/14/30/90 days) that derives both.

## Risks / Trade-offs

- **[LLM cost join performance]** Joining `kb_llm_call_log` (high-volume append-only) with provider/model tables could be slow at scale. -> Mitigation: The `days` parameter caps at 90, and `kb_llm_call_log` has `idx_created_at`. For MVP volume (~20 articles/day = ~50-100 LLM calls/day), this is negligible. If it becomes slow, add an index on `(provider_id, model_id, called_at)`.

- **[No soft-delete filtering needed]** `kb_pipeline_run` and `kb_node_metric` are append-only log tables with no `is_deleted` column. `kb_llm_call_log` has `is_deleted` but call logs are never soft-deleted in practice. -> Mitigation: Still filter `is_deleted = 0` on `kb_llm_call_log` per db-conventions §7.3, but skip it for the pipeline tables (they have no such column).

- **[Timezone handling]** `started_at` in `kb_pipeline_run` is stored as naive UTC. The `DATE(started_at)` grouping in SQL will group by UTC date, which may not match the user's local timezone (UTC+8). -> Mitigation: Acceptable for MVP. The difference is at most 1 day at boundaries. A future enhancement can add timezone-aware grouping.

- **[Frontend bundle size]** Adding a new route increases the number of lazy-loaded chunks but doesn't affect initial bundle since it's dynamically imported. -> No mitigation needed.
