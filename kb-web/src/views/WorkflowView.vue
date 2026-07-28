<script setup lang="ts">
import { onMounted, ref } from 'vue'

const loading = ref(false)
const activeTab = ref('trigger')

// 任务触发参数
const runForm = ref({
  stage: 'all',
  source: 'all',
  keywords: '',
})

// 执行历史
const runs = ref<unknown[]>([])

const stageOptions = [
  { label: '全流程', value: 'all' },
  { label: '采集', value: 'collect' },
  { label: '分析', value: 'analyze' },
  { label: '整理', value: 'curate' },
  { label: '分发', value: 'distribute' },
]

const sourceOptions = [
  { label: '全部', value: 'all' },
  { label: 'GitHub Trending', value: 'github_trending' },
  { label: 'Hacker News', value: 'hackernews' },
]

async function handleRun(): Promise<void> {
  // TODO: POST /workflow/run
  // 返回 trace_id
}

async function loadRuns(): Promise<void> {
  loading.value = true
  try {
    // TODO: GET /workflow/runs
  } finally {
    loading.value = false
  }
}

function copyTraceId(traceId: string): void {
  navigator.clipboard.writeText(traceId)
}

onMounted(() => {
  loadRuns()
})
</script>

<template>
  <div v-loading="loading">
    <el-card shadow="never" style="margin-bottom: 16px;">
      <el-tabs v-model="activeTab">
        <!-- Tab: 任务触发 -->
        <el-tab-pane label="任务触发" name="trigger">
          <el-form :model="runForm" label-width="100px" style="max-width: 600px;">
            <el-form-item label="执行阶段">
              <el-select v-model="runForm.stage" style="width: 200px;">
                <el-option
                  v-for="opt in stageOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="数据源">
              <el-select v-model="runForm.source" style="width: 200px;">
                <el-option
                  v-for="opt in sourceOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="关键词">
              <el-input
                v-model="runForm.keywords"
                placeholder="逗号分隔，如: llm,rag,agent"
                style="width: 400px;"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="handleRun">执行</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- Tab: 执行历史 -->
        <el-tab-pane label="执行历史" name="history">
          <el-empty v-if="runs.length === 0" description="执行历史列表（待实现）" />
          <!-- TODO: GET /workflow/runs -->
          <!-- 列: trace_id, stage, started_at, ended_at, duration, status, candidates_count, analysis_count, articles_count -->
          <!-- traceId 可点击复制 -->
          <!-- 筛选: status, 时间范围 -->
          <!-- 点击行展开链路追踪详情: GET /workflow/runs/:trace_id -->
          <el-table v-else :data="runs" stripe>
            <el-table-column prop="trace_id" label="Trace ID" width="120" />
            <el-table-column prop="stage" label="阶段" width="100" />
            <el-table-column prop="started_at" label="开始时间" width="170" />
            <el-table-column prop="ended_at" label="结束时间" width="170" />
            <el-table-column prop="duration" label="耗时" width="100" />
            <el-table-column prop="status" label="状态" width="100" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>
