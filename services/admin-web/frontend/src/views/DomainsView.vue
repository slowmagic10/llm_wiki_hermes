<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { AlertTriangle, Check, Plus, RefreshCw, Save, X } from '@lucide/vue'
import { api, errorMessage, pretty } from '../api'
import JsonDetails from '../components/JsonDetails.vue'
import MetricCard from '../components/MetricCard.vue'
import PageHeader from '../components/PageHeader.vue'
import StatusBadge from '../components/StatusBadge.vue'

const registry = ref<any>(null)
const editorOpen = ref(false)
const editingId = ref('')
const result = ref<any>(null)
const message = ref('')
const error = ref('')
const busy = ref(false)

const form = reactive<any>({
  id: '', display_name: '', description: '', profile: 'product',
  vault_subpath: '', target_vault_subpath: '', isolation_mode: 'domain_subpath',
  entrypoint: '', entrypoint_aliases: '', entrypoint_platforms: 'qqbot',
  hermes_hook: '', enabled: true, make_default: false,
  rag_base_url: 'http://rag-api:18080',
  hermes_rag_base_url: 'http://127.0.0.1:18080',
  sync_status_file: '/root/llm_wiki_hermes/logs/llm-wiki-sync-status.json',
  vector_backend: 'milvus', vector_collection: 'llm_wiki_chunks_v2',
})
const domainEntries = computed(() => Object.entries(registry.value?.domains || {}) as [string, any][])
const profileEntries = computed(() => Object.entries(registry.value?.profiles || {}) as [string, any][])

async function load() {
  error.value = ''
  try { registry.value = await api.get('/api/domains') } catch (e) { error.value = errorMessage(e) }
}

function list(value: string) {
  return [...new Set(String(value || '').split(/[\n,，]/).map(x => x.trim()).filter(Boolean))]
}

function reset() {
  Object.assign(form, {
    id: '', display_name: '', description: '', profile: profileEntries.value[0]?.[0] || 'product',
    vault_subpath: '', target_vault_subpath: '', isolation_mode: 'domain_subpath',
    entrypoint: '', entrypoint_aliases: '', entrypoint_platforms: 'qqbot',
    hermes_hook: '', enabled: true, make_default: false,
    rag_base_url: 'http://rag-api:18080', hermes_rag_base_url: 'http://127.0.0.1:18080',
    sync_status_file: '/root/llm_wiki_hermes/logs/llm-wiki-sync-status.json',
    vector_backend: 'milvus', vector_collection: 'llm_wiki_chunks_v2',
  })
}

function open(id = '') {
  reset()
  editingId.value = id
  if (id) {
    const cfg = registry.value.domains[id]
    Object.assign(form, cfg, {
      id,
      entrypoint_aliases: (cfg.entrypoint_aliases || []).join('\n'),
      entrypoint_platforms: (cfg.entrypoint_platforms || []).join(', '),
      make_default: id === registry.value.default_domain,
    })
  }
  editorOpen.value = true
  result.value = null
  message.value = id ? '正在编辑 ' + id : '创建新领域'
}

function suggest() {
  if (editingId.value || !form.id) return
  if (!form.vault_subpath) form.vault_subpath = 'domains/' + form.id
  if (!form.target_vault_subpath) form.target_vault_subpath = 'domains/' + form.id
  if (!form.entrypoint) form.entrypoint = '/' + form.id + 'wiki'
  if (!form.hermes_hook) form.hermes_hook = 'llm_wiki_' + form.id.replace(/-/g, '_') + '_router'
}

function payload() {
  return {
    display_name: form.display_name, description: form.description, profile: form.profile,
    vault_subpath: form.vault_subpath, target_vault_subpath: form.target_vault_subpath,
    isolation_mode: form.isolation_mode, rag_base_url: form.rag_base_url,
    sync_status_file: form.sync_status_file, vector_backend: form.vector_backend,
    vector_collection: form.vector_collection, entrypoint: form.entrypoint,
    entrypoint_aliases: list(form.entrypoint_aliases),
    entrypoint_platforms: list(form.entrypoint_platforms),
    hermes_hook: form.hermes_hook, hermes_rag_base_url: form.hermes_rag_base_url,
    enabled: form.enabled, make_default: form.make_default,
  }
}

async function validate() {
  suggest()
  if (!form.id) return
  busy.value = true
  try {
    result.value = await api.post('/api/domains/validate?domain_id=' + encodeURIComponent(form.id), payload())
    message.value = result.value.ok ? '校验通过' : '校验未通过'
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}

async function save() {
  suggest()
  if (!form.id) return
  busy.value = true
  error.value = ''
  try {
    result.value = await api.put('/api/domains/' + encodeURIComponent(form.id), payload())
    message.value = '领域已保存；入口变化后请应用配置。'
    editingId.value = form.id
    await load()
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}

async function applyHooks() {
  busy.value = true
  try {
    result.value = await api.post('/api/domain-hooks/apply')
    message.value = result.value.restart_required ? '入口配置已生成，需要按返回命令重启 Hermes。' : '入口配置已是最新。'
    await load()
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="领域管理" description="以独立 Vault 边界、检索 Profile 和 Hermes 入口隔离不同知识场景。">
      <button class="button secondary" @click="load"><RefreshCw :size="16" />刷新</button>
      <button class="button secondary" @click="open()"><Plus :size="16" />新增领域</button>
      <button class="button primary" :disabled="busy" @click="applyHooks"><Check :size="16" />应用入口配置</button>
    </PageHeader>
    <div v-if="error" class="notice is-error"><AlertTriangle :size="17" />{{ error }}</div>
    <div v-if="message" class="notice">{{ message }}</div>
    <div class="metrics-grid">
      <MetricCard label="领域总数" :value="registry?.summary?.domains ?? '-'" hint="registered domains" />
      <MetricCard label="已启用" :value="registry?.summary?.enabled ?? '-'" hint="enabled" state="ok" />
      <MetricCard label="目录隔离" :value="registry?.summary?.isolated ?? '-'" hint="isolated vaults" />
      <MetricCard label="配置问题" :value="registry?.summary?.issues ?? '-'" hint="validation issues" :state="registry?.summary?.issues ? 'warn' : 'ok'" />
    </div>

    <section class="panel">
      <div class="panel__head"><div><strong>领域注册表</strong><span>{{ registry?.registry_path }}</span></div></div>
      <div class="domain-grid">
        <button v-for="[id, cfg] in domainEntries" :key="id" class="domain-card" @click="open(id)">
          <div class="domain-card__head"><div><strong>{{ cfg.display_name || id }}</strong><code>{{ id }}</code></div><StatusBadge :status="cfg.enabled" :label="cfg.enabled ? '启用' : '停用'" /></div>
          <p>{{ cfg.description || '未填写领域说明' }}</p>
          <dl>
            <div><dt>Vault</dt><dd>{{ cfg.vault_subpath }}</dd></div>
            <div><dt>入口</dt><dd>{{ cfg.entrypoint }}</dd></div>
            <div><dt>Profile</dt><dd>{{ cfg.profile }}</dd></div>
            <div><dt>文档</dt><dd>{{ cfg.vault_status?.markdown_files ?? '-' }}</dd></div>
          </dl>
        </button>
      </div>
    </section>

    <section v-if="editorOpen" class="panel editor-panel">
      <div class="panel__head">
        <div><strong>{{ editingId ? '编辑领域 · ' + editingId : '新增领域' }}</strong><span>领域 ID 创建后不可修改</span></div>
        <button class="icon-button" title="关闭" @click="editorOpen = false"><X :size="18" /></button>
      </div>
      <div class="form-grid three">
        <label class="field"><span>领域 ID</span><input v-model.trim="form.id" :disabled="!!editingId" placeholder="ops" @blur="suggest" /></label>
        <label class="field"><span>显示名称</span><input v-model.trim="form.display_name" placeholder="运维知识库" /></label>
        <label class="field"><span>处理 Profile</span><select v-model="form.profile"><option v-for="[id,cfg] in profileEntries" :key="id" :value="id">{{ cfg.display_name || id }}</option></select></label>
        <label class="field span-2"><span>领域说明</span><input v-model.trim="form.description" placeholder="该领域承载的正式知识范围" /></label>
        <label class="toggle-field"><input v-model="form.enabled" type="checkbox" /><span>启用领域</span></label>
        <label class="field"><span>Vault 子目录</span><input v-model.trim="form.vault_subpath" placeholder="domains/ops" /></label>
        <label class="field"><span>目标子目录</span><input v-model.trim="form.target_vault_subpath" placeholder="domains/ops" /></label>
        <label class="field"><span>隔离模式</span><select v-model="form.isolation_mode"><option>domain_subpath</option><option>legacy_root</option></select></label>
        <label class="field"><span>主入口</span><input v-model.trim="form.entrypoint" placeholder="/opswiki" /></label>
        <label class="field"><span>Hermes Hook</span><input v-model.trim="form.hermes_hook" /></label>
        <label class="field"><span>入口平台</span><input v-model.trim="form.entrypoint_platforms" /></label>
        <label class="field span-2"><span>入口别名</span><textarea v-model="form.entrypoint_aliases" rows="3" placeholder="每行一个触发词"></textarea></label>
        <label class="field"><span>向量后端</span><select v-model="form.vector_backend"><option>milvus</option><option>pgvector</option></select></label>
        <label class="field"><span>Collection</span><input v-model.trim="form.vector_collection" /></label>
        <label class="toggle-field"><input v-model="form.make_default" type="checkbox" /><span>设为默认领域</span></label>
      </div>
      <details class="advanced">
        <summary>高级运行地址</summary>
        <div class="form-grid">
          <label class="field"><span>容器内 RAG 地址</span><input v-model.trim="form.rag_base_url" /></label>
          <label class="field"><span>Hermes RAG 地址</span><input v-model.trim="form.hermes_rag_base_url" /></label>
          <label class="field span-2"><span>同步状态文件</span><input v-model.trim="form.sync_status_file" /></label>
        </div>
      </details>
      <div class="form-actions">
        <button class="button secondary" :disabled="busy" @click="validate"><Check :size="16" />校验</button>
        <button class="button primary" :disabled="busy" @click="save"><Save :size="16" />保存领域</button>
      </div>
      <pre v-if="result" class="result-output">{{ pretty(result) }}</pre>
    </section>

    <section class="panel">
      <div class="panel__head"><div><strong>检索与答案 Profiles</strong><span>由 domains.yml 统一维护</span></div></div>
      <div class="profile-list">
        <div v-for="[id, cfg] in profileEntries" :key="id" class="profile-row">
          <div><strong>{{ cfg.display_name || id }}</strong><code>{{ id }}</code></div>
          <span>{{ (cfg.answer_contract || []).join(' · ') }}</span>
          <div class="profile-stats"><b>Top K {{ cfg.retrieval?.rerank_top_k }}</b><b>阈值 {{ cfg.retrieval?.answerable_threshold }}</b><b>来源 {{ cfg.answer?.max_sources }}</b></div>
        </div>
      </div>
    </section>
    <JsonDetails :value="registry" />
  </div>
</template>
