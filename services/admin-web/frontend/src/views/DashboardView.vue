<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, ArrowRight, CheckCircle2, RefreshCw } from '@lucide/vue'
import { api, errorMessage } from '../api'
import JsonDetails from '../components/JsonDetails.vue'
import MetricCard from '../components/MetricCard.vue'
import PageHeader from '../components/PageHeader.vue'
import StatusBadge from '../components/StatusBadge.vue'

const emit = defineEmits<{ navigate: [id: string] }>()
const status = ref<any>(null)
const health = ref<any>(null)
const loading = ref(false)
const error = ref('')
const checks = computed(() => health.value?.checks || [])
const overall = computed(() => health.value?.summary?.overall || 'unknown')

async function load() {
  loading.value = true
  error.value = ''
  try {
    ;[status.value, health.value] = await Promise.all([
      api.get('/api/status'),
      api.get('/api/health-detail'),
    ])
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

function check(name: string) {
  return checks.value.find((item: any) => item.name === name) || {}
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="运行概览" description="集中查看服务可用性、知识规模和待处理事项。">
      <button class="button secondary" :disabled="loading" @click="emit('navigate', 'health')">查看检查项</button>
      <button class="button primary" :disabled="loading" @click="load"><RefreshCw :size="16" />刷新</button>
    </PageHeader>

    <div v-if="error" class="notice is-error"><AlertTriangle :size="17" />{{ error }}</div>

    <section class="system-banner" :class="'is-' + overall">
      <div class="system-banner__icon"><CheckCircle2 v-if="overall === 'ok'" :size="24" /><AlertTriangle v-else :size="24" /></div>
      <div>
        <StatusBadge :status="overall" :label="overall === 'ok' ? '运行正常' : '需要检查'" />
        <h2>{{ overall === 'ok' ? '知识服务主链路可用' : '部分检查项需要处理' }}</h2>
        <p v-if="health">共 {{ health.summary.checks }} 项检查，异常 {{ health.summary.failed }} 项，警告 {{ health.summary.warnings }} 项。</p>
        <p v-else>正在读取服务状态。</p>
      </div>
      <button class="button secondary" @click="emit('navigate', 'rag')">验证一次问答<ArrowRight :size="16" /></button>
    </section>

    <div class="metrics-grid">
      <MetricCard label="正式文档" :value="status?.counts?.documents ?? '-'" hint="documents" />
      <MetricCard label="检索片段" :value="status?.counts?.chunks ?? '-'" hint="indexed chunks" />
      <MetricCard label="索引文件" :value="status?.counts?.indexed_files ?? '-'" hint="indexed files" />
      <MetricCard label="开放缺口" :value="status?.counts?.knowledge_gaps_open ?? '-'" hint="待补充问题" :state="status?.counts?.knowledge_gaps_open ? 'warn' : 'ok'" />
      <MetricCard label="审计记录" :value="status?.counts?.audit_logs ?? '-'" hint="answer logs" />
    </div>

    <div class="content-grid two">
      <section class="panel">
        <div class="panel__head"><div><strong>系统链路</strong><span>关键依赖的最近检查结果</span></div></div>
        <div class="pipeline-list">
          <div v-for="item in ['postgres','rag_api','milvus','litellm_models','vault_git','sync_status']" :key="item" class="pipeline-row">
            <div class="pipeline-row__line"><i :class="'is-' + (check(item).status || 'neutral')"></i></div>
            <div><strong>{{ item }}</strong><span>{{ check(item).message || '等待检查' }}</span></div>
            <StatusBadge :status="check(item).status" />
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel__head"><div><strong>知识维护</strong><span>当前优先关注的维护状态</span></div></div>
        <div class="task-list">
          <button class="task-row" @click="emit('navigate', 'gaps')">
            <div><strong>知识缺口</strong><span>{{ status?.counts?.knowledge_gaps_open || 0 }} 条问题等待补充</span></div>
            <StatusBadge :status="status?.counts?.knowledge_gaps_open ? 'warning' : 'ok'" :label="status?.counts?.knowledge_gaps_open ? '待处理' : '已清零'" />
          </button>
          <button class="task-row" @click="emit('navigate', 'sync')">
            <div><strong>最近同步</strong><span>{{ status?.sync_status?.ended_at || status?.sync_status?.message || '暂无记录' }}</span></div>
            <StatusBadge :status="status?.sync_status?.status" />
          </button>
          <button class="task-row" @click="emit('navigate', 'domains')">
            <div><strong>领域注册表</strong><span>{{ check('domain_registry').message || '等待检查' }}</span></div>
            <StatusBadge :status="check('domain_registry').status" />
          </button>
        </div>
      </section>
    </div>
    <JsonDetails :value="{ status, health }" />
  </div>
</template>
