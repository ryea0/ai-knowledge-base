## Why

Pipeline metrics collection is fully implemented (M1-M5 via decorator + ORM + DDL + workflow wiring),
but the data is trapped in the database with no way to query it. Content ops, tech leads, and cost
managers cannot answer "which step was slow last night?", "how many review rounds to pass?", or
"which agent burns the most tokens?" without direct DB access. The PRD (`prd-pipeline-metrics.md`)
and architecture doc (`arch-pipeline-metrics.md`) both list the query API and frontend dashboard as
required deliverables that remain unbuilt.

## What Changes

- New `GET /api/metrics/runs` endpoint: list recent pipeline runs with M1-M5 summary metrics
  (status, duration, funnel counts, cost, review pass rate, iteration), supports pagination + date range filter.
- New `GET /api/metrics/runs/{run_id}` endpoint: single run detail with per-node metrics
  (M2 duration, M4 cost breakdown, M3 review data, errors).
- New `GET /api/metrics/summary` endpoint: aggregated dashboard data (daily intake volume,
  review pass rate, cost trend) for the date range -- feeds the 3 dashboard cards.
- New `GET /api/metrics/llm-cost` endpoint: LLM call cost summary from `kb_llm_call_log`,
  grouped by provider/model/day -- answers "which agent is most expensive".
- New `src/api/metrics_routes.py` router module with all above endpoints, registered in `app.py`.
- New `kb-web/src/api/metrics.ts` API client with typed functions for each endpoint.
- New `kb-web/src/views/MetricsView.vue` dashboard page at `/metrics` route with:
  - Summary cards: daily intake, review pass rate, cost trend
  - Pipeline runs table with drill-down to per-node detail
  - Cost breakdown by provider/model chart
- New `kb-web/src/types/metrics.ts` TypeScript types for API responses.

## Capabilities

### New Capabilities
- `metrics-query-api`: REST API endpoints for querying pipeline run metrics, node-level metrics,
  aggregated dashboard summaries, and LLM cost breakdowns from existing `kb_pipeline_run`,
  `kb_node_metric`, and `kb_llm_call_log` tables.
- `metrics-dashboard`: Frontend dashboard page (`/metrics`) displaying pipeline health summary
  cards, run history table with drill-down, and cost trend visualization.

### Modified Capabilities
<!-- No existing spec-level behavior changes -->

## Impact

- **Backend**: New `src/api/metrics_routes.py` router (read-only queries against existing tables);
  registered in `src/app.py`. New service layer `src/services/metrics_service.py` for query logic.
  No changes to existing workflow, collection, or LLM code.
- **Frontend**: New `/metrics` route, `MetricsView.vue`, `metrics.ts` API client, `metrics.ts` types.
  No changes to existing views or routes.
- **Database**: No DDL changes -- reads from existing `kb_pipeline_run`, `kb_node_metric`,
  `kb_llm_call_log` tables (all DDL already deployed).
- **Dependencies**: No new backend dependencies. Frontend may use existing chart library
  (Element Plus / ECharts if already available, otherwise simple tables/cards).
