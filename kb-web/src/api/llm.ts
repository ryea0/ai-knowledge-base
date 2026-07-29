import { get, post, patch, del } from '@/utils/request'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LlmProvider {
  id: number
  provider_code: string
  display_name: string
  provider_type: number
  base_url: string
  litellm_provider: string
  auth_type: number
  header_name: string | null
  token_url: string | null
  is_enabled: boolean
  priority: number
  timeout_seconds: number
  max_retries: number
  rpm_limit: number
  model_count: number
  connectivity: ProviderConnectivity | null
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface ProviderDetail extends LlmProvider {
  models: LlmModel[]
  health_list: HealthInfo[]
}

export interface LlmModel {
  id: number
  provider_id: number
  model_code: string
  litellm_model: string
  display_name: string
  description: string | null
  context_window: number
  max_output_tokens: number
  supports_streaming: boolean
  supports_function_calling: boolean
  supports_vision: boolean
  supports_reasoning: boolean
  task_type: string[] | null
  input_price_per_1m: number
  output_price_per_1m: number
  is_enabled: boolean
  is_default: boolean
  source: number
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface HealthInfo {
  id: number
  provider_id: number
  model_id: number
  health_status: number
  consecutive_failures: number
  failure_threshold: number
  health_check_enabled: boolean
  last_check_at: string | null
  last_success_at: string | null
  last_failure_at: string | null
  last_latency_ms: number | null
  last_error: string | null
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface DiscoveredModel {
  model_code: string
  litellm_model: string
  display_name: string
  context_window: number
  max_output_tokens: number
  supports_streaming: boolean
  supports_function_calling: boolean
  supports_vision: boolean
  supports_reasoning: boolean
  task_type: string[] | null
  input_price_per_1m: number
  output_price_per_1m: number
  already_exists: boolean
}

export interface ConnectivityResult {
  success: boolean
  latency_ms: number | null
  status_code: number | null
  error: string | null
  endpoint: string
}

export interface ProviderConnectivity {
  provider_id: number
  is_connected: boolean
  latency_ms: number | null
  last_check_at: string | null
  last_error: string | null
}

export interface ProviderConnectivityItem {
  provider_id: number
  success: boolean
  latency_ms: number | null
  error: string | null
  last_check_at: string | null
}

export interface ProviderCreatePayload {
  provider_code: string
  display_name: string
  provider_type?: number
  base_url: string
  litellm_provider: string
  auth_type?: number
  api_key?: string | null
  secret_key?: string | null
  header_name?: string | null
  token_url?: string | null
  is_enabled?: boolean
  priority?: number
  timeout_seconds?: number
  max_retries?: number
  rpm_limit?: number
}

export interface ProviderUpdatePayload {
  display_name?: string
  base_url?: string
  litellm_provider?: string
  auth_type?: number
  api_key?: string | null
  secret_key?: string | null
  header_name?: string | null
  token_url?: string | null
  is_enabled?: boolean
  priority?: number
  timeout_seconds?: number
  max_retries?: number
  rpm_limit?: number
}

export interface ModelCreatePayload {
  model_code: string
  litellm_model: string
  display_name: string
  description?: string | null
  context_window?: number
  max_output_tokens?: number
  supports_streaming?: boolean
  supports_function_calling?: boolean
  supports_vision?: boolean
  supports_reasoning?: boolean
  task_type?: string[] | null
  input_price_per_1m?: number
  output_price_per_1m?: number
  is_enabled?: boolean
  is_default?: boolean
}

export interface ModelUpdatePayload {
  litellm_model?: string
  display_name?: string
  description?: string | null
  context_window?: number
  max_output_tokens?: number
  supports_streaming?: boolean
  supports_function_calling?: boolean
  supports_vision?: boolean
  supports_reasoning?: boolean
  task_type?: string[] | null
  input_price_per_1m?: number
  output_price_per_1m?: number
  is_enabled?: boolean
  is_default?: boolean
}

// ---------------------------------------------------------------------------
// Provider API
// ---------------------------------------------------------------------------

export function getProviders(params?: {
  provider_type?: number
  is_enabled?: boolean
}) {
  return get<LlmProvider[]>('/llm/providers', { params })
}

export function getProviderDetail(id: number) {
  return get<ProviderDetail>(`/llm/providers/${id}`)
}

export function createProvider(data: ProviderCreatePayload) {
  return post<LlmProvider>('/llm/providers', data)
}

export function updateProvider(id: number, data: ProviderUpdatePayload) {
  return patch<LlmProvider>(`/llm/providers/${id}`, data)
}

export function deleteProvider(id: number) {
  return del<void>(`/llm/providers/${id}`)
}

export function testConnectivity(id: number) {
  return post<ConnectivityResult>(`/llm/providers/${id}/connectivity`)
}

export function batchTestConnectivity() {
  return post<ProviderConnectivityItem[]>('/llm/providers/batch-connectivity')
}

export function getConnectivityStatus() {
  return get<ProviderConnectivityItem[]>('/llm/providers/connectivity')
}

// ---------------------------------------------------------------------------
// Model API
// ---------------------------------------------------------------------------

export function getModels(providerId: number) {
  return get<LlmModel[]>(`/llm/providers/${providerId}/models`)
}

export function createModel(providerId: number, data: ModelCreatePayload) {
  return post<LlmModel>(`/llm/providers/${providerId}/models`, data)
}

export function updateModel(modelId: number, data: ModelUpdatePayload) {
  return patch<LlmModel>(`/llm/models/${modelId}`, data)
}

export function deleteModel(modelId: number) {
  return del<void>(`/llm/models/${modelId}`)
}

export function batchDeleteModels(modelIds: number[]) {
  return post<number>('/llm/models/batch-delete', modelIds)
}

// ---------------------------------------------------------------------------
// Discovery API
// ---------------------------------------------------------------------------

export function discoverModels(providerId: number) {
  return post<DiscoveredModel[]>(`/llm/providers/${providerId}/discover`)
}

// ---------------------------------------------------------------------------
// Health API
// ---------------------------------------------------------------------------

export function resetModelHealth(modelId: number) {
  return post<void>(`/llm/health/${modelId}/reset`)
}
