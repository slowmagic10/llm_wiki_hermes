<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, RefreshCw, Save } from '@lucide/vue'
import { api, errorMessage } from '../api'
import JsonDetails from '../components/JsonDetails.vue'
import MetricCard from '../components/MetricCard.vue'
import PageHeader from '../components/PageHeader.vue'

const data = ref<any>(null)
const chatModel = ref('')
const rerankerModel = ref('')
const saving = ref(false)
const message = ref('')
const error = ref('')

const chatModels = computed(() => (data.value?.available_models || []).filter((x: string) => !/rerank|embed/i.test(x)))
const rerankModels = computed(() => (data.value?.available_models || []).filter((x: string) => /rerank/i.test(x)))
const embeddingModels = computed(() => (data.value?.available_models || []).filter((x: string) => /embed/i.test(x)))

async function load() {
  error.value = ''
  try {
    data.value = await api.get('/api/model-config')
    chatModel.value = data.value.effective?.chat_model || ''
    rerankerModel.value = data.value.effective?.reranker_model || ''
  } catch (e) { error.value = errorMessage(e) }
}

async function save() {
  saving.value = true
  message.value = ''
  error.value = ''
  try {
    await api.post('/api/model-config', { chat_model: chatModel.value, reranker_model: rerankerModel.value })
    message.value = '配置已保存，新请求将立即使用。'
    await load()
  } catch (e) { error.value = errorMessage(e) } finally { saving.value = false }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="模型配置" description="管理 Wiki/RAG 使用的模型；Hermes 对话模型不在这里修改。">
      <button class="button secondary" @click="load"><RefreshCw :size="16" />刷新列表</button>
      <button class="button primary" :disabled="saving || !chatModel || !rerankerModel" @click="save"><Save :size="16" />保存配置</button>
    </PageHeader>
    <div v-if="error" class="notice is-error"><AlertTriangle :size="17" />{{ error }}</div>
    <div v-if="message" class="notice is-success">{{ message }}</div>

    <div class="metrics-grid">
      <MetricCard label="可用模型" :value="data?.available_models?.length ?? '-'" hint="LiteLLM /v1/models" />
      <MetricCard label="回答模型" :value="data?.effective?.chat_model || '-'" hint="chat model" />
      <MetricCard label="Rerank" :value="data?.effective?.reranker_model || '-'" hint="reranker model" />
      <MetricCard label="Embedding" :value="data?.effective?.embedding_model || '-'" hint="切换后需要重新嵌入" />
    </div>

    <section class="panel">
      <div class="panel__head"><div><strong>RAG 模型选择</strong><span>{{ data?.settings_path || '加载中' }}</span></div></div>
      <div class="form-grid">
        <label class="field"><span>回答模型</span><select v-model="chatModel"><option v-for="model in chatModels" :key="model">{{ model }}</option></select><small>用于生成最终答案。</small></label>
        <label class="field"><span>Rerank 模型</span><select v-model="rerankerModel"><option v-for="model in rerankModels" :key="model">{{ model }}</option></select><small>用于候选文档重排。</small></label>
        <label class="field"><span>Embedding 模型</span><select disabled><option v-for="model in embeddingModels" :key="model">{{ model }}</option></select><small>当前只读，变更必须全量重新索引。</small></label>
      </div>
      <div class="inline-note">这里的配置不写入 Hermes，也不会重启任何模型服务。</div>
    </section>
    <JsonDetails :value="data" />
  </div>
</template>
