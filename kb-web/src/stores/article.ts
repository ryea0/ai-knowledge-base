import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getArticles, type Article, type ArticleListParams } from '@/api'

export const useArticleStore = defineStore('article', () => {
  const articles = ref<Article[]>([])
  const total = ref(0)
  const loading = ref(false)

  async function fetchArticles(params: ArticleListParams): Promise<void> {
    loading.value = true
    try {
      const result = await getArticles(params)
      articles.value = result.list
      total.value = result.total
    } finally {
      loading.value = false
    }
  }

  return { articles, total, loading, fetchArticles }
})
