import { ref } from 'vue'
import {
  getMetricsRuns,
  getMetricsSummary,
  getMetricsLlmCost,
  getMetricsRunDetail,
} from '@/api/metrics'
import type {
  RunSummary,
  RunDetail,
  SummaryResponse,
  LlmCostResponse,
} from '@/types/metrics'

export function useMetrics() {
  const days = ref(7)
  const loadingSummary = ref(false)
  const loadingRuns = ref(false)
  const loadingCost = ref(false)

  const summary = ref<SummaryResponse | null>(null)
  const runs = ref<RunSummary[]>([])
  const runsTotal = ref(0)
  const runsPage = ref(1)
  const runsSize = ref(20)
  const runsStatus = ref<string | undefined>(undefined)
  const costData = ref<LlmCostResponse | null>(null)

  async function fetchSummary(): Promise<void> {
    loadingSummary.value = true
    try {
      summary.value = await getMetricsSummary(days.value)
    } finally {
      loadingSummary.value = false
    }
  }

  async function fetchRuns(): Promise<void> {
    loadingRuns.value = true
    try {
      const startDate = new Date()
      startDate.setDate(startDate.getDate() - days.value + 1)
      const startDateStr = startDate.toISOString().slice(0, 10)

      const result = await getMetricsRuns({
        page: runsPage.value,
        size: runsSize.value,
        start_date: startDateStr,
        status: runsStatus.value,
      })
      runs.value = result.data
      runsTotal.value = result.total
    } finally {
      loadingRuns.value = false
    }
  }

  async function fetchCost(): Promise<void> {
    loadingCost.value = true
    try {
      costData.value = await getMetricsLlmCost(days.value)
    } finally {
      loadingCost.value = false
    }
  }

  async function fetchRunDetail(runId: number): Promise<RunDetail> {
    return getMetricsRunDetail(runId)
  }

  async function refreshAll(): Promise<void> {
    runsPage.value = 1
    await Promise.all([fetchSummary(), fetchRuns(), fetchCost()])
  }

  async function onDaysChange(): Promise<void> {
    await refreshAll()
  }

  async function onRunsPageChange(): Promise<void> {
    await fetchRuns()
  }

  async function onRunsStatusChange(): Promise<void> {
    runsPage.value = 1
    await fetchRuns()
  }

  return {
    days,
    loadingSummary,
    loadingRuns,
    loadingCost,
    summary,
    runs,
    runsTotal,
    runsPage,
    runsSize,
    runsStatus,
    costData,
    fetchSummary,
    fetchRuns,
    fetchCost,
    fetchRunDetail,
    refreshAll,
    onDaysChange,
    onRunsPageChange,
    onRunsStatusChange,
  }
}
