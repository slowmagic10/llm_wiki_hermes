<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { GitPullRequest, Layers3, RefreshCw, RotateCw } from '@lucide/vue'
import { api, errorMessage, pretty } from '../api'
import JsonDetails from '../components/JsonDetails.vue'
import PageHeader from '../components/PageHeader.vue'
import StatusBadge from '../components/StatusBadge.vue'

const status = ref<any>(null)
const running = ref('')
const output = ref('等待操作')
const error = ref('')

async function load() {
  try { status.value = await api.get('/api/sync-status') } catch (e) { error.value = errorMessage(e) }
}

async function run(endpoint: string, label: string) {
  running.value = endpoint
  error.value = ''
  output.value = label + '执行中，请勿重复提交。'
  try {
    const result = await api.post(endpoint)
    output.value = pretty(result)
    await load()
  } catch (e) {
    error.value = errorMessage(e)
    output.value = error.value
  } finally { running.value = '' }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="同步管理" description="从 Vault Git 仓库拉取正式文档，并刷新向量与全文索引。">
      <button class="button secondary" :disabled="!!running" @click="run('/api/git-pull', 'Git Pull')"><GitPullRequest :size="16" />Git Pull</button>
      <button class="button secondary" :disabled="!!running" @click="run('/api/sync-index', '重新索引')"><Layers3 :size="16" />重新索引</button>
      <button class="button primary" :disabled="!!running" @click="run('/api/full-sync', '完整同步')"><RotateCw :size="16" />完整同步</button>
    </PageHeader>
    <div class="sync-strip">
      <div><span>最近状态</span><StatusBadge :status="status?.status" /></div>
      <div><span>开始时间</span><strong>{{ status?.started_at || '-' }}</strong></div>
      <div><span>结束时间</span><strong>{{ status?.ended_at || '-' }}</strong></div>
      <button class="icon-button" title="刷新状态" @click="load"><RefreshCw :size="17" /></button>
    </div>
    <div v-if="error" class="notice is-error">{{ error }}</div>
    <section class="panel terminal-panel">
      <div class="panel__head"><div><strong>执行输出</strong><span>完整同步最长可能需要数分钟</span></div><StatusBadge v-if="running" status="running" label="执行中" /></div>
      <pre>{{ output }}</pre>
    </section>
    <JsonDetails :value="status" />
  </div>
</template>
