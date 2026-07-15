<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Play, SearchCheck } from '@lucide/vue'
import { api, errorMessage } from '../api'
import JsonDetails from '../components/JsonDetails.vue'
import PageHeader from '../components/PageHeader.vue'
import StatusBadge from '../components/StatusBadge.vue'

const registry = ref<any>(null)
const query = ref('OSFP-QDD-CU3可以用于CX7 NIC互连吗？')
const domain = ref('default')
const profile = ref('product')
const result = ref<any>(null)
const running = ref(false)
const error = ref('')
const domains = computed(() => Object.entries(registry.value?.domains || {}).filter(([,cfg]: any) => cfg.enabled) as [string, any][])
const profiles = computed(() => Object.entries(registry.value?.profiles || {}) as [string, any][])

async function loadDomains() {
  registry.value = await api.get('/api/domains')
  domain.value = registry.value.default_domain || 'default'
  profile.value = registry.value.domains?.[domain.value]?.profile || profiles.value[0]?.[0] || 'product'
}
function changeDomain() { profile.value = registry.value?.domains?.[domain.value]?.profile || profile.value }
async function run() {
  if (!query.value.trim()) return
  running.value = true
  error.value = ''
  result.value = null
  try { result.value = await api.post('/api/rag-test', { query: query.value.trim(), domain: domain.value, profile: profile.value }) }
  catch (e) { error.value = errorMessage(e) } finally { running.value = false }
}
onMounted(loadDomains)
</script>

<template>
  <div>
    <PageHeader title="RAG 测试" description="直接验证正式 Wiki 的检索、Rerank、领域隔离和答案约束。" />
    <div class="rag-layout">
      <div class="stack">
        <section class="panel">
          <div class="panel__head"><div><strong>测试问题</strong><span>仅允许使用正式 Wiki 来源</span></div></div>
          <div class="form-grid">
            <label class="field"><span>知识领域</span><select v-model="domain" @change="changeDomain"><option v-for="[id,cfg] in domains" :key="id" :value="id">{{ cfg.display_name || id }}</option></select></label>
            <label class="field"><span>检索 Profile</span><select v-model="profile"><option v-for="[id,cfg] in profiles" :key="id" :value="id">{{ cfg.display_name || id }}</option></select></label>
          </div>
          <label class="field"><span>问题</span><textarea v-model="query" rows="7" placeholder="输入要验证的问题"></textarea></label>
          <div class="quick-queries">
            <button @click="query='FTLC4353RHPL对应我司哪个型号，使用场景是什么？'">型号对应</button>
            <button @click="query='OSFP-QDD-CU3可以用于CX7 NIC互连吗？'">兼容性</button>
            <button @click="query='火星基地的咖啡机采购型号是什么？'">未命中保护</button>
          </div>
          <button class="button primary wide" :disabled="running || !query.trim()" @click="run"><Play :size="16" />{{ running ? '检索与生成中...' : '运行 RAG 测试' }}</button>
        </section>
        <section class="panel">
          <div class="panel__head"><div><strong>判定</strong><span>answerability guard</span></div><StatusBadge v-if="result" :status="result.answerable" :label="result.answerable ? '可回答' : '不可回答'" /></div>
          <div class="answer-metrics">
            <div><span>置信度</span><strong>{{ result?.confidence ?? '-' }}</strong></div>
            <div><span>原因</span><strong>{{ result?.reason || '-' }}</strong></div>
            <div><span>领域</span><strong>{{ result?.domain || domain }}</strong></div>
            <div><span>Profile</span><strong>{{ result?.profile || profile }}</strong></div>
          </div>
        </section>
      </div>
      <div class="stack">
        <section class="panel answer-panel">
          <div class="panel__head"><div><strong>答案预览</strong><span>final_answer</span></div><SearchCheck :size="18" /></div>
          <div v-if="error" class="notice is-error">{{ error }}</div>
          <div class="answer-copy">{{ result?.final_answer || (running ? '正在生成答案...' : '等待测试') }}</div>
        </section>
        <section class="panel">
          <div class="panel__head"><div><strong>引用来源</strong><span>{{ result?.citations?.length || 0 }} 条</span></div></div>
          <div class="citation-list">
            <div v-for="(citation,index) in result?.citations || []" :key="index" class="citation-row">
              <b>{{ Number(index) + 1 }}</b><div><strong>{{ citation.path || '-' }}</strong><span>{{ citation.heading || '' }} · score={{ citation.score ?? '-' }}</span></div>
            </div>
            <div v-if="!result?.citations?.length" class="empty-state">暂无来源</div>
          </div>
        </section>
        <JsonDetails :value="result" />
      </div>
    </div>
  </div>
</template>
