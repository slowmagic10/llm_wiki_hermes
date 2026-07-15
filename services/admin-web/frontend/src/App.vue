<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  Activity, Bot, BookOpen, Boxes, Braces, ChevronRight, CircleGauge, Database,
  FileInput, FileSearch, FolderOpen, Menu, RefreshCw, ScrollText, SearchCheck,
  Settings2, ShieldCheck, X
} from '@lucide/vue'
import { api } from './api'
import DashboardView from './views/DashboardView.vue'
import ModelsView from './views/ModelsView.vue'
import DomainsView from './views/DomainsView.vue'
import SyncView from './views/SyncView.vue'
import KnowledgeView from './views/KnowledgeView.vue'
import DocumentsView from './views/DocumentsView.vue'
import IngestView from './views/IngestView.vue'
import RagView from './views/RagView.vue'
import RecordsView from './views/RecordsView.vue'
import ToolsView from './views/ToolsView.vue'

type NavItem = { id: string; label: string; description: string; icon: any; component: any }
type NavGroup = { label: string; items: NavItem[] }

const groups: NavGroup[] = [
  {
    label: '总览',
    items: [
      { id: 'dashboard', label: '运行概览', description: '知识服务的实时运行状态', icon: CircleGauge, component: DashboardView },
      { id: 'health', label: '健康检查', description: '关键依赖与知识质量检查', icon: Activity, component: ToolsView },
      { id: 'models', label: '模型配置', description: 'RAG 模型与 LiteLLM 资源', icon: Bot, component: ModelsView },
      { id: 'domains', label: '领域管理', description: '知识域、Profile 与入口隔离', icon: Boxes, component: DomainsView },
    ],
  },
  {
    label: '知识维护',
    items: [
      { id: 'sync', label: '同步管理', description: 'Vault 拉取与索引刷新', icon: RefreshCw, component: SyncView },
      { id: 'knowledge', label: '知识地图', description: '结构、产品与显式关系', icon: Database, component: KnowledgeView },
      { id: 'documents', label: '文档浏览', description: '只读浏览 Vault 文档', icon: FolderOpen, component: DocumentsView },
      { id: 'ingest', label: '文档入库', description: 'PDF 抽取与 Markdown 标准化', icon: FileInput, component: IngestView },
      { id: 'schema', label: 'Schema 模板', description: 'Frontmatter 规范与模板', icon: Braces, component: ToolsView },
    ],
  },
  {
    label: '问答质量',
    items: [
      { id: 'rag', label: 'RAG 测试', description: '检索、重排与答案约束验证', icon: SearchCheck, component: RagView },
      { id: 'gaps', label: '知识缺口', description: '正式 Wiki 未覆盖的问题', icon: FileSearch, component: RecordsView },
      { id: 'audit', label: '审计日志', description: '问答记录与引用追踪', icon: ScrollText, component: RecordsView },
    ],
  },
  {
    label: '工具',
    items: [
      { id: 'obsidian', label: 'obsidian-wiki', description: '工具安装与 Vault 状态', icon: BookOpen, component: ToolsView },
    ],
  },
]

const allItems = groups.flatMap(group => group.items)
const initialId = location.hash.replace('#/', '') || 'dashboard'
const activeId = ref(allItems.some(item => item.id === initialId) ? initialId : 'dashboard')
const sidebarOpen = ref(false)
const health = ref<any>(null)
const now = ref('')
const active = computed(() => allItems.find(item => item.id === activeId.value) || allItems[0])

function navigate(id: string) {
  activeId.value = id
  location.hash = '/' + id
  sidebarOpen.value = false
}

async function refreshHealth() {
  try { health.value = await api.get('/api/health-detail') } catch { health.value = null }
}

onMounted(() => {
  refreshHealth()
  const updateClock = () => { now.value = new Date().toLocaleString('zh-CN', { hour12: false }) }
  updateClock()
  setInterval(updateClock, 30_000)
  window.addEventListener('hashchange', () => {
    const id = location.hash.replace('#/', '')
    if (allItems.some(item => item.id === id)) activeId.value = id
  })
})
</script>

<template>
  <div class="app-shell">
    <div v-if="sidebarOpen" class="sidebar-backdrop" @click="sidebarOpen = false"></div>
    <aside class="sidebar" :class="{ 'is-open': sidebarOpen }">
      <div class="brand">
        <div class="brand-mark"><BookOpen :size="19" /></div>
        <div>
          <strong>Knowledge Hub</strong>
          <span>企业知识管理控制台</span>
        </div>
        <button class="icon-button sidebar-close" title="关闭导航" @click="sidebarOpen = false"><X :size="18" /></button>
      </div>
      <nav class="navigation">
        <div v-for="group in groups" :key="group.label" class="nav-group">
          <div class="nav-group__label">{{ group.label }}</div>
          <button
            v-for="item in group.items"
            :key="item.id"
            class="nav-item"
            :class="{ 'is-active': activeId === item.id }"
            @click="navigate(item.id)"
          >
            <component :is="item.icon" :size="17" />
            <span>{{ item.label }}</span>
            <ChevronRight class="nav-item__arrow" :size="15" />
          </button>
        </div>
      </nav>
      <div class="sidebar-foot">
        <ShieldCheck :size="17" />
        <div><strong>正式知识只读问答</strong><span>内容仅由 Vault 人工维护</span></div>
      </div>
    </aside>

    <div class="workspace">
      <header class="topbar">
        <button class="icon-button mobile-menu" title="打开导航" @click="sidebarOpen = true"><Menu :size="19" /></button>
        <div class="topbar__title">
          <strong>{{ active.label }}</strong>
          <span>{{ active.description }}</span>
        </div>
        <div class="topbar__right">
          <button class="health-chip" title="刷新系统状态" @click="refreshHealth">
            <i :class="'is-' + (health?.summary?.overall || 'unknown')"></i>
            {{ health?.summary?.overall === 'ok' ? '系统正常' : health ? '需要检查' : '检查中' }}
          </button>
          <span class="topbar__time">{{ now }}</span>
          <button class="icon-button" title="系统设置" @click="navigate('models')"><Settings2 :size="18" /></button>
        </div>
      </header>
      <main class="main-content">
        <component :is="active.component" :key="activeId" :mode="activeId" @navigate="navigate" />
      </main>
    </div>
  </div>
</template>
