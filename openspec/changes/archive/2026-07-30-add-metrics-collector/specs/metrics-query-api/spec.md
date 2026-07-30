## Purpose

Provide REST API endpoints for querying pipeline run metrics, node-level metrics, aggregated dashboard summaries, and LLM cost breakdowns. All endpoints are read-only against existing `kb_pipeline_run`, `kb_node_metric`, and `kb_llm_call_log` tables.

## ADDED Requirements

### Requirement: List pipeline runs

The system SHALL provide a `GET /api/metrics/runs` endpoint that returns a paginated list of pipeline runs ordered by most recent first.

Query parameters:
- `page` (int, default 1, >= 1): page number
- `size` (int, default 20, 1-100): page size
- `start_date` (date, optional): filter runs started on or after this date (inclusive)
- `end_date` (date, optional): filter runs started on or before this date (inclusive)
- `status` (string, optional): filter by terminal status (`success` / `human_flagged` / `error`)

Each run in the response SHALL include: `id`, `trace_id`, `status`, `started_at`, `ended_at`, `duration_ms`, `source_count`, `analysis_count`, `article_count`, `saved_count`, `human_flagged`, `review_passed`, `iteration`, `total_cost_yuan`, `created_at`.

The response SHALL use the standard `PageResult` envelope with `total`, `page`, `size`.

#### Scenario: List recent runs with default pagination

- **WHEN** `GET /api/metrics/runs` is called with no query parameters
- **THEN** the response returns page 1, size 20, with runs ordered by `started_at` descending
- **AND** the response uses `PageResult` envelope with correct `total`, `page`, `size`

#### Scenario: Filter runs by date range

- **WHEN** `GET /api/metrics/runs?start_date=2026-07-01&end_date=2026-07-31` is called
- **THEN** only runs with `started_at` between 2026-07-01 00:00:00 and 2026-07-31 23:59:59 are returned

#### Scenario: Filter runs by status

- **WHEN** `GET /api/metrics/runs?status=error` is called
- **THEN** only runs with `status = "error"` are returned

#### Scenario: Page size capped at 100

- **WHEN** `GET /api/metrics/runs?size=200` is called
- **THEN** the response returns at most 100 items per page

#### Scenario: Empty result when no runs exist

- **WHEN** `GET /api/metrics/runs` is called and no runs match the filters
- **THEN** the response returns `data: []` with `total: 0`

### Requirement: Get single run detail with node metrics

The system SHALL provide a `GET /api/metrics/runs/{run_id}` endpoint that returns a single pipeline run with its associated node-level metrics.

The response SHALL include:
- All fields from the run summary (same as list item)
- `nodes`: array of node metric objects, each containing `id`, `node_name`, `duration_ms`, `cost_data` (JSON with `prompt_tokens`, `completion_tokens`, `total_tokens`), `review_passed`, `iteration`, `error`, `created_at`

Node metrics SHALL be ordered by `created_at` ascending (execution order).

#### Scenario: Get run detail with node metrics

- **WHEN** `GET /api/metrics/runs/42` is called and run 42 exists
- **THEN** the response returns the run summary plus a `nodes` array
- **AND** each node entry includes `node_name`, `duration_ms`, `cost_data`, `error`

#### Scenario: Run not found

- **WHEN** `GET /api/metrics/runs/9999` is called and run 9999 does not exist
- **THEN** the response returns `code` = `10004` (NOT_FOUND) with message "资源不存在"

#### Scenario: Run with no node metrics

- **WHEN** `GET /api/metrics/runs/1` is called and run 1 exists but has no node metric rows
- **THEN** the response returns the run summary with `nodes: []`

### Requirement: Get aggregated dashboard summary

The system SHALL provide a `GET /api/metrics/summary` endpoint that returns aggregated metrics for a date range, suitable for dashboard display.

Query parameters:
- `days` (int, default 7, 1-90): number of days to aggregate, ending at current date

The response SHALL include:
- `daily`: array of per-day objects, each containing `date` (YYYY-MM-DD), `run_count`, `success_count`, `source_count`, `article_count`, `saved_count`, `review_passed_count`, `total_cost_yuan`
- `totals`: aggregate across the entire range, containing `total_runs`, `total_success`, `avg_review_pass_rate` (0.0-1.0), `total_source_count`, `total_article_count`, `total_saved_count`, `total_cost_yuan`

#### Scenario: Get 7-day summary (default)

- **WHEN** `GET /api/metrics/summary` is called with no parameters
- **THEN** the response returns `daily` with 7 entries (one per day)
- **AND** `totals` aggregates all 7 days

#### Scenario: Get 30-day summary

- **WHEN** `GET /api/metrics/summary?days=30` is called
- **THEN** the response returns `daily` with 30 entries

#### Scenario: Days parameter capped at 90

- **WHEN** `GET /api/metrics/summary?days=120` is called
- **THEN** the response returns data for at most 90 days

#### Scenario: Days parameter minimum is 1

- **WHEN** `GET /api/metrics/summary?days=0` is called
- **THEN** the response returns `code` = `10001` (PARAM_ERROR)

#### Scenario: Day with no runs

- **WHEN** a day within the range has no pipeline runs
- **THEN** that day's entry in `daily` has all count fields as 0 and `total_cost_yuan` as 0.0

### Requirement: Get LLM cost breakdown

The system SHALL provide a `GET /api/metrics/llm-cost` endpoint that returns LLM call cost data from `kb_llm_call_log`, grouped by provider and model.

Query parameters:
- `days` (int, default 7, 1-90): number of days to aggregate, ending at current date

The response SHALL include:
- `items`: array of objects, each containing `provider_id`, `provider_code`, `model_id`, `model_code`, `call_count`, `success_count`, `total_input_tokens`, `total_output_tokens`, `total_tokens`, `total_cost`, `currency`
- `grand_total`: object containing `total_cost_cny`, `total_cost_usd`, `total_calls`, `total_tokens`

Items SHALL be sorted by `total_cost` descending within each currency group.

#### Scenario: Get LLM cost summary for 7 days

- **WHEN** `GET /api/metrics/llm-cost` is called with no parameters
- **THEN** the response returns `items` grouped by provider + model
- **AND** each item includes `call_count`, `total_tokens`, `total_cost`

#### Scenario: LLM cost with no call logs

- **WHEN** `GET /api/metrics/llm-cost?days=7` is called and no call logs exist in the range
- **THEN** the response returns `items: []` and `grand_total` with all zero values

#### Scenario: Cost separated by currency

- **WHEN** call logs exist for models with both CNY and USD pricing
- **THEN** `grand_total.total_cost_cny` sums only CNY-cost items
- **AND** `grand_total.total_cost_usd` sums only USD-cost items

### Requirement: API response format and error handling

All metrics endpoints SHALL use the standard `Result[T]` or `PageResult[T]` envelope (`code` / `message` / `data`).

Invalid query parameters (e.g., non-integer `page`, negative `days`) SHALL return `code` = `10001` (PARAM_ERROR) with a descriptive message.

All endpoints SHALL be read-only and SHALL NOT modify any data.

#### Scenario: Invalid page parameter

- **WHEN** `GET /api/metrics/runs?page=abc` is called
- **THEN** the response returns `code` = `10001` (PARAM_ERROR)

#### Scenario: Negative days parameter

- **WHEN** `GET /api/metrics/summary?days=-5` is called
- **THEN** the response returns `code` = `10001` (PARAM_ERROR)

#### Scenario: Router prefix

- **WHEN** any metrics endpoint is accessed
- **THEN** the path starts with `/api/metrics/`
