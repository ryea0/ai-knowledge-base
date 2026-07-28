<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const activeTab = ref('info')

const providerId = route.params.id as string

function goBack(): void {
  router.push('/llm/providers')
}

onMounted(() => {
  // TODO: GET /llm/providers/:id
})
</script>

<template>
  <div v-loading="loading">
    <el-page-header @back="goBack">
      <template #content>
        <span style="font-size: 16px; font-weight: 500;">供应商详情（ID: {{ providerId }}）</span>
      </template>
    </el-page-header>

    <el-card shadow="never" style="margin-top: 16px;">
      <el-tabs v-model="activeTab">
        <!-- Tab: 供应商信息 -->
        <el-tab-pane label="供应商信息" name="info">
          <el-empty description="供应商信息编辑表单（待实现）" />
          <!-- TODO: GET /llm/providers/:id, PATCH /llm/providers/:id -->
          <!-- 字段: provider_code, display_name, provider_type, base_url, litellm_provider, auth_type, api_key, auth_config, is_enabled, priority, timeout_seconds, max_retries, rpm_limit, health_check_enabled, failure_threshold -->
          <!-- 只读字段: last_check_at, last_success_at, last_failure_at, consecutive_failures, last_error -->
        </el-tab-pane>

        <!-- Tab: 模型管理 -->
        <el-tab-pane label="模型管理" name="models">
          <el-empty description="模型列表与管理（待实现）" />
          <!-- TODO: GET /llm/providers/:id/models, POST /llm/providers/:id/models, PATCH /llm/models/:id -->
          <!-- 功能: 新增模型, 编辑模型, 启用/禁用模型, 设为默认模型 -->
          <!-- 列: model_code, litellm_model, context_window, supports_function_calling, supports_vision, input_price_per_1m, output_price_per_1m, source, is_enabled, is_default -->
        </el-tab-pane>

        <!-- Tab: 模型发现 -->
        <el-tab-pane label="模型发现" name="discover">
          <el-empty description="模型发现与批量导入（待实现）" />
          <!-- TODO: POST /llm/providers/:id/discover -> DiscoveredModel[] -->
          <!-- 功能: 发现模型, 勾选未存在的模型, 批量导入 -->
        </el-tab-pane>

        <!-- Tab: 健康检查日志 -->
        <el-tab-pane label="健康检查日志" name="health-logs">
          <el-empty description="健康检查日志（待实现）" />
          <!-- TODO: GET /llm/providers/:id/health-logs -->
          <!-- 列: check_at, model_id, latency_ms, is_success, error_msg -->
          <!-- 筛选: 时间范围 -->
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>
