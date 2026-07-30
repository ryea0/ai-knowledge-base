<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useMetrics } from '@/composables/useMetrics'
import type { NodeMetric } from '@/types/metrics'

const {
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
  refreshAll,
  onDaysChange,
  onRunsPageChange,
  onRunsStatusChange,
  fetchRunDetail,
} = useMetrics()

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailNodes = ref<NodeMetric[]>([])

const dayOptions = [
  { value: 7, label: '7 天' },
  { value: 14, label: '14 天' },
  { value: 30, label: '30 天' },
  { value: 90, label: '90 天' },
]

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'success', label: '成功' },
  { value: 'human_flagged', label: '人工标记' },
  { value: 'error', label: '错误' },
]

const statusTagType: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
  success: 'success',
  human_flagged: 'warning',
  error: 'danger',
}

function handleDaysChange(): void {
  onDaysChange()
}

function handleStatusChange(): void {
  onRunsStatusChange()
}

function handlePageChange(page: number): void {
  runsPage.value = page
  onRunsPageChange()
}

function handleSizeChange(size: number): void {
  runsSize.value = size
  runsPage.value = 1
  onRunsPageChange()
}

async function handleRowClick(row: { id: number }): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  try {
    const detail = await fetchRunDetail(row.id)
    detailNodes.value = detail.nodes
  } finally {
    detailLoading.value = false
  }
}

function formatDuration(ms: number | null): string {
  if (ms === null) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatCost(yuan: number): string {
  return `¥${yuan.toFixed(4)}`
}

function formatRate(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`
}

onMounted(() => {
  refreshAll()
})
</script>

<template>
  <div class="metrics-page">
    <!-- Date range selector -->
    <div class="metrics-header">
      <el-select
        :model-value="days"
        style="width: 120px"
        @change="handleDaysChange"
      >
        <el-option
          v-for="opt in dayOptions"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </el-select>
    </div>

    <!-- Summary cards -->
    <el-row :gutter="16" class="summary-cards">
      <el-col :span="8">
        <el-card v-loading="loadingSummary" shadow="hover">
          <template #header>入库量</template>
          <div class="card-value">
            {{ summary?.totals.total_article_count ?? 0 }}
          </div>
          <div class="card-sub">
            日均 {{ summary ? (summary.totals.total_article_count / days).toFixed(1) : '0' }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card v-loading="loadingSummary" shadow="hover">
          <template #header>审核通过率</template>
          <div class="card-value">
            {{ summary ? formatRate(summary.totals.avg_review_pass_rate) : '0%' }}
          </div>
          <div class="card-sub">
            共 {{ summary?.totals.total_runs ?? 0 }} 次运行
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card v-loading="loadingSummary" shadow="hover">
          <template #header>成本趋势</template>
          <div class="card-value">
            {{ summary ? formatCost(summary.totals.total_cost_yuan) : '¥0' }}
          </div>
          <div class="card-sub">CNY</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Pipeline runs table -->
    <el-card class="runs-section" shadow="never">
      <template #header>
        <div class="section-header">
          <span>Pipeline 运行历史</span>
          <el-select
            :model-value="runsStatus ?? ''"
            style="width: 120px"
            @change="handleStatusChange"
          >
            <el-option
              v-for="opt in statusOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </div>
      </template>

      <el-table
        v-loading="loadingRuns"
        :data="runs"
        style="width: 100%"
        @row-click="handleRowClick"
      >
        <el-table-column prop="trace_id" label="Trace ID" width="120" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType[row.status] ?? 'info'">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="180">
          <template #default="{ row }">
            {{ row.started_at ?? '-' }}
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">
            {{ formatDuration(row.duration_ms) }}
          </template>
        </el-table-column>
        <el-table-column prop="source_count" label="采集" width="70" />
        <el-table-column prop="article_count" label="条目" width="70" />
        <el-table-column prop="saved_count" label="保存" width="70" />
        <el-table-column label="审核" width="80">
          <template #default="{ row }">
            {{ row.review_passed ? '通过' : '未通过' }}
          </template>
        </el-table-column>
        <el-table-column prop="iteration" label="轮次" width="70" />
        <el-table-column label="成本" width="100">
          <template #default="{ row }">
            {{ formatCost(row.total_cost_yuan) }}
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="runsPage"
          v-model:page-size="runsSize"
          :total="runsTotal"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </el-card>

    <!-- LLM cost breakdown -->
    <el-card class="cost-section" shadow="never">
      <template #header>LLM 成本 Breakdown</template>

      <el-table
        v-loading="loadingCost"
        :data="costData?.items ?? []"
        style="width: 100%"
      >
        <el-table-column prop="provider_code" label="供应商" width="120" />
        <el-table-column prop="model_code" label="模型" width="180" />
        <el-table-column prop="call_count" label="调用次数" width="100" />
        <el-table-column prop="total_tokens" label="总 Tokens" width="120" />
        <el-table-column label="总成本" width="120">
          <template #default="{ row }">
            {{ row.currency === 'USD' ? '$' : '¥' }}{{ row.total_cost.toFixed(4) }}
          </template>
        </el-table-column>
        <el-table-column prop="currency" label="币种" width="80" />
      </el-table>

      <div v-if="costData" class="cost-total">
        <span>CNY 总计: ¥{{ costData.grand_total.total_cost_cny.toFixed(4) }}</span>
        <span>USD 总计: ${{ costData.grand_total.total_cost_usd.toFixed(4) }}</span>
        <span>总调用: {{ costData.grand_total.total_calls }}</span>
        <span>总 Tokens: {{ costData.grand_total.total_tokens }}</span>
      </div>
    </el-card>

    <!-- Run detail dialog -->
    <el-dialog v-model="detailVisible" title="节点指标详情" width="700px">
      <el-table v-loading="detailLoading" :data="detailNodes" style="width: 100%">
        <el-table-column prop="node_name" label="节点" width="100" />
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">
            {{ formatDuration(row.duration_ms) }}
          </template>
        </el-table-column>
        <el-table-column label="Prompt Tokens" width="130">
          <template #default="{ row }">
            {{ row.cost_data?.prompt_tokens ?? '-' }}
          </template>
        </el-table-column>
        <el-table-column label="Completion Tokens" width="150">
          <template #default="{ row }">
            {{ row.cost_data?.completion_tokens ?? '-' }}
          </template>
        </el-table-column>
        <el-table-column label="Total Tokens" width="120">
          <template #default="{ row }">
            {{ row.cost_data?.total_tokens ?? '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="error" label="错误" min-width="150" />
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.metrics-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.metrics-header {
  display: flex;
  justify-content: flex-end;
}

.summary-cards {
  margin-bottom: 0;
}

.card-value {
  font-size: 28px;
  font-weight: 600;
  color: #303133;
}

.card-sub {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.cost-total {
  display: flex;
  gap: 24px;
  margin-top: 12px;
  font-size: 14px;
  font-weight: 500;
  color: #606266;
}
</style>
