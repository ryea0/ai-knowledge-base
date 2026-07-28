import axios from 'axios'
import type {
  AxiosInstance,
  AxiosRequestConfig,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from 'axios'
import { ElMessageBox } from 'element-plus'

const instance: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

instance.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => config,
  (error) => Promise.reject(error),
)

instance.interceptors.response.use(
  (response: AxiosResponse) => {
    const res = response.data
    if (res && typeof res === 'object' && 'code' in res) {
      if (res.code === 0) {
        return res.data
      }
      ElMessageBox.alert(res.message ?? '请求失败', '错误', {
        type: 'error',
        confirmButtonText: '确认',
      }).catch(() => {})
      return Promise.reject(new Error(res.message ?? '请求失败'))
    }
    return res
  },
  (error) => {
    const body = error.response?.data
    const message = (body && typeof body === 'object' && 'message' in body)
      ? String(body.message)
      : error.message ?? '网络异常'
    ElMessageBox.alert(message, '错误', {
      type: 'error',
      confirmButtonText: '确认',
    }).catch(() => {})
    return Promise.reject(new Error(message))
  },
)

export function get<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return instance.get(url, config)
}

export function post<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return instance.post(url, data, config)
}

export function put<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return instance.put(url, data, config)
}

export function del<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return instance.delete(url, config)
}

export function patch<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return instance.patch(url, data, config)
}

export default instance
