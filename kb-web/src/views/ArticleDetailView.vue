<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getArticle, type Article } from '@/api'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const article = ref<Article | null>(null)

async function loadData(): Promise<void> {
  loading.value = true
  try {
    const id = route.params.id as string
    article.value = await getArticle(id)
  } finally {
    loading.value = false
  }
}

function goBack(): void {
  router.push('/articles')
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div v-loading="loading">
    <el-page-header @back="goBack">
      <template #content>
        <span style="font-size: 16px; font-weight: 500;">条目详情</span>
      </template>
    </el-page-header>

    <el-card v-if="article" shadow="never" style="margin-top: 16px;">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="标题" :span="2">{{ article.title }}</el-descriptions-item>
        <el-descriptions-item label="条目 ID">{{ article.article_id }}</el-descriptions-item>
        <el-descriptions-item label="来源平台">{{ article.source_platform }}</el-descriptions-item>
        <el-descriptions-item label="来源链接" :span="2">
          <el-link type="primary" :href="article.source_url" target="_blank">{{ article.source_url }}</el-link>
        </el-descriptions-item>
        <el-descriptions-item label="热度">{{ article.source_score }}</el-descriptions-item>
        <el-descriptions-item label="分类">{{ article.category }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ article.status }}</el-descriptions-item>
        <el-descriptions-item label="语言">{{ article.language }}</el-descriptions-item>
        <el-descriptions-item label="标签" :span="2">
          <el-tag v-for="tag in article.tags" :key="tag" size="small" style="margin-right: 6px;">{{ tag }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="摘要" :span="2">{{ article.summary }}</el-descriptions-item>
        <el-descriptions-item label="采集时间">{{ article.collected_at }}</el-descriptions-item>
        <el-descriptions-item label="分析时间">{{ article.analyzed_at ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="发布时间">{{ article.published_at ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="发布渠道">{{ article.published_channels?.join(', ') ?? '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>
