## 1. Backend Schemas

- [x] 1.1 Create `src/api/metrics_schemas.py` with Pydantic response models: `RunSummaryResponse`, `NodeMetricResponse`, `RunDetailResponse`, `DailySummary`, `SummaryTotals`, `SummaryResponse`, `LlmCostItem`, `LlmCostGrandTotal`, `LlmCostResponse`
- [x] 1.2 Add `__init__.py` exports if needed for the `src/api/` package (check existing)

## 2. Backend Service Layer

- [x] 2.1 Create `src/api/metrics_service.py` with `list_runs(session, page, size, start_date, end_date, status)` -- paginated query on `kb_pipeline_run` with optional filters, ordered by `started_at` DESC, returns `(list[RunSummaryResponse], total_count)`
- [x] 2.2 Implement `get_run_detail(session, run_id)` -- fetch single `PipelineRun` + associated `NodeMetric` rows ordered by `created_at` ASC; raise `BizException(ErrorCode.NOT_FOUND)` if run missing; return `RunDetailResponse`
- [x] 2.3 Implement `get_summary(session, days)` -- SQL `GROUP BY DATE(started_at)` aggregation over `kb_pipeline_run` for last N days; fill missing days with zeros in Python; compute totals (total_runs, total_success, avg_review_pass_rate, counts, total_cost_yuan); return `SummaryResponse`
- [x] 2.4 Implement `get_llm_cost(session, days)` -- join `kb_llm_call_log` with `kb_llm_provider` and `kb_llm_model`, filter `is_deleted = 0` on call log, group by `(provider_id, model_id, currency)`, aggregate call_count/success_count/token totals/cost; sort by total_cost DESC; compute grand_total split by CNY/USD; return `LlmCostResponse`
- [x] 2.5 Validate `days` parameter (1-90, cap at 90) and `page`/`size` parameters (page >= 1, size 1-100) with `BizException(ErrorCode.PARAM_ERROR)` on invalid input

## 3. Backend API Routes

- [x] 3.1 Create `src/api/metrics_routes.py` with `APIRouter(prefix="/api/metrics", tags=["指标监控"])`
- [x] 3.2 Implement `GET /runs` endpoint -- accepts `page`, `size`, `start_date`, `end_date`, `status` query params; calls `list_runs`; returns `PageResult[RunSummaryResponse]`
- [x] 3.3 Implement `GET /runs/{run_id}` endpoint -- calls `get_run_detail`; returns `Result[RunDetailResponse]`
- [x] 3.4 Implement `GET /summary` endpoint -- accepts `days` query param (default 7); calls `get_summary`; returns `Result[SummaryResponse]`
- [x] 3.5 Implement `GET /llm-cost` endpoint -- accepts `days` query param (default 7); calls `get_llm_cost`; returns `Result[LlmCostResponse]`
- [x] 3.6 Register `metrics_router` in `src/app.py` via `app.include_router(metrics_router)`

## 4. Backend Tests

- [x] 4.1 Create `tests/api/test_metrics_service.py` -- test `list_runs` with pagination, date filter, status filter, empty result
- [x] 4.2 Test `get_run_detail` -- existing run with nodes, existing run without nodes, not-found raises `BizException`
- [x] 4.3 Test `get_summary` -- 7-day default, 30-day, day with no runs (zeros), days=0 raises PARAM_ERROR, days=120 capped to 90
- [x] 4.4 Test `get_llm_cost` -- with data grouped by provider/model, no data returns empty + zero grand_total, CNY/USD currency split
- [x] 4.5 Create `tests/api/test_metrics_routes.py` -- integration tests via FastAPI TestClient for all 4 endpoints, covering happy path + error cases (invalid params, not found)

## 5. Frontend Types and API Client

- [x] 5.1 Create `kb-web/src/types/metrics.ts` with TypeScript interfaces mirroring backend schemas: `RunSummary`, `NodeMetric`, `RunDetail`, `DailySummary`, `SummaryTotals`, `SummaryResponse`, `LlmCostItem`, `LlmCostGrandTotal`, `LlmCostResponse`, `MetricsRunsParams`
- [x] 5.2 Create `kb-web/src/api/metrics.ts` with typed functions: `getMetricsRuns(params)`, `getMetricsRunDetail(runId)`, `getMetricsSummary(days)`, `getMetricsLlmCost(days)` -- using shared `get` from `@/utils/request`
- [x] 5.3 Export metrics API from `kb-web/src/api/index.ts` barrel

## 6. Frontend Composable

- [x] 6.1 Create `kb-web/src/composables/useMetrics.ts` composable -- manages `days` ref (default 7), loading states for summary/runs/cost, and fetch functions that call the API client; exposes `refreshAll()` to re-fetch all sections on date range change

## 7. Frontend View and Route

- [x] 7.1 Create `kb-web/src/views/MetricsView.vue` with three sections: summary cards (el-card x3), pipeline runs table (el-table with pagination + status filter + row click drill-down dialog), LLM cost breakdown table (el-table with grand total row)
- [x] 7.2 Implement date range selector (el-select with 7/14/30/90 day options) that triggers `refreshAll()` on change
- [x] 7.3 Implement status color coding in runs table: success=green, human_flagged=orange, error=red via el-tag type
- [x] 7.4 Implement run detail drill-down: clicking a row opens an el-dialog showing per-node metrics (node_name, duration_ms, cost_data tokens, error)
- [x] 7.5 Add `/metrics` route to `kb-web/src/router/index.ts` with lazy-loaded `MetricsView.vue` and `meta: { title: '指标监控' }`
- [x] 7.6 Add "指标监控" menu item to `kb-web/src/layouts/DefaultLayout.vue` sidebar (with TrendCharts icon from @element-plus/icons-vue)

## 8. Verification

- [x] 8.1 Run `uv run ruff check src/api/metrics_routes.py src/api/metrics_service.py src/api/metrics_schemas.py tests/api/test_metrics_service.py tests/api/test_metrics_routes.py`
- [x] 8.2 Run `uv run mypy src/api/metrics_routes.py src/api/metrics_service.py src/api/metrics_schemas.py`
- [x] 8.3 Run `uv run pytest tests/api/test_metrics_service.py tests/api/test_metrics_routes.py --cov=src/api/metrics_service --cov=src/api/metrics_routes --cov-fail-under=80`
- [x] 8.4 Verify all 4 API endpoints work end-to-end by running the FastAPI app and hitting each endpoint with curl (confirm valid JSON envelope, correct pagination, correct error codes)
- [x] 8.5 Run `cd kb-web && npm run build` to verify frontend compiles without TypeScript errors
- [ ] 8.6 Manually verify the `/metrics` page renders correctly in the browser: cards load, table paginates, status filter works, row click opens node detail dialog, cost breakdown displays, date range selector triggers re-fetch
