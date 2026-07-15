<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RefreshCw } from '@lucide/vue'
import { api, errorMessage } from '../api'
import JsonDetails from '../components/JsonDetails.vue'
import MetricCard from '../components/MetricCard.vue'
import PageHeader from '../components/PageHeader.vue'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps<{ mode: string }>()
const data = ref<any>(null)
const error = ref('')
const loading = ref(false)
const config = computed(() => ({
  health: ['健康检查', '聚合检查数据库、RAG、Milvus、LiteLLM、Vault、同步和知识质量。', '/api/health-detail'],
  schema: ['Schema 模板', '查看当前 Wiki frontmatter 规范和标准 Markdown 模板。', '/api/schema-template'],
  obsidian: ['obsidian-wiki', '检查容器内 obsidian-wiki 安装状态和 Vault 配置。', '/api/obsidian-wiki'],
} as any)[props.mode])

async function load() {
  loading.value = true
  error.value = ''
  try { data.value = await api.get(config.value[2]) } catch (e) { error.value = errorMessage(e) } finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div>
    <PageHeader :title="config[0]" :description="config[1]"><button class="button primary" :disabled="loading" @click="load"><RefreshCw :size="16" />刷新</button></PageHeader>
    <div v-if="error" class="notice is-error">{{ error }}</div>
    <template v-if="mode === 'health'">
      <div class="metrics-grid">
        <MetricCard label="检查项" :value="data?.summary?.checks ?? '-'" hint="checks" />
        <MetricCard label="正常" :value="data?.summary?.ok ?? '-'" hint="passed" state="ok" />
        <MetricCard label="警告" :value="data?.summary?.warnings ?? '-'" hint="warnings" :state="data?.summary?.warnings ? 'warn' : 'ok'" />
        <MetricCard label="异常" :value="data?.summary?.failed ?? '-'" hint="failed" :state="data?.summary?.failed ? 'bad' : 'ok'" />
      </div>
      <section class="panel"><div class="panel__head"><div><strong>检查矩阵</strong><span>{{ data?.summary?.checked_at }}</span></div></div>
        <div class="check-list"><div v-for="item in data?.checks || []" :key="item.name" class="check-row"><div><strong>{{ item.name }}</strong><span>{{ item.message }}</span></div><StatusBadge :status="item.status" /></div></div>
      </section>
    </template>
    <template v-else-if="mode === 'schema'">
      <section class="panel code-panel"><pre>{{ data?.content || '正在加载...' }}</pre></section>
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
