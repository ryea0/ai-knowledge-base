import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/layouts/DefaultLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '仪表盘' },
      },
      {
        path: 'articles',
        name: 'Articles',
        component: () => import('@/views/ArticleListView.vue'),
        meta: { title: '知识条目' },
      },
      {
        path: 'articles/:id',
        name: 'ArticleDetail',
        component: () => import('@/views/ArticleDetailView.vue'),
        meta: { title: '条目详情' },
      },
      {
        path: 'llm/providers',
        name: 'LlmProviders',
        component: () => import('@/views/LlmProviderView.vue'),
        meta: { title: 'LLM 供应商' },
      },
      {
        path: 'llm/providers/:id',
        name: 'LlmProviderDetail',
        component: () => import('@/views/LlmProviderDetailView.vue'),
        meta: { title: '供应商详情' },
      },
      {
        path: 'workflow',
        name: 'Workflow',
        component: () => import('@/views/WorkflowView.vue'),
        meta: { title: '工作流管理' },
      },
      {
        path: 'distributors',
        name: 'Distributors',
        component: () => import('@/views/DistributionView.vue'),
        meta: { title: '分发渠道' },
      },
      {
        path: 'metrics',
        name: 'Metrics',
        component: () => import('@/views/MetricsView.vue'),
        meta: { title: '指标监控' },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
