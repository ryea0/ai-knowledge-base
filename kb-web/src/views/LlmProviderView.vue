<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getProviders, type LlmProvider } from '@/api'

const loading = ref(false)
const providers = ref<LlmProvider[]>([])

const healthStatusType: Record<string, string> = {
  healthy: 'success',
  degraded: 'warning',
  unhealthy: 'danger',
  unknown: 'info',
}

async function loadData(): Promise<void> {
  loading.value = true
  try {
    providers.value = await getProviders()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <el-card shadow="never">
    <el-table v-loading="loading" :data="providers" stripe>
      <el-table-column prop="provider_code" label="代码" width="120" />
      <el-table-column prop="provider_name" label="名称" width="150" />
      <el-table-column prop="provider_type" label="类型" width="80" />
      <el-table-column prop="auth_type" label="鉴权" width="80" />
      <el-table-column prop="litellm_provider" label="LiteLLM" width="120" />
      <el-table-column prop="base_url" label="Base URL" min-width="250" show-overflow-tooltip />
      <el-table-column prop="health_status" label="健康" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="healthStatusType[row.health_status] ?? 'info'" size="small">
            {{ row.health_status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="priority" label="优先级" width="80" align="center" />
      <el-table-column prop="is_enabled" label="启用" width="70" align="center">
        <template #default="{ row }">
          <el-tag :type="row.is_enabled ? 'success' : 'info'" size="small">
            {{ row.is_enabled ? '是' : '否' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>
