<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Document,
  Setting,
  DataBoard,
  Operation,
  Promotion,
  TrendCharts,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

const activeMenu = computed(() => route.path)

interface MenuItem {
  index: string
  title: string
  icon?: typeof Document
}

const menuItems: MenuItem[] = [
  { index: '/dashboard', title: '仪表盘', icon: DataBoard },
  { index: '/articles', title: '知识条目', icon: Document },
  { index: '/llm/providers', title: 'LLM 管理', icon: Setting },
  { index: '/workflow', title: '工作流', icon: Operation },
  { index: '/distributors', title: '分发渠道', icon: Promotion },
  { index: '/metrics', title: '指标监控', icon: TrendCharts },
]

function handleSelect(index: string): void {
  router.push(index)
}
</script>

<template>
  <el-container style="height: 100%">
    <el-aside width="200px" style="background: #304156">
      <div style="height: 60px; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 16px; font-weight: bold;">
        AI 知识库
      </div>
      <el-menu
        :default-active="activeMenu"
        background-color="#304156"
        text-color="#bfcbd9"
        active-text-color="#409eff"
        @select="handleSelect"
      >
        <el-menu-item v-for="item in menuItems" :key="item.index" :index="item.index">
          <el-icon v-if="item.icon"><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header style="display: flex; align-items: center; background: #fff; border-bottom: 1px solid #e6e6e6;">
        <span style="font-size: 18px; font-weight: 500;">{{ route.meta.title ?? '' }}</span>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>
