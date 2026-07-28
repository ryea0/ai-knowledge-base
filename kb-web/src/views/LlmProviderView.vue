<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { SuccessFilled, CircleCloseFilled, RemoveFilled } from '@element-plus/icons-vue'
import {
  getProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  batchTestConnectivity,
  getConnectivityStatus,
  type LlmProvider,
  type ProviderCreatePayload,
  type ProviderUpdatePayload,
} from '@/api'

const router = useRouter()
const loading = ref(false)
const providers = ref<LlmProvider[]>([])

// Connectivity
const connectivityLoading = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

// Filter
const filterType = ref<number | undefined>(undefined)
const filterEnabled = ref<boolean | undefined>(undefined)

// Create/Edit dialog
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const dialogLoading = ref(false)
const editingId = ref<number | null>(null)
const form = ref<ProviderCreatePayload & ProviderUpdatePayload>(defaultForm())

const LITELLM_PROVIDER_OPTIONS = [
  { label: 'OpenAI 兼容 (openai)', value: 'openai' },
  { label: 'Ollama 原生 (ollama)', value: 'ollama' },
  { label: 'llama.cpp (llamacpp)', value: 'llamacpp' },
  { label: 'Anthropic 原生 (anthropic)', value: 'anthropic' },
  { label: 'Gemini 原生 (gemini)', value: 'gemini' },
  { label: 'Azure OpenAI (azure)', value: 'azure' },
]

function defaultForm(): ProviderCreatePayload {
  return {
    provider_code: '',
    display_name: '',
    provider_type: 0,
    base_url: '',
    litellm_provider: 'openai',
    auth_type: 0,
    api_key: '',
    is_enabled: true,
    priority: 100,
    timeout_seconds: 30,
    max_retries: 3,
  }
}

const authTypeLabel: Record<number, string> = {
  0: 'bearer',
  1: 'oauth',
  2: 'header',
  3: 'none',
}

const providerTypeLabel: Record<number, string> = {
  0: 'cloud',
  1: 'local',
}

const isEditMode = computed(() => dialogMode.value === 'edit')

const filteredProviders = computed(() => providers.value)

async function loadData(): Promise<void> {
  loading.value = true
  try {
    providers.value = await getProviders({
      provider_type: filterType.value,
      is_enabled: filterEnabled.value,
    })
  } finally {
    loading.value = false
  }
}

async function loadConnectivity(): Promise<void> {
  try {
    const results = await getConnectivityStatus()
    const map: Record<number, typeof results[0]> = {}
    for (const r of results) {
      map[r.provider_id] = r
    }
    // Merge connectivity into provider rows
    for (const p of providers.value) {
      const c = map[p.id]
      p.connectivity = c
        ? {
            provider_id: c.provider_id,
            is_connected: c.success,
            latency_ms: c.latency_ms,
            last_check_at: c.last_check_at,
            last_error: c.error,
          }
        : null
    }
  } catch {
    // Error handled by interceptor
  }
}

async function handleTestConnectivity(): Promise<void> {
  connectivityLoading.value = true
  try {
    await batchTestConnectivity()
    await loadData()
  } catch {
    // Error handled by interceptor
  } finally {
    connectivityLoading.value = false
  }
}

async function handleToggleEnabled(row: LlmProvider): Promise<void> {
  const newVal = !row.is_enabled
  try {
    await updateProvider(row.id, { is_enabled: newVal })
    row.is_enabled = newVal
    ElMessage.success({ message: newVal ? '已启用' : '已禁用', duration: 5000 })
  } catch {
    // Error handled by interceptor
  }
}

function handleRowClick(row: LlmProvider, column: { label?: string } | null): void {
  if (column?.label === '操作') return
  router.push(`/llm/providers/${row.id}`)
}

function openCreateDialog(): void {
  dialogMode.value = 'create'
  editingId.value = null
  form.value = defaultForm()
  dialogVisible.value = true
}

function openEditDialog(row: LlmProvider): void {
  dialogMode.value = 'edit'
  editingId.value = row.id
  form.value = {
    provider_code: row.provider_code,
    display_name: row.display_name,
    provider_type: row.provider_type,
    base_url: row.base_url,
    litellm_provider: row.litellm_provider,
    auth_type: row.auth_type,
    api_key: '',
    header_name: row.header_name ?? undefined,
    token_url: row.token_url ?? undefined,
    is_enabled: row.is_enabled,
    priority: row.priority,
    timeout_seconds: row.timeout_seconds,
    max_retries: row.max_retries,
    rpm_limit: row.rpm_limit,
  }
  dialogVisible.value = true
}

async function handleSubmit(): Promise<void> {
  dialogLoading.value = true
  try {
    if (isEditMode.value && editingId.value !== null) {
      const payload: ProviderUpdatePayload = {
        display_name: form.value.display_name,
        base_url: form.value.base_url,
        litellm_provider: form.value.litellm_provider,
        auth_type: form.value.auth_type,
        is_enabled: form.value.is_enabled,
        priority: form.value.priority,
        timeout_seconds: form.value.timeout_seconds,
        max_retries: form.value.max_retries,
        rpm_limit: form.value.rpm_limit,
      }
      if (form.value.api_key) payload.api_key = form.value.api_key
      if (form.value.secret_key) payload.secret_key = form.value.secret_key
      if (form.value.header_name !== undefined) payload.header_name = form.value.header_name
      if (form.value.token_url !== undefined) payload.token_url = form.value.token_url
      await updateProvider(editingId.value, payload)
      ElMessage.success({ message: '供应商更新成功', duration: 5000 })
    } else {
      await createProvider(form.value)
      ElMessage.success({ message: '供应商创建成功', duration: 5000 })
    }
    dialogVisible.value = false
    await loadData()
    await loadConnectivity()
  } catch {
    // Error handled by interceptor
  } finally {
    dialogLoading.value = false
  }
}

async function handleDelete(row: LlmProvider): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除供应商 "${row.display_name}" 吗？`,
      '删除确认',
      { type: 'warning' },
    )
    await deleteProvider(row.id)
    ElMessage.success({ message: '删除成功', duration: 5000 })
    await loadData()
    await loadConnectivity()
  } catch {
    // Cancelled or error
  }
}

onMounted(() => {
  loadData()
  loadConnectivity()
  pollTimer = setInterval(loadConnectivity, 30000)
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<template>
  <el-card shadow="never">
    <!-- Toolbar -->
    <div style="display: flex; justify-content: space-between; margin-bottom: 16px;">
      <div style="display: flex; gap: 12px; align-items: center;">
        <el-select
          v-model="filterType"
          placeholder="全部类型"
          clearable
          style="width: 120px;"
          @change="loadData"
        >
          <el-option label="cloud" :value="0" />
          <el-option label="local" :value="1" />
        </el-select>
        <el-select
          v-model="filterEnabled"
          placeholder="全部状态"
          clearable
          style="width: 120px;"
          @change="loadData"
        >
          <el-option label="启用" :value="true" />
          <el-option label="禁用" :value="false" />
        </el-select>
        <el-button :loading="connectivityLoading" @click="handleTestConnectivity">
          测试联通
        </el-button>
      </div>
      <el-button type="primary" @click="openCreateDialog">
        新增供应商
      </el-button>
    </div>

    <!-- Table -->
    <el-table
      v-loading="loading"
      :data="filteredProviders"
      stripe
      style="cursor: pointer;"
      @row-click="handleRowClick"
    >
      <el-table-column prop="provider_code" label="代码" width="120" />
      <el-table-column prop="display_name" label="名称" width="150" />
      <el-table-column label="类型" width="80">
        <template #default="{ row }">
          {{ providerTypeLabel[row.provider_type] ?? row.provider_type }}
        </template>
      </el-table-column>
      <el-table-column label="鉴权" width="80">
        <template #default="{ row }">
          {{ authTypeLabel[row.auth_type] ?? row.auth_type }}
        </template>
      </el-table-column>
      <el-table-column prop="litellm_provider" label="LiteLLM" width="120" />
      <el-table-column prop="base_url" label="Base URL" min-width="250" show-overflow-tooltip />
      <el-table-column label="联通" width="80" align="center">
        <template #default="{ row }">
          <el-tooltip
            v-if="row.connectivity"
            :content="row.connectivity.is_connected
              ? `连通正常 (${row.connectivity.latency_ms}ms)`
              : `连通失败: ${row.connectivity.last_error ?? ''}`"
            placement="top"
          >
            <el-icon
              :color="row.connectivity.is_connected ? '#67c23a' : '#f56c6c'"
              :size="16"
            >
              <SuccessFilled v-if="row.connectivity.is_connected" />
              <CircleCloseFilled v-else />
            </el-icon>
          </el-tooltip>
          <el-icon v-else color="#909399" :size="16"><RemoveFilled /></el-icon>
        </template>
      </el-table-column>
      <el-table-column prop="model_count" label="模型数" width="80" align="center" />
      <el-table-column label="启用" width="80" align="center">
        <template #default="{ row }">
          <el-switch
            :model-value="row.is_enabled"
            @change="handleToggleEnabled(row as LlmProvider)"
          />
        </template>
      </el-table-column>
      <el-table-column prop="priority" label="优先级" width="80" align="center" />
      <el-table-column label="操作" width="160" align="center" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" size="small" link @click.stop="openEditDialog(row as LlmProvider)">
            编辑
          </el-button>
          <el-button type="danger" size="small" link @click.stop="handleDelete(row as LlmProvider)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Create/Edit Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEditMode ? '编辑供应商' : '新增供应商'"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="120px">
        <el-form-item label="供应商代码">
          <el-input
            v-model="form.provider_code"
            placeholder="如 deepseek / ark"
            :disabled="isEditMode"
          />
        </el-form-item>
        <el-form-item label="展示名称">
          <el-input v-model="form.display_name" placeholder="如 DeepSeek" />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="form.provider_type" :disabled="isEditMode">
            <el-radio :value="0">Cloud</el-radio>
            <el-radio :value="1">Local</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="https://api.example.com/v1" />
        </el-form-item>
        <el-form-item label="LiteLLM Provider">
          <el-select v-model="form.litellm_provider" placeholder="选择协议族" style="width: 100%;">
            <el-option
              v-for="opt in LITELLM_PROVIDER_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="鉴权方式">
          <el-radio-group v-model="form.auth_type">
            <el-radio :value="0">Bearer</el-radio>
            <el-radio :value="1">OAuth</el-radio>
            <el-radio :value="2">Header</el-radio>
            <el-radio :value="3">None</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.auth_type !== 3" :label="isEditMode ? 'API Key (留空不修改)' : 'API Key'">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="isEditMode ? '留空表示不修改' : '明文输入，服务端加密存储'"
          />
        </el-form-item>
        <el-form-item v-if="form.auth_type === 2" label="Header 名">
          <el-input v-model="form.header_name" placeholder="如 x-api-key" />
        </el-form-item>
        <el-form-item v-if="form.auth_type === 1" label="Secret Key">
          <el-input
            v-model="form.secret_key"
            type="password"
            show-password
            :placeholder="isEditMode ? '留空表示不修改' : '仅 OAuth 类型'"
          />
        </el-form-item>
        <el-form-item v-if="form.auth_type === 1" label="Token URL">
          <el-input v-model="form.token_url" placeholder="OAuth token 交换地址" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" :min="0" :max="999" />
        </el-form-item>
        <el-form-item label="超时(秒)">
          <el-input-number v-model="form.timeout_seconds" :min="1" :max="600" />
        </el-form-item>
        <el-form-item label="最大重试">
          <el-input-number v-model="form.max_retries" :min="0" :max="10" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dialogLoading" @click="handleSubmit">
          {{ isEditMode ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </el-card>
</template>
