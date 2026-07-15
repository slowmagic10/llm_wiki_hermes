<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  BookOpen, Building2, Clipboard, FileCode2, ListChecks, PackageSearch, RefreshCw
} from '@lucide/vue'
import { api, errorMessage } from '../api'
import JsonDetails from '../components/JsonDetails.vue'
import MetricCard from '../components/MetricCard.vue'
import PageHeader from '../components/PageHeader.vue'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps<{ mode: string }>()
const data = ref<any>(null)
const error = ref('')
const loading = ref(false)
const schemaId = ref('')
const copied = ref(false)
const config = computed(() => ({
  health: ['健康检查', '聚合检查数据库、RAG、Milvus、LiteLLM、Vault、同步和知识质量。', '/api/health-detail'],
  schema: ['Schema 模板', '按知识场景选择标准 Frontmatter 和正文结构，所有模板默认只生成待审核草稿。', '/api/schema-template'],
  obsidian: ['obsidian-wiki', '检查容器内 obsidian-wiki 安装状态和 Vault 配置。', '/api/obsidian-wiki'],
} as any)[props.mode])
const templates = computed(() => data.value?.templates || [])
const selectedSchema = computed(() => {
  if (schemaId.value === 'reference') {
    return {
      id: 'reference',
      label: '字段规范',
      description: '通用字段、产品扩展字段和健康检查规则。',
      type: 'reference',
      content: data.value?.reference?.content || '',
    }
  }
  return templates.value.find((item: any) => item.id === schemaId.value) || templates.value[0]
})

function schemaIcon(id: string) {
  return ({
    general: BookOpen,
    product: PackageSearch,
    enterprise_handbook: Building2,
    technical: FileCode2,
    sop: ListChecks,
    reference: FileCode2,
  } as any)[id] || BookOpen
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.get(config.value[2])
    if (props.mode === 'schema') schemaId.value = data.value.default_template || data.value.templates?.[0]?.id || ''
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function copyTemplate() {
  if (!selectedSchema.value?.content) return
  await navigator.clipboard.writeText(selectedSchema.value.content)
  copied.value = true
  window.setTimeout(() => { copied.value = false }, 1600)
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader :title="config[0]" :description="config[1]">
      <button class="button primary" :disabled="loading" @click="load"><RefreshCw :size="16" />刷新</button>
    </PageHeader>
    <div v-if="error" class="notice is-error">{{ error }}</div>

    <template v-if="mode === 'health'">
      <div class="metrics-grid">
        <MetricCard label="检查项" :value="data?.summary?.checks ?? '-'" hint="checks" />
        <MetricCard label="正常" :value="data?.summary?.ok ?? '-'" hint="passed" state="ok" />
        <MetricCard label="警告" :value="data?.summary?.warnings ?? '-'" hint="warnings" :state="data?.summary?.warnings ? 'warn' : 'ok'" />
        <MetricCard label="异常" :value="data?.summary?.failed ?? '-'" hint="failed" :state="data?.summary?.failed ? 'bad' : 'ok'" />
      </div>
      <section class="panel">
        <div class="panel__head"><div><strong>检查矩阵</strong><span>{{ data?.summary?.checked_at }}</span></div></div>
        <div class="check-list">
          <div v-for="item in data?.checks || []" :key="item.name" class="check-row">
            <div><strong>{{ item.name }}</strong><span>{{ item.message }}</span></div>
            <StatusBadge :status="item.status" />
          </div>
        </div>
      </section>
    </template>

    <template v-else-if="mode === 'schema'">
      <section class="schema-library">
        <button
          v-for="item in templates"
          :key="item.id"
          class="schema-option"
          :class="{ active: schemaId === item.id }"
          @click="schemaId = item.id"
        >
          <span class="schema-option__icon"><component :is="schemaIcon(item.id)" :size="18" /></span>
          <span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span>
          <code>{{ item.type }}</code>
        </button>
        <button class="schema-option" :class="{ active: schemaId === 'reference' }" @click="schemaId = 'reference'">
          <span class="schema-option__icon"><FileCode2 :size="18" /></span>
          <span><strong>字段规范</strong><small>字段说明、状态规则和健康检查约束。</small></span>
          <code>reference</code>
        </button>
      </section>

      <div v-if="data?.notes?.length" class="schema-notes">
        <div v-for="note in data.notes" :key="note">{{ note }}</div>
      </div>

      <section class="panel code-panel schema-preview">
        <div class="panel__head">
          <div><strong>{{ selectedSchema?.label || '模板加载中' }}</strong><span>{{ selectedSchema?.description }}</span></div>
          <div class="panel-actions">
            <StatusBadge :status="selectedSchema?.id === 'reference' ? 'neutral' : 'warning'" :label="selectedSchema?.id === 'reference' ? '规范说明' : '默认草稿'" />
            <button class="icon-button" title="复制当前模板" @click="copyTemplate"><Clipboard :size="17" /></button>
          </div>
        </div>
        <div v-if="copied" class="copy-toast">已复制当前模板</div>
        <pre>{{ selectedSchema?.content || '正在加载...' }}</pre>
      </section>
    </template>

    <template v-else>
      <section class="panel tool-status">
        <div><span>安装状态</span><StatusBadge :status="data?.installed" :label="data?.installed ? '已安装' : '未安装'" /></div>
        <div><span>版本</span><strong>{{ data?.version || '-' }}</strong></div>
        <div><span>命令</span><code>{{ data?.command || '-' }}</code></div>
        <div><span>Vault</span><code>{{ data?.vault_path || '-' }}</code></div>
      </section>
    </template>
    <JsonDetails :value="data" />
  </div>
</template>
