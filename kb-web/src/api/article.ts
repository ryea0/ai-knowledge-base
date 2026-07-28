import { get } from '@/utils/request'

export interface Article {
  article_id: string
  title: string
  source_url: string
  source_platform: string
  source_score: number
  summary: string
  content_path: string
  tags: string[]
  category: string
  status: string
  language: string
  collected_at: string
  analyzed_at: string | null
  published_at: string | null
  published_channels: string[] | null
}

export interface ArticleListParams {
  page?: number
  size?: number
  status?: string
  category?: string
  keyword?: string
}

export interface PageResult<T> {
  list: T[]
  total: number
  page: number
  size: number
}

export function getArticles(params: ArticleListParams) {
  return get<PageResult<Article>>('/articles', { params })
}

export function getArticle(id: string) {
  return get<Article>(`/articles/${id}`)
}
