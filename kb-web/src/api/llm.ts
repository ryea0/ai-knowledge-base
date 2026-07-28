import { get } from '@/utils/request'

export interface LlmProvider {
  id: number
  provider_code: string
  provider_name: string
  provider_type: string
  auth_type: string
  base_url: string
  litellm_provider: string
  is_enabled: boolean
  health_status: string
  priority: number
  models: LlmModel[]
}

export interface LlmModel {
  id: number
  model_code: string
  model_name: string
  is_default: boolean
  context_window: number | null
  supports_function_calling: boolean
  supports_vision: boolean
  source: string
}

export function getProviders() {
  return get<LlmProvider[]>('/llm/providers')
}

export function getModels(providerId: number) {
  return get<LlmModel[]>(`/llm/providers/${providerId}/models`)
}
