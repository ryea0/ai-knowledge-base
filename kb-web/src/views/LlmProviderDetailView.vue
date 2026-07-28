<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getProviderDetail,
  updateProvider,
  deleteProvider,
  testConnectivity,
  createModel,
  updateModel,
  deleteModel,
  discoverModels,
  resetModelHealth,
  type ProviderDetail,
  type LlmModel,
  type HealthInfo,
  type DiscoveredModel,
  type ConnectivityResult,
  type ModelCreatePayload,
  type ModelUpdatePayload,
} from '@/api'

const route = useRoute()
const router = useRouter()
const providerId = Number(route.params.id)

const loading = ref(false)
const detail = ref<ProviderDetail | null>(null)
const activeTab = ref('info')

// Connectivity
const connectivityLoading = ref(false)
const connectivityResult = ref<ConnectivityResult | null>(null)

// Model dialog
const modelDialogVisible = ref(false)
const modelDialogTitle = ref('')
const modelLoading = ref(false)
const editingModelId = ref<number | null>(null)
const modelForm = ref<ModelCreatePayload & ModelUpdatePayload>(defaultModelForm())

// Discovery
const discoverLoading = ref(false)
const discoveredModels = ref<DiscoveredModel[]>([])
const selectedDiscoveredModels = ref<DiscoveredModel[]>([])

// Health
const healthLoading = ref(false)

function defaultModelForm() {
  return {
    model_code: '',
    litellm_model: '',
    display_name: '',
    description: '',
    context_window: 4096,
    max_output_tokens: 4096,
    supports_streaming: true,
    supports_function_calling: false,
    supports_vision: false,
    input_price_per_1m: 0,
    output_price_per_1m: 0,
    is_enabled: true,
    is_default: false,
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

const sourceLabel: Record<number, string> = {
  0: 'preset',
  1: 'discovered',
  2: 'manual',
}

const healthStatusType: Record<number, 'success' | 'warning' | 'danger' | 'info'> = {
  0: 'success',
  1: 'warning',
  2: 'danger',
  3: 'info',
}

const healthStatusLabel: Record<number, string> = {
  0: 'healthy',
  1: 'degraded',
  2: 'unhealthy',
  3: 'unknown',
}

const models = computed<LlmModel[]>(() => detail.value?.models ?? [])
const healthList = computed<HealthInfo[]>(() => detail.value?.health_list ?? [])

const modelNameMap = computed<Record<number, string>>(() => {
  const map: Record<number, string> = {}
  for (const m of models.value) {
    map[m.id] = m.display_name
  }
  return map
})

async function loadDetail(): Promise<void> {
  loading.value = true
  try {
    detail.value = await getProviderDetail(providerId)
  } finally {
    loading.value = false
  }
}

// ---------------------------------------------------------------------------
// Connectivity
// ---------------------------------------------------------------------------

async function handleConnectivity(): Promise<void> {
  connectivityLoading.value = true
  try {
    connectivityResult.value = await testConnectivity(providerId)
    if (connectivityResult.value.success) {
      ElMessage.success({ message: `连通正常，延迟 ${connectivityResult.value.latency_ms}ms`, duration: 5000 })
    } else {
      ElMessage.error(`连通失败: ${connectivityResult.value.error}`)
    }
  } finally {
    connectivityLoading.value = false
  }
}

// ---------------------------------------------------------------------------
// Provider edit
// ---------------------------------------------------------------------------

async function handleToggleEnabled(): Promise<void> {
  if (!detail.value) return
  const newVal = !detail.value.is_enabled
  try {
    await updateProvider(providerId, { is_enabled: newVal })
    detail.value.is_enabled = newVal
    ElMessage.success({ message: newVal ? '已启用' : '已禁用', duration: 5000 })
  } catch {
    // Error handled by interceptor
  }
}

async function handleSavePriority(): Promise<void> {
  if (!detail.value) return
  try {
    await updateProvider(providerId, { priority: detail.value.priority })
    ElMessage.success({ message: '优先级已更新', duration: 5000 })
  } catch {
    // Error handled by interceptor
  }
}

async function handleDeleteProvider(): Promise<void> {
  try {
    await ElMessageBox.confirm('确定删除此供应商？', '删除确认', { type: 'warning' })
    await deleteProvider(providerId)
    ElMessage.success({ message: '删除成功', duration: 5000 })
    router.push('/llm/providers')
  } catch {
    // Cancelled or error
  }
}

// ---------------------------------------------------------------------------
// Model CRUD
// ---------------------------------------------------------------------------

function openCreateModelDialog(): void {
  editingModelId.value = null
  modelDialogTitle.value = '新增模型'
  modelForm.value = defaultModelForm()
  // Auto-fill litellm_model prefix
  if (detail.value) {
    modelForm.value.litellm_model = `${detail.value.litellm_provider}/`
  }
  modelDialogVisible.value = true
}

function openEditModelDialog(model: LlmModel): void {
  editingModelId.value = model.id
  modelDialogTitle.value = '编辑模型'
  modelForm.value = {
    model_code: model.model_code,
    litellm_model: model.litellm_model,
    display_name: model.display_name,
    description: model.description ?? '',
    context_window: model.context_window,
    max_output_tokens: model.max_output_tokens,
    supports_streaming: model.supports_streaming,
    supports_function_calling: model.supports_function_calling,
    supports_vision: model.supports_vision,
    input_price_per_1m: model.input_price_per_1m,
    output_price_per_1m: model.output_price_per_1m,
    is_enabled: model.is_enabled,
    is_default: model.is_default,
  }
  modelDialogVisible.value = true
}

async function handleSaveModel(): Promise<void> {
  modelLoading.value = true
  try {
    if (editingModelId.value !== null) {
      const { model_code: _, ...updateData } = modelForm.value
      await updateModel(editingModelId.value, updateData)
      ElMessage.success({ message: '模型更新成功', duration: 5000 })
    } else {
      await createModel(providerId, modelForm.value)
      ElMessage.success({ message: '模型创建成功', duration: 5000 })
    }
    modelDialogVisible.value = false
    await loadDetail()
  } catch {
    // Error handled by interceptor
  } finally {
    modelLoading.value = false
  }
}

async function handleToggleModelEnabled(model: LlmModel): Promise<void> {
  try {
    await updateModel(model.id, { is_enabled: !model.is_enabled })
    ElMessage.success({ message: !model.is_enabled ? '已启用' : '已禁用', duration: 5000 })
    await loadDetail()
  } catch {
    // Error handled by interceptor
  }
}

async function handleSetDefaultModel(model: LlmModel): Promise<void> {
  try {
    await updateModel(model.id, { is_default: true })
    ElMessage.success({ message: '已设为默认', duration: 5000 })
    await loadDetail()
  } catch {
    // Error handled by interceptor
  }
}

async function handleDeleteModel(model: LlmModel): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除模型 "${model.display_name}"？`, '删除确认', {
      type: 'warning',
    })
    await deleteModel(model.id)
    ElMessage.success({ message: '删除成功', duration: 5000 })
    await loadDetail()
  } catch {
    // Cancelled or error
  }
}

// ---------------------------------------------------------------------------
// Model Discovery
// ---------------------------------------------------------------------------

async function handleDiscover(): Promise<void> {
  discoverLoading.value = true
  selectedDiscoveredModels.value = []
  try {
    discoveredModels.value = await discoverModels(providerId)
    if (discoveredModels.value.length === 0) {
      ElMessage.info({ message: '未发现可用模型', duration: 5000 })
    } else {
      const newCount = discoveredModels.value.filter((m) => !m.already_exists).length
      ElMessage.success({ message: `发现 ${discoveredModels.value.length} 个模型，其中 ${newCount} 个可导入`, duration: 5000 })
    }
  } finally {
    discoverLoading.value = false
  }
}

function handleSelectionChange(selection: DiscoveredModel[]): void {
  selectedDiscoveredModels.value = selection.filter((m) => !m.already_exists)
}

async function handleBatchImport(): Promise<void> {
  if (selectedDiscoveredModels.value.length === 0) {
    ElMessage.warning({ message: '请勾选要导入的模型', duration: 5000 })
    return
  }

  discoverLoading.value = true
  let successCount = 0
  let failCount = 0

  for (const m of selectedDiscoveredModels.value) {
    try {
      await createModel(providerId, {
        model_code: m.model_code,
        litellm_model: m.litellm_model,
        display_name: m.display_name,
        context_window: m.context_window,
        max_output_tokens: m.max_output_tokens,
        supports_streaming: m.supports_streaming,
        supports_function_calling: m.supports_function_calling,
        supports_vision: m.supports_vision,
        input_price_per_1m: m.input_price_per_1m,
        output_price_per_1m: m.output_price_per_1m,
        is_enabled: true,
        is_default: false,
      })
      successCount++
    } catch {
      failCount++
    }
  }

  discoverLoading.value = false
  if (successCount > 0) {
    ElMessage.success({ message: `成功导入 ${successCount} 个模型${failCount > 0 ? `，失败 ${failCount} 个` : ''}`, duration: 5000 })
    await loadDetail()
    await handleDiscover()
  } else {
    ElMessage.error('导入失败')
  }
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

async function handleResetHealth(modelId: number): Promise<void> {
  healthLoading.value = true
  try {
    await resetModelHealth(modelId)
    ElMessage.success({ message: '健康状态已重置', duration: 5000 })
    await loadDetail()
  } finally {
    healthLoading.value = false
  }
}

// Lifecycle
onMounted(() => {
  loadDetail()
})
</script>

<template>
  <div v-loading="loading">
    <el-page-header @back="router.push('/llm/providers')">
      <template #content>
        <span style="font-size: 16px; font-weight: 500;">
          {{ detail?.display_name ?? '供应商详情' }}
          <el-tag
            v-if="detail"
            :type="detail.is_enabled ? 'success' : 'info'"
            size="small"
            style="margin-left: 8px;"
          >
            {{ detail.is_enabled ? '启用' : '禁用' }}
          </el-tag>
        </span>
      </template>
      <template #extra>
        <el-button
          type="primary"
          :loading="connectivityLoading"
          @click="handleConnectivity"
        >
          测试联通
        </el-button>
      </template>
    </el-page-header>

    <!-- Connectivity Result -->
    <el-alert
      v-if="connectivityResult"
      :title="connectivityResult.success
        ? `连通成功 (HTTP ${connectivityResult.status_code}, ${connectivityResult.latency_ms}ms)`
        : `连通失败: ${connectivityResult.error}`"
      :type="connectivityResult.success ? 'success' : 'error'"
      :description="`端点: ${connectivityResult.endpoint}`"
      show-icon
      closable
      style="margin-top: 12px;"
      @close="connectivityResult = null"
    />

    <el-card shadow="never" style="margin-top: 16px;">
      <el-tabs v-model="activeTab">
        <!-- Tab: 供应商信息 -->
        <el-tab-pane label="供应商信息" name="info">
          <template v-if="detail">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="供应商代码">{{ detail.provider_code }}</el-descriptions-item>
              <el-descriptions-item label="展示名称">{{ detail.display_name }}</el-descriptions-item>
              <el-descriptions-item label="类型">{{ providerTypeLabel[detail.provider_type] }}</el-descriptions-item>
              <el-descriptions-item label="LiteLLM">{{ detail.litellm_provider }}</el-descriptions-item>
              <el-descriptions-item label="Base URL" :span="2">{{ detail.base_url }}</el-descriptions-item>
              <el-descriptions-item label="鉴权方式">{{ authTypeLabel[detail.auth_type] }}</el-descriptions-item>
              <el-descriptions-item label="优先级">
                <el-input-number v-model="detail.priority" :min="0" :max="999" size="small" />
                <el-button size="small" type="primary" link @click="handleSavePriority">保存</el-button>
              </el-descriptions-item>
              <el-descriptions-item label="超时(秒)">{{ detail.timeout_seconds }}</el-descriptions-item>
              <el-descriptions-item label="最大重试">{{ detail.max_retries }}</el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ detail.created_at }}</el-descriptions-item>
              <el-descriptions-item label="更新时间">{{ detail.updated_at }}</el-descriptions-item>
            </el-descriptions>

            <div style="margin-top: 16px; display: flex; gap: 12px;">
              <el-button :type="detail.is_enabled ? 'warning' : 'success'" @click="handleToggleEnabled">
                {{ detail.is_enabled ? '禁用' : '启用' }}
              </el-button>
              <el-button type="danger" @click="handleDeleteProvider">删除供应商</el-button>
            </div>
          </template>
        </el-tab-pane>

        <!-- Tab: 模型管理 -->
        <el-tab-pane label="模型管理" name="models">
          <div style="margin-bottom: 12px;">
            <el-button type="primary" @click="openCreateModelDialog">新增模型</el-button>
          </div>

          <el-table :data="models" stripe>
            <el-table-column prop="model_code" label="模型代码" width="180" />
            <el-table-column prop="litellm_model" label="LiteLLM 标识" width="200" show-overflow-tooltip />
            <el-table-column prop="display_name" label="名称" width="150" />
            <el-table-column prop="context_window" label="上下文" width="100" align="center" />
            <el-table-column label="能力" width="120" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.supports_function_calling" size="small" style="margin-right: 4px;">FC</el-tag>
                <el-tag v-if="row.supports_vision" size="small" type="success">Vision</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="input_price_per_1m" label="输入价格" width="100" align="center">
              <template #default="{ row }">${{ row.input_price_per_1m }}</template>
            </el-table-column>
            <el-table-column prop="output_price_per_1m" label="输出价格" width="100" align="center">
              <template #default="{ row }">${{ row.output_price_per_1m }}</template>
            </el-table-column>
            <el-table-column label="来源" width="90" align="center">
              <template #default="{ row }">
                <el-tag size="small" type="info">{{ sourceLabel[row.source] }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="默认" width="60" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.is_default" size="small" type="warning">默认</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="70" align="center">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.is_enabled"
                  @change="handleToggleModelEnabled(row as LlmModel)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="180" align="center" fixed="right">
              <template #default="{ row }">
                <el-button size="small" link @click="openEditModelDialog(row as LlmModel)">编辑</el-button>
                <el-button
                  v-if="!row.is_default"
                  size="small"
                  link
                  type="warning"
                  @click="handleSetDefaultModel(row as LlmModel)"
                >设默认</el-button>
                <el-button size="small" link type="danger" @click="handleDeleteModel(row as LlmModel)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <!-- Model Dialog -->
          <el-dialog
            v-model="modelDialogVisible"
            :title="modelDialogTitle"
            width="600px"
            :close-on-click-modal="false"
          >
            <el-form :model="modelForm" label-width="120px">
              <el-form-item label="模型代码">
                <el-input
                  v-model="modelForm.model_code"
                  :disabled="editingModelId !== null"
                  placeholder="如 deepseek-chat"
                />
              </el-form-item>
              <el-form-item label="LiteLLM 标识">
                <el-input v-model="modelForm.litellm_model" placeholder="如 openai/deepseek-chat" />
              </el-form-item>
              <el-form-item label="展示名称">
                <el-input v-model="modelForm.display_name" />
              </el-form-item>
              <el-form-item label="描述">
                <el-input v-model="modelForm.description" type="textarea" :rows="2" />
              </el-form-item>
              <el-form-item label="上下文窗口">
                <el-input-number v-model="modelForm.context_window" :min="1" />
              </el-form-item>
              <el-form-item label="最大输出">
                <el-input-number v-model="modelForm.max_output_tokens" :min="1" />
              </el-form-item>
              <el-form-item label="流式输出">
                <el-switch v-model="modelForm.supports_streaming" />
              </el-form-item>
              <el-form-item label="函数调用">
                <el-switch v-model="modelForm.supports_function_calling" />
              </el-form-item>
              <el-form-item label="多模态">
                <el-switch v-model="modelForm.supports_vision" />
              </el-form-item>
              <el-form-item label="输入价格/M">
                <el-input-number v-model="modelForm.input_price_per_1m" :min="0" :precision="4" />
              </el-form-item>
              <el-form-item label="输出价格/M">
                <el-input-number v-model="modelForm.output_price_per_1m" :min="0" :precision="4" />
              </el-form-item>
              <el-form-item label="设为默认">
                <el-switch v-model="modelForm.is_default" />
              </el-form-item>
              <el-form-item label="启用">
                <el-switch v-model="modelForm.is_enabled" />
              </el-form-item>
            </el-form>
            <template #footer>
              <el-button @click="modelDialogVisible = false">取消</el-button>
              <el-button type="primary" :loading="modelLoading" @click="handleSaveModel">
                保存
              </el-button>
            </template>
          </el-dialog>
        </el-tab-pane>

        <!-- Tab: 模型发现 -->
        <el-tab-pane label="模型发现" name="discover">
          <div style="margin-bottom: 12px; display: flex; gap: 12px;">
            <el-button type="primary" :loading="discoverLoading" @click="handleDiscover">
              发现模型
            </el-button>
            <el-button
              v-if="discoveredModels.length > 0"
              type="success"
              :loading="discoverLoading"
              :disabled="selectedDiscoveredModels.length === 0"
              @click="handleBatchImport"
            >
              批量导入 ({{ selectedDiscoveredModels.length }})
            </el-button>
          </div>

          <el-table
            v-if="discoveredModels.length > 0"
            :data="discoveredModels"
            stripe
            @selection-change="handleSelectionChange"
          >
            <el-table-column
              type="selection"
              width="50"
              :selectable="(row: DiscoveredModel) => !row.already_exists"
            />
            <el-table-column prop="model_code" label="模型代码" width="200" />
            <el-table-column prop="litellm_model" label="LiteLLM 标识" width="250" show-overflow-tooltip />
            <el-table-column prop="display_name" label="名称" width="150" />
            <el-table-column prop="context_window" label="上下文" width="100" align="center" />
            <el-table-column label="能力" width="120" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.supports_function_calling" size="small" style="margin-right: 4px;">FC</el-tag>
                <el-tag v-if="row.supports_vision" size="small" type="success">Vision</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.already_exists" size="small" type="info">已存在</el-tag>
                <el-tag v-else size="small" type="success">可导入</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="点击「发现模型」拉取供应商可用模型列表" />
        </el-tab-pane>

        <!-- Tab: 健康状态 -->
        <el-tab-pane label="健康状态" name="health">
          <el-table :data="healthList" stripe v-loading="healthLoading">
            <el-table-column label="模型" width="180">
              <template #default="{ row }">
                {{ modelNameMap[row.model_id] ?? `模型 #${row.model_id}` }}
              </template>
            </el-table-column>
            <el-table-column label="健康状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="healthStatusType[row.health_status] ?? 'info'" size="small">
                  {{ healthStatusLabel[row.health_status] ?? 'unknown' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="失败次数/阈值" width="120" align="center">
              <template #default="{ row }">
                {{ row.consecutive_failures }} / {{ row.failure_threshold }}
              </template>
            </el-table-column>
            <el-table-column prop="last_check_at" label="最近检查" width="180" />
            <el-table-column label="延迟" width="80" align="center">
              <template #default="{ row }">
                {{ row.last_latency_ms != null ? `${row.last_latency_ms}ms` : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="last_error" label="最近错误" min-width="200" show-overflow-tooltip />
            <el-table-column label="操作" width="100" align="center" fixed="right">
              <template #default="{ row }">
                <el-button
                  size="small"
                  link
                  type="warning"
                  @click="handleResetHealth(row.model_id)"
                >重置</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>
