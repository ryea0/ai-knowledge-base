<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getArticles, type Article, type ArticleListParams } from '@/api'
import { usePagination } from '@/composables/usePagination'

const router = useRouter()
const loading = ref(false)
const articles = ref<Article[]>([])

const { page, size, total, handlePageChange, handleSizeChange } = usePagination(20)

const statusFilter = ref('')
const categoryFilter = ref('')
const keyword = ref('')

async function loadData(): Promise<void> {
  loading.value = true
  try {
    const params: ArticleListParams = {
      page: page.value,
      size: size.value,
      status: statusFilter.value || undefined,
      category: categoryFilter.value || undefined,
      keyword: keyword.value || undefined,
    }
    const result = await getArticles(params)
    articles.value = result.list
    total.value = result.total
  } finally {
    loading.value = false
  }
}

function handleSearch(): void {
  page.value = 1
  loadData()
}

function handleReset(): void {
  statusFilter.value = ''
  categoryFilter.value = ''
  keyword.value = ''
  page.value = 1
  loadData()
}

function goToDetail(row: Article): void {
  router.push(`/articles/${row.article_id}`)
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div>
    <el-card shadow="never" style="margin-bottom: 16px;">
      <el-form inline>
        <el-form-item label="状态">
          <el-select v-model="statusFilter" placeholder="全部" clearable style="width: 120px;">
            <el-option label="待处理" value="pending" />
            <el-option label="已审核" value="reviewed" />
            <el-option label="已发布" value="published" />
            <el-option label="已归档" value="archived" />
          </el-select>
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="categoryFilter" placeholder="全部" clearable style="width: 120px;">
            <el-option label="模型发布" value="model_release" />
            <el-option label="论文" value="paper" />
            <el-option label="工具" value="tool" />
            <el-option label="教程" value="tutorial" />
            <el-option label="新闻" value="news" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词">
          <el-input v-model="keyword" placeholder="搜索标题/摘要" clearable style="width: 200px;" @keyup.enter="handleSearch" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSearch">搜索</el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="articles" stripe @row-click="goToDetail">
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="source_platform" label="来源" width="140" />
        <el-table-column prop="source_score" label="热度" width="80" align="center" />
        <el-table-column prop="category" label="分类" width="120">
          <template #default="{ row }">
            <el-tag size="small">{{ row.category }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'published' ? 'success' : row.status === 'reviewed' ? 'warning' : row.status === 'archived' ? 'info' : 'primary'"
              size="small"
            >
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="collected_at" label="采集时间" width="170" />
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        style="margin-top: 16px; justify-content: flex-end;"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </el-card>
  </div>
</template>
