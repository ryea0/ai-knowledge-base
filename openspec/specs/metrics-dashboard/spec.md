## Purpose

Provide a frontend dashboard page at `/metrics` that visualizes pipeline health, run history, and LLM cost trends, fed by the metrics query API. Enables content ops, tech leads, and cost managers to monitor pipeline performance without direct database access.

### Requirement: Metrics dashboard page and route

The system SHALL provide a `/metrics` route with a `MetricsView.vue` page component, lazy-loaded via dynamic import.

The page SHALL be accessible from the sidebar navigation as a top-level menu item labeled "指标监控".

#### Scenario: Navigate to metrics page

- **WHEN** user clicks "指标监控" in the sidebar
- **THEN** the `/metrics` route is activated and `MetricsView.vue` is rendered

#### Scenario: Route is lazy-loaded

- **WHEN** the application first loads
- **THEN** `MetricsView.vue` is not included in the initial bundle
- **AND** it is loaded on first navigation to `/metrics`

### Requirement: Summary cards section

The dashboard SHALL display three summary cards at the top of the page, populated by `GET /api/metrics/summary`:

1. **Daily intake volume**: total `article_count` for the selected date range, with a sub-text showing daily average.
2. **Review pass rate**: `avg_review_pass_rate` as a percentage, with a sub-text showing total runs.
3. **Cost trend**: `total_cost_yuan` for the selected range, with a sub-text showing currency.

Each card SHALL display a title, a primary value, and a secondary description.

#### Scenario: Summary cards load on page mount

- **WHEN** the metrics page is loaded
- **THEN** three summary cards are displayed with data from `GET /api/metrics/summary`

#### Scenario: Summary cards reflect selected date range

- **WHEN** user changes the date range selector (e.g., from 7 days to 30 days)
- **THEN** the summary cards re-fetch and display updated values

#### Scenario: Loading state

- **WHEN** summary data is being fetched
- **THEN** the cards show a loading skeleton or spinner

### Requirement: Pipeline runs table with drill-down

The dashboard SHALL display a pipeline runs table populated by `GET /api/metrics/runs`, with columns: trace_id, status (color-coded tag), started_at, duration_ms, source_count, article_count, saved_count, review_passed, iteration, total_cost_yuan.

The table SHALL support:
- Pagination (page size selector: 10/20/50)
- Status filter (all / success / human_flagged / error)
- Date range filter

Clicking a row SHALL expand or open a detail panel showing per-node metrics from `GET /api/metrics/runs/{run_id}`, including: node_name, duration_ms, cost_data (tokens breakdown), error.

#### Scenario: Runs table loads with pagination

- **WHEN** the metrics page is loaded
- **THEN** the runs table shows the first page of recent runs
- **AND** pagination controls are visible

#### Scenario: Filter runs by status

- **WHEN** user selects "error" in the status filter
- **THEN** only runs with `status = "error"` are displayed
- **AND** the table re-fetches from the API with the status filter

#### Scenario: Drill-down to node detail

- **WHEN** user clicks a row in the runs table
- **THEN** a detail panel or dialog opens showing per-node metrics for that run
- **AND** each node's `node_name`, `duration_ms`, `cost_data`, and `error` are displayed

#### Scenario: Empty runs table

- **WHEN** no runs match the current filters
- **THEN** the table displays an empty state message

### Requirement: LLM cost breakdown section

The dashboard SHALL display an LLM cost breakdown section populated by `GET /api/metrics/llm-cost`, showing:
- A table or chart of cost by provider + model, sorted by total cost descending
- Columns: provider_code, model_code, call_count, total_tokens, total_cost, currency
- A grand total summary showing total cost by currency (CNY / USD)

#### Scenario: Cost breakdown loads on page mount

- **WHEN** the metrics page is loaded
- **THEN** the LLM cost breakdown section displays data from `GET /api/metrics/llm-cost`

#### Scenario: Cost breakdown reflects date range

- **WHEN** user changes the date range selector
- **THEN** the cost breakdown re-fetches and displays updated data

#### Scenario: Cost breakdown with no data

- **WHEN** no LLM call logs exist for the selected range
- **THEN** the section displays an empty state message

### Requirement: Date range selector

The dashboard SHALL provide a date range selector control that applies to the summary cards, runs table, and cost breakdown sections.

Available options: 7 days (default), 14 days, 30 days, 90 days.

Changing the selector SHALL trigger a re-fetch of all affected sections.

#### Scenario: Default date range is 7 days

- **WHEN** the metrics page is first loaded
- **THEN** the date range selector shows "7 days" and all sections use 7-day data

#### Scenario: Change date range to 30 days

- **WHEN** user selects "30 days" from the date range selector
- **THEN** summary cards, runs table (date filter), and cost breakdown all re-fetch with the 30-day range

### Requirement: Status color coding

The runs table SHALL color-code the status column using Element Plus tag types:
- `success` -> `type="success"` (green)
- `human_flagged` -> `type="warning"` (orange)
- `error` -> `type="danger"` (red)

#### Scenario: Success status is green

- **WHEN** a run with `status = "success"` is displayed in the table
- **THEN** the status tag is green (`type="success"`)

#### Scenario: Error status is red

- **WHEN** a run with `status = "error"` is displayed in the table
- **THEN** the status tag is red (`type="danger"`)

### Requirement: Frontend API client

The system SHALL provide a `kb-web/src/api/metrics.ts` module with typed API functions for each metrics endpoint:
- `getMetricsRuns(params)`: calls `GET /api/metrics/runs`
- `getMetricsRunDetail(runId)`: calls `GET /api/metrics/runs/{run_id}`
- `getMetricsSummary(days)`: calls `GET /api/metrics/summary`
- `getMetricsLlmCost(days)`: calls `GET /api/metrics/llm-cost`

All functions SHALL use the shared axios instance from `kb-web/src/utils/request.ts` and return typed responses.

#### Scenario: API client returns typed data

- **WHEN** `getMetricsRuns({ page: 1, size: 20 })` is called
- **THEN** the return type is the paginated response type with run items

#### Scenario: API client handles errors

- **WHEN** an API call fails (e.g., network error)
- **THEN** the error is propagated to the caller for display handling
