<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { FileText, Link2, RefreshCw, Search, Tag } from '@lucide/vue'
import { api, errorMessage } from '../api'
import JsonDetails from '../components/JsonDetails.vue'
import MetricCard from '../components/MetricCard.vue'
import PageHeader from '../components/PageHeader.vue'

const data = ref<any>(null)
const search = ref('')
const selected = ref<any>(null)
const error = ref('')
const products = computed(() => {
  const term = search.value.toLowerCase().trim()
  return (data.value?.products || []).filter((item: any) => !term || JSON.stringify(item).toLowerCase().includes(term))
})
async function load() { try { data.value = await api.get('/api/knowledge-map') } catch (e) { error.value = errorMessage(e) } }
onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="知识地图" description="按领域、目录、文档与产品查看 Markdown 中的显式结构关系。">
      <button class="button primary" @click="load"><RefreshCw :size="16" />刷新地图</button>
    </PageHeader>
    <div v-if="error" class="notice is-error">{{ error }}</div>
    <div class="metrics-grid">
      <MetricCard label="领域" :value="data?.summary?.domains ?? data?.domains?.length ?? '-'" hint="domains" />
      <MetricCard label="目录" :value="data?.summary?.folders ?? data?.folders?.length ?? '-'" hint="folders" />
      <MetricCard label="文档" :value="data?.summary?.documents ?? data?.documents?.length ?? '-'" hint="markdown" />
      <MetricCard label="产品 / SKU" :value="data?.summary?.products ?? data?.products?.length ?? '-'" hint="products" />
      <MetricCard label="显式关系" :value="data?.summary?.edges ?? data?.edges?.length ?? '-'" hint="edges" />
    </div>
    <div class="knowledge-layout">
      <section class="panel">
        <div class="panel__head"><div><strong>产品与 SKU</strong><span>只展示显式元数据关系</span></div></div>
        <label class="search-field"><Search :size="16" /><input v-model="search" placeholder="搜索 SKU、别名或文档" /></label>
        <div class="knowledge-list">
          <button v-for="item in products" :key="item.sku || item.id" :class="{ active: selected === item }" @click="selected = item">
            <div><strong>{{ item.sku || item.label || item.id }}</strong><span>{{ item.title || item.document_title || item.path || '-' }}</span></div><Link2 :size="16" />
          </button>
          <div v-if="!products.length" class="empty-state">暂无匹配产品</div>
        </div>
      </section>
      <section class="panel detail-panel">
        <div class="panel__head"><div><strong>{{ selected?.sku || selected?.label || '选择产品查看详情' }}</strong><span>来源于 Frontmatter 和双链</span></div></div>
        <template v-if="selected">
          <div class="detail-section"><span><FileText :size="15" />文档来源</span><strong>{{ selected.path || selected.document || '-' }}</strong></div>
          <div class="detail-section"><span><Tag :size="15" />别名</span><div class="chips"><b v-for="item in selected.aliases || []" :key="item">{{ item }}</b><em v-if="!selected.aliases?.length">未记录</em></div></div>
          <div class="detail-section"><span>兼容对象</span><div class="chips"><b v-for="item in selected.compatible_with || selected.compatibility || []" :key="item">{{ item }}</b><em v-if="!(selected.compatible_with || selected.compatibility)?.length">未记录</em></div></div>
          <div class="detail-section"><span>替代方案</span><div class="chips"><b v-for="item in selected.alternatives || []" :key="item">{{ item }}</b><em v-if="!selected.alternatives?.length">未记录</em></div></div>
          <div class="detail-section"><span>限制条件</span><p>{{ Array.isArray(selected.limitations) ? selected.limitations.join('；') : selected.limitations || '未记录' }}</p></div>
        </template>
        <div v-else class="empty-state large">从左侧选择一个产品或 SKU。</div>
      </section>
      <section class="panel structure-panel">
        <div class="panel__head"><div><strong>目录结构</strong><span>{{ data?.folders?.length || 0 }} 个目录</span></div></div>
        <div class="folder-list"><div v-for="folder in data?.folders || []" :key="folder.path || folder.id"><strong>{{ folder.path || folder.label || folder.id }}</strong><span>{{ folder.document_count ?? folder.documents?.length ?? 0 }} 个文档</span></div></div>
      </section>
    </div>
    <JsonDetails :value="data" />
  </div>
</template>
