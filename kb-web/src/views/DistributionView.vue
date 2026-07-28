<script setup lang="ts">
import { onMounted, ref } from 'vue'

const loading = ref(false)

// 渠道配置状态
const channels = ref([
  { name: 'telegram', label: 'Telegram', configured: false },
  { name: 'feishu', label: '飞书', configured: false },
])

// 分发历史
const distributions = ref<unknown[]>([])

async function loadChannels(): Promise<void> {
  // TODO: GET /distributors/channels
}

async function loadDistributions(): Promise<void> {
  loading.value = true
  try {
    // TODO: GET /distributions
  } finally {
    loading.value = false
  }
}

async function handleResend(articleId: string): Promise<void> {
  // TODO: POST /articles/:id/distribute
}

onMounted(() => {
  loadChannels()
  loadDistributions()
})
</script>

<template>
  <div v-loading="loading">
    <!-- 渠道配置卡片 -->
    <el-row :gutter="16" style="margin-bottom: 16px;">
      <el-col v-for="ch in channels" :key="ch.name" :span="12">
        <el-card shadow="hover">
          <div style="display: flex; align-items: center; justify-content: space-between;">
            <div>
              <span style="font-size: 16px; font-weight: 500;">{{ ch.label }}</span>
              <div style="margin-top: 8px;">
                <el-tag :type="ch.configured ? 'success' : 'info'" size="small">
                  {{ ch.configured ? '已配置' : '未配置' }}
                </el-tag>
              </div>
            </div>
            <el-icon style="font-size: 32px; color: #909399;">
              <!-- TODO: 渠道图标 -->
            </el-icon>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 分发历史列表 -->
    <el-card shadow="never">
      <template #header>分发历史</template>
      <el-empty v-if="distributions.length === 0" description="分发历史列表（待实现）" />
      <!-- TODO: GET /distributions -->
      <!-- 列: article_title, channel, pushed_at, result(success/skipped/failed), error -->
      <!-- 筛选: channel, result -->
      <!-- 失败行提供「重发」按钮: POST /articles/:id/distribute -->
      <el-table v-else :data="distributions" stripe>
        <el-table-column prop="article_title" label="条目标题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="channel" label="渠道" width="100" />
        <el-table-column prop="pushed_at" label="推送时间" width="170" />
        <el-table-column prop="result" label="结果" width="100" />
        <el-table-column prop="error" label="错误信息" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.result === 'failed'"
              type="primary"
              size="small"
              link
              @click="handleResend(row.article_id)"
            >
              重发
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
