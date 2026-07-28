import instance from '@/utils/request'

export interface ComponentHealth {
  status: 'up' | 'degraded' | 'down'
  details: Record<string, unknown>
}

export interface HealthResponse {
  status: 'up' | 'degraded' | 'down'
  timestamp: string
  components: Record<string, ComponentHealth>
}

export interface AppInfo {
  name: string
  version: string
  python_version: string
  platform: string
}

export function getHealth(): Promise<HealthResponse> {
  return instance.get('/health', { validateStatus: () => true }) as Promise<HealthResponse>
}

export function getHealthSimple(): Promise<{ status: string }> {
  return instance.get('/health/simple') as Promise<{ status: string }>
}

export function getHealthInfo(): Promise<AppInfo> {
  return instance.get('/health/info') as Promise<AppInfo>
}
