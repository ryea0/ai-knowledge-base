export interface RunSummary {
  id: number
  trace_id: string
  status: string
  started_at: string | null
  ended_at: string | null
  duration_ms: number | null
  source_count: number
  analysis_count: number
  article_count: number
  saved_count: number
  human_flagged: boolean
  review_passed: boolean
  iteration: number
  total_cost_yuan: number
  created_at: string
}

export interface NodeMetric {
  id: number
  node_name: string
  duration_ms: number
  cost_data: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  } | null
  review_passed: boolean | null
  iteration: number | null
  error: string
  created_at: string
}

export interface RunDetail extends RunSummary {
  nodes: NodeMetric[]
}

export interface DailySummary {
  date: string
  run_count: number
  success_count: number
  source_count: number
  article_count: number
  saved_count: number
  review_passed_count: number
  total_cost_yuan: number
}

export interface SummaryTotals {
  total_runs: number
  total_success: number
  avg_review_pass_rate: number
  total_source_count: number
  total_article_count: number
  total_saved_count: number
  total_cost_yuan: number
}

export interface SummaryResponse {
  daily: DailySummary[]
  totals: SummaryTotals
}

export interface LlmCostItem {
  provider_id: number
  provider_code: string
  model_id: number
  model_code: string
  call_count: number
  success_count: number
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
  total_cost: number
  currency: string
}

export interface LlmCostGrandTotal {
  total_cost_cny: number
  total_cost_usd: number
  total_calls: number
  total_tokens: number
}

export interface LlmCostResponse {
  items: LlmCostItem[]
  grand_total: LlmCostGrandTotal
}

export interface MetricsRunsParams {
  page?: number
  size?: number
  start_date?: string
  end_date?: string
  status?: string
}

export interface PageResult<T> {
  code: number
  message: string
  data: T[]
  total: number
  page: number
  size: number
}
