<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getHealth, type HealthResponse, type ComponentHealth } from '@/api'

const router = useRouter()
const loading = ref(false)

interface StatsData {
  total: number
  pending: number
  reviewed: number
  published: number
  archived: number
  today_new: number
}

const stats = ref<StatsData>({
  total: 0,
  pending: 0,
  reviewed: 0,
  published: 0,
  archived: 0,
  today_new: 0,
})

const health = ref<HealthResponse | null>(null)

const statusText: Record<string, string> = {
  up: '正常',
  degraded: '降级',
  down: '不可用',
}

const statusColor: Record<string, string> = {
  up: '#67c23a',
  degraded: '#e6a23c',
  down: '#f56c6c',
}

const componentLabels: Record<string, string> = {
  database: '数据库',
  llm_providers: 'LLM 供应商',
  distributors: '分发渠道',
}

async function loadData(): Promise<void> {
  loading.value = true
  try {
    // TODO: GET /articles/stats
  } finally {
    loading.value = false
  }
}

async function loadHealth(): Promise<void> {
  try {
    health.value = await getHealth()
  } catch {
    health.value = null
  }
}

function goToProviders(): void {
  router.push('/llm/providers')
}

function componentStatus(comp: ComponentHealth | undefined): string {
  return comp?.status ?? 'down'
}

onMounted(() => {
  loadData()
  loadHealth()
})
</script>

<template>
  <div v-loading="loading">
    <!-- 系统健康状态 -->
    <el-card shadow="hover" style="margin-bottom: 16px;">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <span>系统健康状态</span>
          <span
            v-if="health"
            class="health-status-text"
            :style="{ color: statusColor[health.status] }"
          >
            {{ statusText[health.status] }}
          </span>
        </div>
      </template>
      <el-row :gutter="16" v-if="health">
        <el-col
          v-for="(comp, key) in health.components"
          :key="key"
          :span="8"
        >
          <div class="health-component-card">
            <div class="health-component-label">{{ componentLabels[key] ?? key }}</div>
            <div
              class="health-component-status"
              :style="{ color: statusColor[componentStatus(comp)] }"
            >
              {{ statusText[componentStatus(comp)] }}
            </div>
          </div>
        </el-col>
      </el-row>
      <el-empty v-else description="健康检查不可用" :image-size="60" />
    </el-card>

    <!-- 统计卡片 -->
    <el-row :gutter="16" style="margin-bottom: 16px;">
      <el-col :span="4">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value">{{ stats.total }}</div>
            <div class="stat-label">条目总数</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value stat-pending">{{ stats.pending }}</div>
            <div class="stat-label">待处理</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value stat-reviewed">{{ stats.reviewed }}</div>
            <div class="stat-label">已审核</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value stat-published">{{ stats.published }}</div>
            <div class="stat-label">已发布</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value stat-archived">{{ stats.archived }}</div>
            <div class="stat-label">已归档</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value stat-today">{{ stats.today_new }}</div>
            <div class="stat-label">今日新增</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 来源平台分布 & 热门标签 -->
    <el-row :gutter="16" style="margin-bottom: 16px;">
      <el-col :span="12">
        <el-card shadow="never" header="来源平台分布">
          <div class="chart-placeholder">
            <!-- TODO: 饼图 - 按 source_platform 聚合 -->
            <el-empty description="来源分布图表（待实现）" />
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never" header="热门标签 Top 10">
          <div class="chart-placeholder">
            <!-- TODO: 条形图/标签云 - 按频次排序 -->
            <el-empty description="热门标签图表（待实现）" />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- LLM 供应商健康概览 & 采集趋势 -->
    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never" header="LLM 供应商健康概览">
          <div class="health-overview" @click="goToProviders">
            <!-- TODO: healthy/degraded/unhealthy/unknown 计数卡片 -->
            <el-empty description="供应商健康概览（待实现）" />
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never" header="采集趋势">
          <div class="chart-placeholder">
            <!-- TODO: 折线图 - 近 7/30 天每日新增 -->
            <el-empty description="采集趋势图表（待实现）" />
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.health-status-text {
  font-size: 16px;
  font-weight: bold;
}

.health-component-card {
  text-align: center;
  padding: 16px 0;
}

.health-component-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.health-component-status {
  font-size: 22px;
  font-weight: bold;
}

.stat-card {
  text-align: center;
  padding: 10px 0;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #303133;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}

.stat-pending {
  color: #409eff;
}

.stat-reviewed {
  color: #e6a23c;
}

.stat-published {
  color: #67c23a;
}

.stat-archived {
  color: #909399;
}

.stat-today {
  color: #f56c6c;
}

.chart-placeholder {
  min-height: 250px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.health-overview {
  min-height: 250px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
</style>
