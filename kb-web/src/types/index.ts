export interface PaginationParams {
  page: number
  size: number
}

export interface ApiResult<T> {
  code: number
  message: string
  data: T
}

export interface PageData<T> {
  list: T[]
  total: number
  page: number
  size: number
}
