import { get } from '@/utils/request'
import type {
  RunSummary,
  RunDetail,
  SummaryResponse,
  LlmCostResponse,
  MetricsRunsParams,
  PageResult,
} from '@/types/metrics'

export function getMetricsRuns(params: MetricsRunsParams): Promise<PageResult<RunSummary>> {
  return get<PageResult<RunSummary>>('/metrics/runs', { params })
}

export function getMetricsRunDetail(runId: number): Promise<RunDetail> {
  return get<RunDetail>(`/metrics/runs/${runId}`)
}

export function getMetricsSummary(days: number): Promise<SummaryResponse> {
  return get<SummaryResponse>('/metrics/summary', { params: { days } })
}

export function getMetricsLlmCost(days: number): Promise<LlmCostResponse> {
  return get<LlmCostResponse>('/metrics/llm-cost', { params: { days } })
}
