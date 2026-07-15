<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChevronLeft, FileText, Folder, Home, RefreshCw } from '@lucide/vue'
import { api, errorMessage } from '../api'
import PageHeader from '../components/PageHeader.vue'
import StatusBadge from '../components/StatusBadge.vue'

const listing = ref<any>({ entries: [] })
const current = ref('.')
const document = ref<any>(null)
const error = ref('')
const meta = computed(() => parseFrontmatter(document.value?.content || '').meta)
const body = computed(() => parseFrontmatter(document.value?.content || '').body)

function parseFrontmatter(text: string) {
  if (!text.startsWith('---')) return { meta: null as any, body: text }
  const end = text.indexOf('\n---', 3)
  if (end < 0) return { meta: null as any, body: text }
  const raw = text.slice(3, end).trim()
  const data: Record<string, any> = {}
  let key = ''
  for (const line of raw.split('\n')) {
    const match = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/)
    if (match) { key = match[1]; data[key] = match[2].replace(/^['"]|['"]$/g, '') }
    else if (key && line.trim().startsWith('- ')) {
      if (!Array.isArray(data[key])) data[key] = data[key] ? [data[key]] : []
      data[key].push(line.trim().slice(2).replace(/^['"]|['"]$/g, ''))
    }
  }
  return { meta: data, body: text.slice(text.indexOf('\n', end + 4) + 1) }
}
async function load(path = '.') {
  error.value = ''
  try { listing.value = await api.get('/api/files?path=' + encodeURIComponent(path)); current.value = listing.value.path }
  catch (e) { error.value = errorMessage(e) }
}
async function open(entry: any) {
  if (entry.type === 'dir') return load(entry.path)
  try { document.value = await api.get('/api/file?path=' + encodeURIComponent(entry.path)) } catch (e) { error.value = errorMessage(e) }
}
onMounted(() => load())
</script>

<template>
  <div>
    <PageHeader title="文档浏览" description="只读浏览远端 Vault 中的 Markdown 和 Frontmatter。">
      <button class="button secondary" @click="load(current)"><RefreshCw :size="16" />刷新目录</button>
    </PageHeader>
    <div v-if="error" class="notice is-error">{{ error }}</div>
    <div class="documents-layout">
      <section class="panel file-browser">
        <div class="panel__head"><div><strong>Vault 文件</strong><span>{{ current }}</span></div><button class="icon-button" title="根目录" @click="load('.')"><Home :size="17" /></button></div>
        <button v-if="listing.parent !== null" class="file-row" @click="load(listing.parent)"><ChevronLeft :size="17" /><span>返回上级</span></button>
        <button v-for="entry in listing.entries" :key="entry.path" class="file-row" @click="open(entry)">
          <Folder v-if="entry.type === 'dir'" :size="17" /><FileText v-else :size="17" /><span>{{ entry.name }}</span><small>{{ entry.type === 'dir' ? 'DIR' : 'MD' }}</small>
        </button>
        <div v-if="!listing.entries?.length" class="empty-state">空目录</div>
      </section>
      <section class="panel document-preview">
        <div class="panel__head"><div><strong>{{ meta?.title || document?.path?.split('/').pop() || '选择文档' }}</strong><span>{{ document?.path || '选择左侧 Markdown 文件预览' }}</span></div><StatusBadge v-if="document" :status="meta?.status === 'active' ? 'ok' : 'warning'" :label="meta?.status || (meta ? 'metadata' : 'missing')" /></div>
        <pre>{{ body || '等待选择文档...' }}</pre>
      </section>
      <section class="panel metadata-panel">
        <div class="panel__head"><div><strong>Frontmatter</strong><span>结构化元数据</span></div></div>
        <dl v-if="meta"><div v-for="(value,key) in meta" :key="key"><dt>{{ key }}</dt><dd>{{ Array.isArray(value) ? value.join(', ') : value || '-' }}</dd></div></dl>
        <div v-else class="empty-state">选择文档后显示元数据</div>
      </section>
    </div>
  </div>
</template>
