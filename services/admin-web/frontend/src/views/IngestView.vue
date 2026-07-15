<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Clipboard, Download, FileUp, Sparkles, Trash2 } from '@lucide/vue'
import { api, errorMessage } from '../api'
import JsonDetails from '../components/JsonDetails.vue'
import PageHeader from '../components/PageHeader.vue'
import StatusBadge from '../components/StatusBadge.vue'

const raw = ref('')
const domain = ref('default')
const schemaId = ref('general')
const owner = ref('nick')
const templates = ref<any[]>([])
const pdf = ref<any>(null)
const result = ref<any>(null)
const busy = ref('')
const error = ref('')
const selectedTemplate = computed(() => templates.value.find((item: any) => item.id === schemaId.value))

async function extract(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  busy.value = 'pdf'; error.value = ''
  try { pdf.value = await api.upload('/api/extract-pdf', 'file', file); raw.value = pdf.value.extracted_markdown || '' }
  catch (e) { error.value = errorMessage(e) } finally { busy.value = '' }
}
async function rewrite() {
  if (!raw.value.trim()) return
  busy.value = 'rewrite'; error.value = ''; result.value = null
  try { result.value = await api.post('/api/rewrite-document', { raw_markdown: raw.value, domain: domain.value, schema_id: schemaId.value, owner: owner.value }) }
  catch (e) { error.value = errorMessage(e) } finally { busy.value = '' }
}
async function loadTemplates() {
  try {
    const data = await api.get('/api/schema-template')
    templates.value = data.templates || []
    schemaId.value = data.default_template || templates.value[0]?.id || 'general'
  } catch (e) { error.value = errorMessage(e) }
}
onMounted(loadTemplates)
watch(schemaId, () => { result.value = null })
async function copy() { if (result.value?.rewritten_markdown) await navigator.clipboard.writeText(result.value.rewritten_markdown) }
function download() {
  const markdown = result.value?.rewritten_markdown
  if (!markdown) return
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'wiki-draft.md'; link.click(); URL.revokeObjectURL(link.href)
}
function clear() { raw.value = ''; pdf.value = null; result.value = null; error.value = '' }
</script>

<template>
  <div>
    <PageHeader title="文档入库" description="抽取文本型 PDF 或粗糙 Markdown，清洗并生成符合 Schema 的人工审核草稿。">
      <button class="button secondary" @click="clear"><Trash2 :size="16" />清空</button>
      <button class="button primary" :disabled="!!busy || !raw.trim()" @click="rewrite"><Sparkles :size="16" />{{ busy === 'rewrite' ? '生成中...' : '生成标准草稿' }}</button>
    </PageHeader>
    <div v-if="error" class="notice is-error">{{ error }}</div>
    <div class="ingest-layout">
      <div class="stack">
        <section class="panel">
          <div class="panel__head"><div><strong>原始内容</strong><span>不会自动写入 Vault</span></div></div>
          <div class="form-grid">
            <label class="field"><span>Domain</span><input v-model="domain" /></label>
            <label class="field">
              <span>Schema 模板</span>
              <select v-model="schemaId">
                <option v-for="item in templates" :key="item.id" :value="item.id">{{ item.label }} · {{ item.type }}</option>
              </select>
            </label>
            <label class="field"><span>Frontmatter type</span><input :value="selectedTemplate?.type || '-'" readonly /></label>
            <label class="field"><span>Owner</span><input v-model="owner" /></label>
          </div>
          <div v-if="selectedTemplate" class="template-context">
            <div><strong>{{ selectedTemplate.label }}</strong><code>{{ selectedTemplate.id }}</code></div>
            <p>{{ selectedTemplate.description }}</p>
            <span>生成时会强制使用 type={{ selectedTemplate.type }} 及该模板的正文结构。</span>
          </div>
          <label class="upload-button"><FileUp :size="17" /><span>{{ busy === 'pdf' ? '正在抽取 PDF...' : '选择文本型 PDF' }}</span><input type="file" accept=".pdf,application/pdf" @change="extract" /></label>
          <textarea v-model="raw" class="source-editor" placeholder="粘贴原始 Markdown、制度条款、技术资料、流程记录或其他来源内容。信息不完整也可以。"></textarea>
        </section>
        <section class="panel">
          <div class="panel__head"><div><strong>PDF 抽取报告</strong><span>不执行 OCR</span></div><StatusBadge v-if="pdf" :status="pdf.can_rewrite" :label="pdf.can_rewrite ? '可重写' : '需检查'" /></div>
          <div v-if="pdf" class="report-grid"><div><span>文件</span><strong>{{ pdf.filename }}</strong></div><div><span>页数</span><strong>{{ pdf.extracted_pages }}/{{ pdf.pages }}</strong></div><div><span>字符</span><strong>{{ pdf.total_text_chars }}</strong></div><div><span>告警</span><strong>{{ pdf.warnings?.length || 0 }}</strong></div></div>
          <div v-else class="empty-state">选择 PDF 后显示抽取质量。</div>
        </section>
        <section class="panel">
          <div class="panel__head"><div><strong>审核报告</strong><span>{{ result?.selected_schema?.label || selectedTemplate?.label || '所选模板' }} · 发布前必须人工确认</span></div><StatusBadge v-if="result" :status="result.validation?.ok ? 'ok' : 'warning'" :label="result.validation?.ok ? '草稿通过' : '需要确认'" /></div>
          <div v-if="result" class="review-blocks">
            <div><span>建议路径</span><strong>{{ result.review_report?.suggested_path || '-' }}</strong></div>
            <div><span>缺失字段</span><p>{{ (result.review_report?.missing_fields || result.validation?.missing_required_fields || []).join('、') || '无' }}</p></div>
            <div><span>待确认事实</span><p>{{ (result.review_report?.uncertain_claims || []).join('、') || '无' }}</p></div>
            <div><span>已清洗内容</span><p>{{ (result.review_report?.removed_irrelevant_content || []).join('、') || '无' }}</p></div>
          </div>
          <div v-else class="empty-state">生成草稿后显示缺口和清洗报告。</div>
        </section>
      </div>
      <div class="stack">
        <section class="panel draft-panel">
          <div class="panel__head"><div><strong>标准 Markdown 草稿</strong><span>仅供人工审核</span></div><div class="panel-actions"><button class="icon-button" title="复制" @click="copy"><Clipboard :size="17" /></button><button class="icon-button" title="下载 Markdown" @click="download"><Download :size="17" /></button></div></div>
          <pre>{{ result?.rewritten_markdown || (busy === 'rewrite' ? '正在生成...' : '等待生成...') }}</pre>
        </section>
        <JsonDetails :value="result" />
      </div>
    </div>
  </div>
</template>
