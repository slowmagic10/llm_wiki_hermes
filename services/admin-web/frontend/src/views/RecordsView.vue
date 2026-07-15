<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RefreshCw } from '@lucide/vue'
import { api, errorMessage } from '../api'
import MetricCard from '../components/MetricCard.vue'
import PageHeader from '../components/PageHeader.vue'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps<{ mode: string }>()
const rows = ref<any[]>([])
const error = ref('')
const loading = ref(false)
const isGaps = computed(() => props.mode === 'gaps')

async function load() {
  loading.value = true
  error.value = ''
  try { rows.value = await api.get(isGaps.value ? '/api/gaps' : '/api/audit') } catch (e) { error.value = errorMessage(e) } finally { loading.value = false }
}

function citationCount(value: unknown) {
  try { const data = typeof value === 'string' ? JSON.parse(value) : value; return Array.isArray(data) ? data.length : 0 } catch { return 0 }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader :title="isGaps ? '知识缺口' : '审计日志'" :description="isGaps ? '跟踪正式 Wiki 无法回答的问题，作为后续文档补充线索。' : '查看最近问答、可回答判定和引用数量。'">
      <button class="button primary" :disabled="loading" @click="load"><RefreshCw :size="16" />刷新</button>
    </PageHeader>
    <div v-if="error" class="notice is-error">{{ error }}</div>
    <div class="metrics-grid">
      <MetricCard :label="isGaps ? '缺口总数' : '审计总数'" :value="rows.length" hint="当前返回记录" />
      <MetricCard v-if="isGaps" label="Open" :value="rows.filter(x => x.status === 'open').length" hint="待补充" state="warn" />
      <MetricCard v-else label="可回答" :value="rows.filter(x => x.answerable).length" hint="answerable" state="ok" />
      <MetricCard v-if="!isGaps" label="未回答" :value="rows.filter(x => !x.answerable).length" hint="protected" />
    </div>
    <section class="panel table-panel">
      <div class="table-wrap">
        <table v-if="rows.length">
          <thead><tr v-if="isGaps"><th>最近出现</th><th>问题</th><th>频次</th><th>状态</th><th>建议标题</th></tr><tr v-else><th>时间</th><th>问题</th><th>判定</th><th>置信度</th><th>来源</th></tr></thead>
          <tbody>
            <tr v-for="(row,index) in rows" :key="index">
              <template v-if="isGaps">
                <td class="nowrap">{{ row.last_seen_at }}</td><td class="primary-cell">{{ row.query }}</td><td>{{ row.frequency }}</td><td><StatusBadge :status="row.status === 'open' ? 'warning' : 'ok'" :label="row.status" /></td><td>{{ row.suggested_title || '-' }}</td>
              </template>
              <template v-else>
                <td class="nowrap">{{ row.created_at }}</td><td class="primary-cell">{{ row.query }}</td><td><StatusBadge :status="row.answerable" :label="row.answerable ? '可回答' : '拒答'" /></td><td>{{ Number(row.confidence || 0).toFixed(3) }}</td><td>{{ citationCount(row.citations) }}</td>
              </template>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty-state">{{ loading ? '正在加载...' : '暂无记录' }}</div>
      </div>
    </section>
  </div>
</template>
