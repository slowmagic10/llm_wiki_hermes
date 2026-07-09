const $ = (id) => document.getElementById(id);
const pageInfo = {
  dashboard:['仪表盘','企业正式 Wiki 运行状态'],
  models:['模型配置','LiteLLM 可用模型与 RAG 运行模型'],
  domains:['领域注册表','多领域知识库的管理侧注册表'],
  sync:['同步管理','Git 同步和索引刷新'],
  knowledgeMap:['知识地图','Wiki 结构和显式关系可视化'],
  rag:['RAG 测试','正式 Wiki 问答链路验证'],
  docs:['文档浏览','远端 Vault Markdown 只读浏览'],
  rewrite:['文档入库','Markdown 标准化草稿和缺口报告'],
  gaps:['知识缺口','未命中问题和补充线索'],
  audit:['审计日志','最近问答请求和来源记录'],
  health:['健康检查','系统依赖与知识质量检查'],
  schema:['Schema 模板','frontmatter 规范'],
  obsidian:['obsidian-wiki','维护工具状态']
};
function showTab(id){
  document.querySelectorAll('section').forEach(s=>s.classList.remove('active'));
  $(id).classList.add('active');
  document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active', b.dataset.tab===id));
  $('pageTitle').textContent=pageInfo[id]?.[0]||id;
  $('pageMeta').textContent=pageInfo[id]?.[1]||'';
  if(id === 'models') loadModelConfig();
  if(id === 'domains') loadDomains();
  if(id === 'knowledgeMap') loadKnowledgeMap();
}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
function pretty(x){ return JSON.stringify(x,null,2); }
async function getJson(url, opts={}){ const r=await fetch(url, opts); const t=await r.text(); try{ const j=JSON.parse(t); if(!r.ok) throw j; return j; }catch(e){ if(!r.ok) throw new Error(t); return t; } }
function escapeHtml(s){ return String(s).replace(/[&<>"']/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function q(s){ return String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'"); }
function badge(status, text){
  const cls = status==='ok'?'ok':(status==='warning'||status==='warn'?'warn':(status==='failed'||status==='bad'?'bad':''));
  return `<span class="badge ${cls}">${escapeHtml(text ?? status ?? 'unknown')}</span>`;
}
function card(label,value,meta='',state=''){
  const cls = state==='ok'?'ok':(state==='warning'?'warn':(state==='failed'?'bad':''));
  return `<div class="card"><div class="metric-label">${escapeHtml(label)}</div><div class="metric ${cls}">${escapeHtml(value ?? '-')}</div><div class="metric-sub">${escapeHtml(meta || '')}</div></div>`;
}
function listRow(title, sub, right='', state=''){
  return `<div class="list-row"><div><div class="list-title">${escapeHtml(title)}</div><div class="list-sub">${escapeHtml(sub || '')}</div></div><div>${right ? badge(state || 'ok', right) : ''}</div></div>`;
}
function table(rows, cols){
  if(!rows.length) return '<div class="empty">暂无数据</div>';
  return '<table><thead><tr>'+cols.map(c=>`<th>${c[1]}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(c=>`<td>${escapeHtml(String(r[c[0]] ?? ''))}</td>`).join('')+'</tr>').join('')+'</tbody></table>';
}
function setQuery(text){ $('query').value = text; }
function mini(label, value, state=''){
  const cls = state==='ok'?'ok':(state==='warning'?'warn':(state==='failed'?'bad':''));
  return `<div class="mini-stat"><div class="mini-label">${escapeHtml(label)}</div><div class="mini-value ${cls}">${escapeHtml(value ?? '-')}</div></div>`;
}
function pills(values, empty='未记录'){
  const items = Array.isArray(values) ? values.filter(Boolean) : [];
  if(!items.length) return `<span class="muted">${escapeHtml(empty)}</span>`;
  return `<div class="map-pills">${items.map(value=>`<span class="pill">${escapeHtml(value)}</span>`).join('')}</div>`;
}
function citationTotal(value){
  try {
    const parsed = typeof value === 'string' ? JSON.parse(value) : value;
    return Array.isArray(parsed) ? parsed.length : 0;
  } catch(e) {
    return 0;
  }
}
function parseFrontmatter(text){
  if(!text.startsWith('---')) return { meta:null, body:text };
  const end = text.indexOf('\n---', 3);
  if(end < 0) return { meta:null, body:text };
  const raw = text.slice(3, end).trim();
  const body = text.slice(text.indexOf('\n', end + 4) + 1);
  const meta = {};
  let currentKey = null;
  for(const line of raw.split('\n')){
    if(!line.trim()) continue;
    const m = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if(m){
      currentKey = m[1];
      let value = m[2].trim();
      value = value.replace(/^['"]|['"]$/g,'');
      meta[currentKey] = value || '';
    } else if(currentKey && line.trim().startsWith('- ')){
      const value = line.trim().slice(2).replace(/^['"]|['"]$/g,'');
      if(!Array.isArray(meta[currentKey])) meta[currentKey] = meta[currentKey] ? [meta[currentKey]] : [];
      meta[currentKey].push(value);
    }
  }
  return { meta, body };
}
function renderMeta(meta){
  if(!meta) return '<div class="empty">未检测到 frontmatter</div>';
  const preferred = ['title','type','status','owner','updated','tags','sku','aliases','summary'];
  const keys = [...preferred.filter(k => k in meta), ...Object.keys(meta).filter(k => !preferred.includes(k))];
  return keys.map(k => {
    const value = Array.isArray(meta[k]) ? meta[k].join(', ') : meta[k];
    return `<div class="kv-row"><div class="kv-key">${escapeHtml(k)}</div><div class="kv-value">${escapeHtml(value || '-')}</div></div>`;
  }).join('') || '<div class="empty">frontmatter 为空</div>';
}
function updateGlobal(status){
  const text = status==='ok'?'系统正常':(status==='warning'?'存在警告':(status==='failed'?'存在异常':'未检查'));
  $('globalHealth').outerHTML = `<span class="badge ${status==='ok'?'ok':(status==='warning'?'warn':(status==='failed'?'bad':''))}" id="globalHealth">${text}</span>`;
}
function updateStateBand(summary){
  const status = summary?.overall || 'unknown';
  const text = status==='ok'?'系统链路正常':(status==='warning'?'系统存在警告':(status==='failed'?'系统存在异常':'等待健康检查'));
  const desc = status==='ok'
    ? `全部 ${summary.checks ?? '-'} 个检查项通过，最近检查时间 ${summary.checked_at || '-'}`
    : `异常 ${summary.failed ?? 0} 项，警告 ${summary.warnings ?? 0} 项`;
  $('stateBadge').outerHTML = badge(status, status).replace('<span','<span id="stateBadge"');
  $('stateTitle').textContent = text;
  $('stateDesc').textContent = desc;
}
function checkByName(data, name){
  return (data?.checks || []).find(item => item.name === name) || {};
}
function renderPipeline(data){
  const specs = [
    ['postgres','Postgres'],
    ['rag_api','RAG API'],
    ['litellm_models','LiteLLM'],
    ['vault_git','Vault Git'],
    ['sync_status','Sync']
  ];
  $('systemPipeline').innerHTML = specs.map(([key,label]) => {
    const item = checkByName(data, key);
    const status = item.status || 'unknown';
    return `<div class="node"><div class="node-name">${escapeHtml(label)}</div><div>${badge(status, status)}</div><div class="node-msg">${escapeHtml(item.message || '等待检查')}</div></div>`;
  }).join('');
}
function renderDashboardHealth(data){
  const summary = data.summary || {};
  updateGlobal(summary.overall || 'unknown');
  updateStateBand(summary);
  renderPipeline(data);
  const wiki = checkByName(data, 'wiki_quality');
  const db = checkByName(data, 'postgres');
  const sync = checkByName(data, 'sync_status');
  const counts = db.details || {};
  const wikiSummary = wiki.details?.summary || {};
  $('qualityBadge').outerHTML = badge(wiki.status || 'unknown', wiki.status || 'unknown').replace('<span','<span id="qualityBadge"');
  $('knowledgeList').innerHTML = [
    listRow('文档规模', `documents=${counts.documents ?? '-'}, chunks=${counts.chunks ?? '-'}`, 'indexed', 'ok'),
    listRow('Wiki 质量', `errors=${wikiSummary.errors ?? '-'}, warnings=${wikiSummary.warnings ?? '-'}`, wiki.status || 'unknown', wiki.status),
    listRow('Vault Git', checkByName(data,'vault_git').message || '-', checkByName(data,'vault_git').status || 'unknown', checkByName(data,'vault_git').status),
    listRow('最近同步', sync.message || '-', sync.status || 'unknown', sync.status)
  ].join('');
}
async function loadStatus(){
  const data=await getJson('/api/status');
  $('statusRaw').textContent=pretty(data);
  const counts=data.counts||{};
  const sync=data.sync_status||{};
  const ragOk=!!data.rag_health?.ok;
  $('statusCards').innerHTML=[
    card('文档', counts.documents, 'documents'),
    card('Chunks', counts.chunks, 'indexed content'),
    card('索引文件', counts.indexed_files, 'indexed_files'),
    card('Open 缺口', counts.knowledge_gaps_open, 'knowledge_gaps'),
    card('审计记录', counts.audit_logs, 'audit_logs'),
    card('RAG API', ragOk?'OK':'FAIL', data.rag_health?.db?'db connected':'', ragOk?'ok':'failed'),
    card('同步', sync.status || '-', sync.ended_at || sync.started_at || '', sync.status==='success'?'ok':(sync.status==='failed'?'failed':'warning'))
  ].join('');
  $('syncRaw').textContent=pretty(sync);
  $('syncBadge').outerHTML=badge(sync.status==='success'?'ok':(sync.status==='failed'?'failed':'warning'), sync.status || 'unknown').replace('<span','<span id="syncBadge"');
  $('workList').innerHTML = [
    listRow('Open 知识缺口', `${counts.knowledge_gaps_open ?? 0} 条待补充`, counts.knowledge_gaps_open > 0 ? '处理' : '清零', counts.knowledge_gaps_open > 0 ? 'warning' : 'ok'),
    listRow('最近索引', data.latest_index?.path || '暂无索引记录', data.latest_index?.status || '-', data.latest_index?.status === 'indexed' ? 'ok' : '检查', data.latest_index?.status === 'indexed' ? 'ok' : 'warning'),
    listRow('Git 工作区', (data.git_status?.stdout || '').trim() ? '存在未提交改动' : '工作区干净', (data.git_status?.stdout || '').trim() ? '检查' : 'ok', (data.git_status?.stdout || '').trim() ? 'warning' : 'ok')
  ].join('');
}
function renderOptions(selectId, models, selected, fallback){
  const select = $(selectId);
  const values = [...new Set([selected, fallback, ...models].filter(Boolean))];
  select.innerHTML = values.map(model => `<option value="${escapeHtml(model)}" ${model===selected?'selected':''}>${escapeHtml(model)}</option>`).join('');
}
function classifyModels(models, kind){
  const items = models || [];
  if(kind === 'reranker') return items.filter(model => /rerank|reranker/i.test(model));
  if(kind === 'embedding') return items.filter(model => /embed|embedding/i.test(model));
  return items.filter(model => !/rerank|reranker|embed|embedding/i.test(model));
}
async function loadModelConfig(){
  const data = await getJson('/api/model-config');
  $('modelConfigRaw').textContent = pretty(data);
  const models = data.available_models || [];
  const effective = data.effective || {};
  const defaults = data.defaults || {};
  renderOptions('chatModel', classifyModels(models, 'chat'), effective.chat_model, defaults.chat_model);
  renderOptions('rerankerModel', classifyModels(models, 'reranker'), effective.reranker_model, defaults.reranker_model);
  renderOptions('embeddingModel', classifyModels(models, 'embedding'), effective.embedding_model, defaults.embedding_model);
  $('modelCards').innerHTML = [
    card('LiteLLM 模型', models.length, 'available models', models.length ? 'ok' : 'warning'),
    card('回答模型', effective.chat_model || '-', 'chat_model'),
    card('Rerank 模型', effective.reranker_model || '-', 'reranker_model'),
    card('Embedding', effective.embedding_model || '-', '只展示，切换需重建索引')
  ].join('');
  $('modelSaveState').textContent = data.settings_path || '';
}
async function saveModelConfig(){
  $('modelSaveState').textContent = '保存中...';
  try {
    const data = await getJson('/api/model-config', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        chat_model:$('chatModel').value,
        reranker_model:$('rerankerModel').value
      })
    });
    $('modelSaveState').textContent = '已保存';
    $('modelConfigRaw').textContent = pretty(data);
    await loadModelConfig();
  } catch(e) {
    $('modelSaveState').textContent = '保存失败';
    $('modelConfigRaw').textContent = String(e.stack || e);
  }
}
async function loadDomains(){
  const data = await getJson('/api/domains');
  $('domainsRaw').textContent = pretty(data);
  const summary = data.summary || {};
  $('domainRegistryPath').textContent = data.registry_path || '';
  $('domainCards').innerHTML = [
    card('领域数', summary.domains ?? 0, 'domains'),
    card('启用领域', summary.enabled ?? 0, 'enabled', summary.enabled > 0 ? 'ok' : 'warning'),
    card('已隔离', summary.isolated ?? 0, 'domain_subpath'),
    card('根目录兼容', summary.legacy_root ?? 0, 'legacy_root'),
    card('默认领域', data.default_domain || '-', 'default_domain'),
    card('配置来源', data.source || '-', data.registry_path || '')
  ].join('');
  const domains = data.domains || {};
  const entries = Object.entries(domains);
  $('domainList').innerHTML = entries.length ? entries.map(([id, cfg]) => {
    const enabled = !!cfg.enabled;
    const collection = cfg.vector_collection || cfg.milvus_collection || '-';
    const vault = cfg.vault_status || {};
    const target = cfg.target_vault_status || {};
    const isolation = cfg.isolation_mode || '-';
    const targetText = cfg.target_vault_subpath ? `${cfg.target_vault_subpath} (${target.exists ? 'exists' : 'not ready'})` : '-';
    return `<div class="task-card">
      <div class="task-top"><div><div class="task-title">${escapeHtml(cfg.display_name || id)}</div><div class="list-sub">${escapeHtml(id)} · profile=${escapeHtml(cfg.profile || '-')} · isolation=${escapeHtml(isolation)}</div></div>${badge(enabled ? 'ok' : 'warning', enabled ? 'enabled' : 'disabled')}</div>
      <div class="task-meta">
        <span>vault=${escapeHtml(cfg.vault_subpath || '-')} (${vault.exists ? 'exists' : 'missing'})</span>
        <span>target=${escapeHtml(targetText)}</span>
        <span>md=${escapeHtml(vault.markdown_files ?? '-')}</span>
        <span>indexed=${escapeHtml(vault.indexed_files ?? '-')}</span>
        <span>rag=${escapeHtml(cfg.rag_base_url || '-')}</span>
        <span>sync=${escapeHtml(cfg.sync_status_file || '-')}</span>
        <span>vector=${escapeHtml(cfg.vector_backend || '-')} / ${escapeHtml(collection)}</span>
        <span>entry=${escapeHtml(cfg.entrypoint || '-')}</span>
      </div>
      ${cfg.description ? `<div class="list-sub" style="margin-top:8px">${escapeHtml(cfg.description)}</div>` : ''}
    </div>`;
  }).join('') : '<div class="empty">未定义领域</div>';
  const issues = data.issues || [];
  $('domainIssueCount').outerHTML = badge(issues.length ? (summary.errors ? 'failed' : 'warning') : 'ok', `${issues.length} 项`).replace('<span','<span id="domainIssueCount"');
  $('domainIssues').innerHTML = issues.length ? `<div class="task-list">${issues.map(item=>`<div class="task-card"><div class="task-top"><div class="task-title">${escapeHtml(item.domain || '-')} · ${escapeHtml(item.code || '-')}</div>${badge(item.severity === 'error' ? 'failed' : 'warning', item.severity || '-')}</div><div class="task-meta"><span>${escapeHtml(item.message || '')}</span></div></div>`).join('')}</div>` : '<div class="empty">领域注册表校验通过</div>';
}
let knowledgeMapState = null;
let knowledgeGraphMode = 'product';
let knowledgeGraphFocusSku = null;
let rewriteDraft = '';
function shortLabel(value, limit=28){
  const text = String(value || '-');
  return text.length > limit ? text.slice(0, limit - 1) + '…' : text;
}
function nodeSvg({x,y,w,h,label,sub,type='',focus=false,dim=false,onclick=''}) {
  const classes = ['graph-node', type, focus ? 'focus' : '', dim ? 'dim' : '', onclick ? 'clickable' : ''].filter(Boolean).join(' ');
  const action = onclick ? ` onclick="${onclick}"` : '';
  return `<g class="${classes}"${action}>
    <rect x="${x}" y="${y}" width="${w}" height="${h}"></rect>
    <text x="${x + 12}" y="${y + 21}">${escapeHtml(shortLabel(label, Math.floor(w / 7)))}</text>
    <text class="sub" x="${x + 12}" y="${y + 39}">${escapeHtml(shortLabel(sub || '', Math.floor(w / 8)))}</text>
  </g>`;
}
function edgeSvg(x1,y1,x2,y2,strong=false){
  const mid = Math.round((x1 + x2) / 2);
  return `<path class="graph-edge ${strong ? 'strong' : ''}" d="M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}"></path>`;
}
function docByPath(data){
  const map = {};
  for(const doc of data.documents || []) map[doc.path] = doc;
  return map;
}
function graphNodeMap(data){
  const map = {};
  for(const node of data.nodes || []) map[node.id] = node;
  return map;
}
function graphNodes(data, type){
  return (data.nodes || []).filter(node => node.type === type);
}
function graphEdges(data, type){
  return (data.edges || []).filter(edge => edge.type === type);
}
function setKnowledgeGraphMode(mode){
  knowledgeGraphMode = mode;
  document.querySelectorAll('.graph-mode').forEach(btn=>btn.classList.remove('active'));
  if(mode === 'product') $('graphModeProduct').classList.add('active');
  if(mode === 'structure') $('graphModeStructure').classList.add('active');
  renderKnowledgeGraph();
}
function renderKnowledgeGraph(){
  const data = knowledgeMapState || {};
  const svg = $('knowledgeGraphSvg');
  if(!svg) return;
  if(knowledgeGraphMode === 'structure'){
    renderStructureGraph(data, svg);
  } else {
    renderProductGraph(data, svg);
  }
}
function renderProductGraph(data, svg){
  if(!(data.nodes || []).length || !(data.edges || []).length){
    return renderLegacyProductGraph(data, svg);
  }
  const nodeMap = graphNodeMap(data);
  const mentionEdges = graphEdges(data, 'MENTIONS_SKU');
  const productIds = [...new Set(mentionEdges.map(edge => edge.target))].filter(id => nodeMap[id]);
  const docIds = [...new Set(mentionEdges.map(edge => edge.source))].filter(id => nodeMap[id]);
  const productH = 48;
  const docH = 48;
  const gap = 14;
  const height = Math.max(520, 86 + Math.max(productIds.length * (productH + gap), docIds.length * (docH + gap)));
  const productX = 58;
  const docX = 760;
  const productY = 62;
  const docY = 62;
  const productPos = {};
  const docPos = {};
  let edges = '';
  let nodes = '';
  productIds.forEach((id, index) => {
    productPos[id] = {x:productX, y:productY + index * (productH + gap), w:270, h:productH};
  });
  docIds.forEach((id, index) => {
    docPos[id] = {x:docX, y:docY + index * (docH + gap), w:285, h:docH};
  });
  mentionEdges.forEach(edge => {
    const product = productPos[edge.target];
    const doc = docPos[edge.source];
    if(!product || !doc) return;
    const productNode = nodeMap[edge.target];
    const strong = knowledgeGraphFocusSku && productNode?.label === knowledgeGraphFocusSku;
    edges += edgeSvg(product.x + product.w, product.y + product.h/2, doc.x, doc.y + doc.h/2, strong);
  });
  productIds.forEach((id) => {
    const product = nodeMap[id];
    const pos = productPos[id];
    const focused = knowledgeGraphFocusSku === product.label;
    const dim = knowledgeGraphFocusSku && !focused;
    const relatedDocs = mentionEdges.filter(edge => edge.target === id).length;
    const legacyIndex = (data.products || []).findIndex(item => item.sku === product.label);
    nodes += nodeSvg({
      ...pos,
      label: product.label,
      sub: `docs ${relatedDocs} · ${product.metadata?.domain || '-'}`,
      type:'product',
      focus: focused,
      dim,
      onclick: legacyIndex >= 0 ? `renderProductFocus(${legacyIndex})` : ''
    });
  });
  docIds.forEach((id) => {
    const doc = nodeMap[id];
    const pos = docPos[id];
    const related = mentionEdges.some(edge => edge.source === id && nodeMap[edge.target]?.label === knowledgeGraphFocusSku);
    const dim = knowledgeGraphFocusSku && !related;
    nodes += nodeSvg({
      ...pos,
      label: doc.label,
      sub: `${doc.metadata?.chunks || 0} chunks · ${doc.metadata?.status || '-'}`,
      type:'document',
      focus: related,
      dim
    });
  });
  svg.setAttribute('viewBox', `0 0 1100 ${height}`);
  svg.innerHTML = `<text x="58" y="32" fill="#647084" font-size="12" font-weight="700">产品 / SKU</text>
    <text x="760" y="32" fill="#647084" font-size="12" font-weight="700">Markdown 文档</text>
    ${edges}${nodes}`;
}
function renderLegacyProductGraph(data, svg){
  const products = data.products || [];
  const docs = data.documents || [];
  const productH = 48;
  const docH = 48;
  const gap = 14;
  const height = Math.max(520, 86 + Math.max(products.length * (productH + gap), docs.length * (docH + gap)));
  const productX = 58;
  const docX = 760;
  const productY = 62;
  const docY = 62;
  const productPos = {};
  const docPos = {};
  let edges = '';
  let nodes = '';
  products.forEach((product, index) => {
    productPos[product.sku] = {x:productX, y:productY + index * (productH + gap), w:270, h:productH};
  });
  docs.forEach((doc, index) => {
    docPos[doc.path] = {x:docX, y:docY + index * (docH + gap), w:285, h:docH};
  });
  products.forEach((product, index) => {
    const pos = productPos[product.sku];
    const focused = knowledgeGraphFocusSku === product.sku;
    const dim = knowledgeGraphFocusSku && !focused;
    for(const ref of product.documents || []){
      const target = docPos[ref.path];
      if(!target) continue;
      edges += edgeSvg(pos.x + pos.w, pos.y + pos.h/2, target.x, target.y + target.h/2, focused);
    }
    nodes += nodeSvg({
      ...pos,
      label: product.sku,
      sub: `aliases ${product.aliases?.length || 0} · docs ${product.documents?.length || 0}`,
      type:'product',
      focus: focused,
      dim,
      onclick:`renderProductFocus(${index})`
    });
  });
  docs.forEach((doc) => {
    const pos = docPos[doc.path];
    const related = products.some(product => product.sku === knowledgeGraphFocusSku && (product.documents || []).some(ref => ref.path === doc.path));
    const dim = knowledgeGraphFocusSku && !related;
    nodes += nodeSvg({
      ...pos,
      label: doc.title || doc.path,
      sub: `${doc.chunks || 0} chunks · ${doc.status || '-'}`,
      type:'document',
      focus: related,
      dim
    });
  });
  svg.setAttribute('viewBox', `0 0 1100 ${height}`);
  svg.innerHTML = `<text x="58" y="32" fill="#647084" font-size="12" font-weight="700">产品 / SKU</text>
    <text x="760" y="32" fill="#647084" font-size="12" font-weight="700">Markdown 文档</text>
    ${edges}${nodes}`;
}
function renderStructureGraph(data, svg){
  if(!(data.nodes || []).length || !(data.edges || []).length){
    return renderLegacyStructureGraph(data, svg);
  }
  const nodeMap = graphNodeMap(data);
  const domains = graphNodes(data, 'Domain');
  const folders = graphNodes(data, 'Folder');
  const docs = graphNodes(data, 'Document');
  const domainH = 48;
  const folderH = 48;
  const docH = 48;
  const gap = 14;
  const height = Math.max(520, 86 + Math.max(domains.length * (domainH + gap), folders.length * (folderH + gap), docs.length * (docH + gap)));
  const domainPos = {};
  const folderPos = {};
  const docPos = {};
  let edges = '';
  let nodes = '';
  domains.forEach((domain, index) => {
    domainPos[domain.id] = {x:58, y:74 + index * (domainH + gap), w:190, h:domainH};
  });
  folders.forEach((folder, index) => {
    folderPos[folder.id] = {x:360, y:74 + index * (folderH + gap), w:250, h:folderH};
  });
  docs.forEach((doc, index) => {
    docPos[doc.id] = {x:760, y:56 + index * (docH + gap), w:285, h:docH};
  });
  graphEdges(data, 'FOLDER_IN_DOMAIN').forEach(edge => {
    const folder = folderPos[edge.source];
    const domain = domainPos[edge.target];
    if(domain && folder) edges += edgeSvg(domain.x + domain.w, domain.y + domain.h/2, folder.x, folder.y + folder.h/2, true);
  });
  graphEdges(data, 'IN_FOLDER').forEach(edge => {
    const doc = docPos[edge.source];
    const folder = folderPos[edge.target];
    if(folder && doc) edges += edgeSvg(folder.x + folder.w, folder.y + folder.h/2, doc.x, doc.y + doc.h/2, false);
  });
  domains.forEach(domain => {
    const pos = domainPos[domain.id];
    nodes += nodeSvg({...pos, label:domain.label, sub:`docs ${domain.metadata?.documents || 0}`, type:'domain'});
  });
  folders.forEach(folder => {
    const pos = folderPos[folder.id];
    nodes += nodeSvg({...pos, label:folder.label, sub:`docs ${folder.metadata?.documents || 0} · ${folder.metadata?.domain || '-'}`, type:'folder'});
  });
  docs.forEach(doc => {
    const pos = docPos[doc.id];
    nodes += nodeSvg({...pos, label:doc.label, sub:`${doc.metadata?.chunks || 0} chunks · ${doc.metadata?.status || '-'}`, type:'document'});
  });
  svg.setAttribute('viewBox', `0 0 1100 ${height}`);
  svg.innerHTML = `<text x="58" y="32" fill="#647084" font-size="12" font-weight="700">领域</text>
    <text x="360" y="32" fill="#647084" font-size="12" font-weight="700">目录</text>
    <text x="760" y="32" fill="#647084" font-size="12" font-weight="700">Markdown 文档</text>
    ${edges}${nodes}`;
}
function renderLegacyStructureGraph(data, svg){
  const domains = data.domains || [];
  const folders = data.folders || [];
  const docs = data.documents || [];
  const domainH = 48;
  const folderH = 48;
  const docH = 48;
  const gap = 14;
  const height = Math.max(520, 86 + Math.max(domains.length * (domainH + gap), folders.length * (folderH + gap), docs.length * (docH + gap)));
  const domainPos = {};
  const folderPos = {};
  const docPos = {};
  let edges = '';
  let nodes = '';
  domains.forEach((domain, index) => {
    domainPos[domain.id] = {x:58, y:74 + index * (domainH + gap), w:190, h:domainH};
  });
  folders.forEach((folder, index) => {
    folderPos[folder.path] = {x:360, y:74 + index * (folderH + gap), w:250, h:folderH};
  });
  docs.forEach((doc, index) => {
    docPos[doc.path] = {x:760, y:56 + index * (docH + gap), w:285, h:docH};
  });
  folders.forEach(folder => {
    const source = domainPos[folder.domain];
    const target = folderPos[folder.path];
    if(source && target) edges += edgeSvg(source.x + source.w, source.y + source.h/2, target.x, target.y + target.h/2, true);
  });
  docs.forEach(doc => {
    const source = folderPos[doc.folder];
    const target = docPos[doc.path];
    if(source && target) edges += edgeSvg(source.x + source.w, source.y + source.h/2, target.x, target.y + target.h/2, false);
  });
  domains.forEach(domain => {
    const pos = domainPos[domain.id];
    nodes += nodeSvg({...pos, label:domain.id, sub:`docs ${domain.documents || 0} · products ${domain.products?.length || 0}`, type:'domain'});
  });
  folders.forEach(folder => {
    const pos = folderPos[folder.path];
    nodes += nodeSvg({...pos, label:folder.path, sub:`docs ${folder.documents || 0} · chunks ${folder.chunks || 0}`, type:'folder'});
  });
  docs.forEach(doc => {
    const pos = docPos[doc.path];
    nodes += nodeSvg({...pos, label:doc.title || doc.path, sub:`${doc.chunks || 0} chunks · ${doc.status || '-'}`, type:'document'});
  });
  svg.setAttribute('viewBox', `0 0 1100 ${height}`);
  svg.innerHTML = `<text x="58" y="32" fill="#647084" font-size="12" font-weight="700">领域</text>
    <text x="360" y="32" fill="#647084" font-size="12" font-weight="700">目录</text>
    <text x="760" y="32" fill="#647084" font-size="12" font-weight="700">Markdown 文档</text>
    ${edges}${nodes}`;
}
function renderProductFocus(index){
  const data = knowledgeMapState || {};
  const product = (data.products || [])[index];
  document.querySelectorAll('#productMapList .map-card').forEach((el, i)=>el.classList.toggle('active', i === index));
  if(!product){
    knowledgeGraphFocusSku = null;
    renderKnowledgeGraph();
    $('mapFocusTitle').textContent = '选择一个产品查看详情';
    $('mapFocusBadge').outerHTML = badge('warning','等待').replace('<span','<span id="mapFocusBadge"');
    $('mapFocusDetail').innerHTML = '<div class="empty">左侧选择 SKU 后显示 aliases、兼容对象、替代方案、限制条件和文档来源。</div>';
    return;
  }
  knowledgeGraphFocusSku = product.sku;
  renderKnowledgeGraph();
  $('mapFocusTitle').textContent = product.sku;
  $('mapFocusBadge').outerHTML = badge('ok', product.domain || 'domain').replace('<span','<span id="mapFocusBadge"');
  const docs = product.documents || [];
  $('mapFocusDetail').innerHTML = [
    `<div class="map-field"><div class="map-field-label">对应文档</div><div class="map-list">${docs.map(doc=>`<div class="citation"><div class="citation-title">${escapeHtml(doc.title || doc.path)}</div><div class="citation-sub">${escapeHtml(doc.path)} · chunks=${escapeHtml(doc.chunks ?? '-')}</div></div>`).join('') || '<span class="muted">未记录</span>'}</div></div>`,
    `<div class="map-field"><div class="map-field-label">Aliases</div>${pills(product.aliases)}</div>`,
    `<div class="map-field"><div class="map-field-label">兼容对象</div>${pills(product.compatible_with)}</div>`,
    `<div class="map-field"><div class="map-field-label">替代方案</div>${pills(product.alternatives)}</div>`,
    `<div class="map-field"><div class="map-field-label">限制条件</div>${pills(product.limitations)}</div>`,
    `<div class="map-field"><div class="map-field-label">适用对象 / 套餐</div>${pills([...(product.applies_to || []), ...(product.plans || [])])}</div>`,
    `<div class="map-field"><div class="map-field-label">标签</div>${pills(product.tags)}</div>`
  ].join('');
}
async function loadKnowledgeMap(){
  const data = await getJson('/api/knowledge-map');
  knowledgeMapState = data;
  $('knowledgeMapRaw').textContent = pretty(data);
  const s = data.summary || {};
  $('knowledgeMapCards').innerHTML = [
    card('文档', s.documents ?? 0, 'documents'),
    card('Chunks', s.chunks ?? 0, 'indexed chunks'),
    card('图谱节点', s.nodes ?? 0, 'nodes'),
    card('图谱关系', s.edges ?? 0, 'edges'),
    card('产品 / SKU', s.products ?? 0, 'frontmatter sku'),
    card('领域', s.domains ?? 0, 'domains'),
    card('目录', s.folders ?? 0, 'folders'),
    card('标签', s.tags ?? 0, 'tags')
  ].join('');
  const policy = data.policy || {};
  $('knowledgeMapPolicy').innerHTML = [
    `<div><strong>定位</strong><br>${escapeHtml(policy.purpose || '')}</div>`,
    `<div><strong>强关系来源</strong><br>${escapeHtml((policy.strong_sources || []).join(' / '))}</div>`,
    `<div><strong>向量使用</strong><br>${escapeHtml(policy.vector_usage || '')}</div>`,
    `<div><strong>LLM 使用</strong><br>${escapeHtml(policy.llm_usage || '')}</div>`
  ].join('');
  const products = data.products || [];
  $('productCount').textContent = `${products.length} 个`;
  $('productMapList').innerHTML = products.length ? products.map((item,index)=>`
    <div class="map-card" onclick="renderProductFocus(${index})">
      <div class="map-title">${escapeHtml(item.sku)}</div>
      <div class="map-sub">
        <span>${escapeHtml(item.domain || '-')}</span>
        <span>docs=${escapeHtml((item.documents || []).length)}</span>
        <span>aliases=${escapeHtml((item.aliases || []).length)}</span>
        <span>limits=${escapeHtml((item.limitations || []).length)}</span>
      </div>
    </div>
  `).join('') : '<div class="empty">暂无产品/SKU frontmatter</div>';
  const folders = data.folders || [];
  $('folderCount').textContent = `${folders.length} 个`;
  $('folderMapList').innerHTML = folders.length ? folders.map(item=>`
    <div class="map-card">
      <div class="map-title">${escapeHtml(item.path)}</div>
      <div class="map-sub"><span>${escapeHtml(item.domain || '-')}</span><span>documents=${escapeHtml(item.documents ?? 0)}</span><span>chunks=${escapeHtml(item.chunks ?? 0)}</span></div>
    </div>
  `).join('') : '<div class="empty">暂无目录数据</div>';
  renderProductFocus(products.length ? 0 : -1);
}
async function runAction(url){
  $('actionLog').textContent='running...';
  try{ const data=await getJson(url,{method:'POST'}); $('actionLog').textContent=pretty(data); loadStatus(); }
  catch(e){ $('actionLog').textContent=String(e.stack||e); }
}
async function testRag(){
  const query=$('query').value.trim();
  if(!query){ $('ragResult').textContent='请输入问题'; return; }
  $('ragAnswer').textContent='查询中...';
  $('ragAnswer').className='answer-box muted';
  $('ragResult').textContent='querying...';
  $('ragCitations').innerHTML='';
  $('citationCount').textContent='0';
  $('ragMeta').innerHTML='';
  try{
    const data=await getJson('/api/rag-test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query})});
    $('ragResult').textContent=pretty(data);
    const answerable = !!data.answerable;
    const status = answerable ? 'ok' : 'failed';
    $('ragBadge').outerHTML = badge(status, answerable ? '可回答' : '不可回答').replace('<span','<span id="ragBadge"');
    $('ragMeta').innerHTML = [
      mini('answerable', answerable ? 'true' : 'false', status),
      mini('confidence', data.confidence ?? '-', answerable ? 'ok' : 'failed'),
      mini('reason', data.reason || '-', answerable ? 'ok' : 'failed')
    ].join('');
    $('ragAnswer').className = 'answer-box';
    $('ragAnswer').textContent = data.final_answer || '无 final_answer';
    const citations = data.citations || [];
    $('citationCount').textContent = `${citations.length} 条`;
    $('ragCitations').innerHTML = citations.length ? citations.map((c,i)=>`<div class="citation"><div class="citation-title">[${i+1}] ${escapeHtml(c.path || '-')}</div><div class="citation-sub">${escapeHtml(c.heading || '')} · score=${escapeHtml(c.score ?? '-')}</div></div>`).join('') : '<div class="empty">无可靠来源</div>';
  }
  catch(e){
    $('ragBadge').outerHTML = badge('failed','失败').replace('<span','<span id="ragBadge"');
    $('ragAnswer').className='answer-box bad';
    $('ragAnswer').textContent=String(e.stack||e);
    $('ragResult').textContent=String(e.stack||e);
  }
}
function renderRewriteReport(data){
  const report = data.review_report || {};
  const validation = data.validation || {};
  const missing = report.missing_fields || validation.missing_required_fields || [];
  const uncertain = report.uncertain_claims || [];
  const questions = report.suggested_questions || [];
  const removed = report.removed_irrelevant_content || [];
  const notes = report.notes || [];
  const status = validation.ok ? 'ok' : 'warning';
  $('rewriteStatus').outerHTML = badge(status, validation.ok ? '草稿校验通过' : '需要确认').replace('<span','<span id="rewriteStatus"');
  const block = (title, items, empty) => `<div class="map-field"><div class="map-field-label">${escapeHtml(title)}</div>${
    items && items.length ? `<div class="task-list">${items.map(item=>`<div class="citation"><div class="citation-title">${escapeHtml(String(item))}</div></div>`).join('')}</div>` : `<span class="muted">${escapeHtml(empty)}</span>`
  }</div>`;
  $('rewriteReport').className = '';
  $('rewriteReport').innerHTML = [
    `<div class="map-field"><div class="map-field-label">建议路径</div><div class="citation"><div class="citation-title">${escapeHtml(report.suggested_path || '未生成')}</div></div></div>`,
    `<div class="map-field"><div class="map-field-label">转正式状态</div>${badge('warning', '永远需要人工确认')}</div>`,
    block('缺失字段', missing, '未检测到必填字段缺失'),
    block('待确认事实', uncertain, '未列出不确定事实'),
    block('建议追问', questions, '未生成建议问题'),
    block('已清洗内容', removed, '未清洗明显噪声'),
    block('备注', notes, '无额外备注'),
    block('校验错误', validation.errors || [], '无'),
    block('校验警告', validation.warnings || [], '无')
  ].join('');
}
async function rewriteDocument(){
  const raw = $('rewriteInput').value.trim();
  if(!raw){
    $('rewriteOutput').textContent = '请先粘贴原始 Markdown 或产品说明。';
    return;
  }
  $('rewriteStatus').outerHTML = badge('warning','生成中').replace('<span','<span id="rewriteStatus"');
  $('rewriteOutput').textContent = '生成中...';
  $('rewriteRaw').textContent = 'requesting...';
  try{
    const data = await getJson('/api/rewrite-document', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        raw_markdown: raw,
        domain: $('rewriteDomain').value.trim() || 'default',
        profile: $('rewriteProfile').value.trim() || 'product',
        doc_type: $('rewriteType').value,
        owner: $('rewriteOwner').value.trim() || 'nick'
      })
    });
    rewriteDraft = data.rewritten_markdown || '';
    $('rewriteOutput').textContent = rewriteDraft || '未生成草稿';
    $('rewriteRaw').textContent = pretty(data);
    renderRewriteReport(data);
  } catch(e) {
    $('rewriteStatus').outerHTML = badge('failed','失败').replace('<span','<span id="rewriteStatus"');
    $('rewriteOutput').textContent = String(e.stack || e);
    $('rewriteRaw').textContent = String(e.stack || e);
  }
}
function renderPdfExtractReport(data){
  const warnings = data.warnings || [];
  $('pdfExtractReport').className = '';
  $('pdfExtractReport').innerHTML = [
    `<div class="map-field"><div class="map-field-label">文件</div><div class="citation"><div class="citation-title">${escapeHtml(data.filename || '-')}</div><div class="citation-sub">pages=${escapeHtml(data.pages ?? '-')} · extracted=${escapeHtml(data.extracted_pages ?? '-')} · chars=${escapeHtml(data.total_text_chars ?? 0)}</div></div></div>`,
    `<div class="map-field"><div class="map-field-label">是否适合重写</div>${badge(data.can_rewrite ? 'ok' : 'warning', data.can_rewrite ? '可以生成草稿' : '文本过少，建议人工检查')}</div>`,
    `<div class="map-field"><div class="map-field-label">页面字符数</div><div class="task-meta">${(data.page_summaries || []).map(item=>`<span>P${escapeHtml(item.page)}=${escapeHtml(item.chars)}</span>`).join('') || '<span>无</span>'}</div></div>`,
    `<div class="map-field"><div class="map-field-label">告警</div>${warnings.length ? warnings.map(item=>`<div class="citation"><div class="citation-title">${escapeHtml(item)}</div></div>`).join('') : '<span class="muted">无</span>'}</div>`
  ].join('');
}
async function extractPdfText(){
  const input = $('pdfInput');
  const file = input?.files?.[0];
  if(!file){
    $('pdfExtractState').textContent = '请先选择 PDF 文件';
    return;
  }
  $('pdfExtractState').textContent = '抽取中...';
  $('pdfExtractReport').className = 'empty';
  $('pdfExtractReport').textContent = '抽取中...';
  const form = new FormData();
  form.append('file', file);
  try{
    const data = await getJson('/api/extract-pdf', { method:'POST', body:form });
    $('pdfExtractState').textContent = `已抽取 ${data.total_text_chars || 0} 字符`;
    $('rewriteInput').value = data.extracted_markdown || '';
    renderPdfExtractReport(data);
  } catch(e) {
    $('pdfExtractState').textContent = '抽取失败';
    $('pdfExtractReport').className = 'empty';
    $('pdfExtractReport').textContent = String(e.stack || e);
  }
}
function clearRewriteDocument(){
  $('rewriteInput').value = '';
  if($('pdfInput')) $('pdfInput').value = '';
  rewriteDraft = '';
  $('rewriteOutput').textContent = '等待生成...';
  $('rewriteRaw').textContent = '等待生成...';
  $('rewriteReport').className = 'empty';
  $('rewriteReport').textContent = '生成草稿后显示缺失字段、待确认问题和建议路径。';
  $('pdfExtractReport').className = 'empty';
  $('pdfExtractReport').textContent = '上传文本型 PDF 后显示页数、字符数和告警。';
  $('pdfExtractState').textContent = '仅支持文本型 PDF，不做 OCR';
  $('rewriteStatus').outerHTML = badge('', '等待').replace('<span','<span id="rewriteStatus"');
}
async function copyRewriteDraft(){
  if(!rewriteDraft) return;
  try {
    await navigator.clipboard.writeText(rewriteDraft);
    $('rewriteStatus').outerHTML = badge('ok','已复制').replace('<span','<span id="rewriteStatus"');
  } catch(e) {
    $('rewriteStatus').outerHTML = badge('warning','复制失败').replace('<span','<span id="rewriteStatus"');
  }
}
function downloadRewriteDraft(){
  if(!rewriteDraft) return;
  const parsed = parseFrontmatter(rewriteDraft);
  const title = parsed.meta?.title || 'draft';
  const safeName = String(title).replace(/[\\/:*?"<>|]+/g, '-').slice(0, 80) || 'draft';
  const blob = new Blob([rewriteDraft], {type:'text/markdown;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${safeName}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
async function loadFiles(path='.'){
  const data=await getJson('/api/files?path='+encodeURIComponent(path));
  let h='';
  if(data.parent!==null) h+=`<a href="#" onclick="loadFiles('${q(data.parent)}');return false;"><span class="file-kind">UP</span><span class="file-name">..</span></a>`;
  h += data.entries.map(e=>`<a href="#" onclick="${e.type==='dir'?`loadFiles('${q(e.path)}')`:`previewFile('${q(e.path)}')`};return false;"><span class="file-kind">${e.type==='dir'?'DIR':'MD'}</span><span class="file-name">${escapeHtml(e.name)}</span></a>`).join('');
  $('files').innerHTML=h||'<div class="empty">空目录</div>';
}
async function previewFile(path){
  const data=await getJson('/api/file?path='+encodeURIComponent(path));
  const parsed = parseFrontmatter(data.content || '');
  $('docTitle').textContent=(parsed.meta && parsed.meta.title) ? parsed.meta.title : data.path.split('/').pop();
  $('docPath').textContent=data.path;
  $('docPreview').textContent=parsed.body || data.content;
  $('docMeta').innerHTML=renderMeta(parsed.meta);
  const status = parsed.meta?.status || (parsed.meta ? 'metadata' : 'missing');
  $('docStatus').outerHTML = badge(status === 'active' ? 'ok' : (status === 'missing' ? 'warning' : 'warning'), status).replace('<span','<span id="docStatus"');
}
async function loadGaps(){
  const rows=await getJson('/api/gaps');
  const open = rows.filter(r => r.status === 'open').length;
  const totalFreq = rows.reduce((sum,r)=>sum + Number(r.frequency || 0), 0);
  $('gapsSummary').innerHTML=[
    card('Open 缺口', open, 'status=open', open ? 'warning' : 'ok'),
    card('记录数', rows.length, '最近 100 条'),
    card('累计出现', totalFreq, 'frequency sum')
  ].join('');
  $('gapsTable').innerHTML=rows.length ? `<div class="task-list">${rows.map(r=>`<div class="task-card"><div class="task-top"><div class="task-title">${escapeHtml(r.query || '-')}</div>${badge(r.status==='open'?'warning':'ok', r.status || '-')}</div><div class="task-meta"><span>最近：${escapeHtml(r.last_seen_at || '-')}</span><span>次数：${escapeHtml(r.frequency ?? '-')}</span><span>建议：${escapeHtml(r.suggested_title || '-')}</span></div></div>`).join('')}</div>` : '<div class="empty">暂无知识缺口</div>';
}
async function loadAudit(){
  const rows=await getJson('/api/audit');
  const answerable = rows.filter(r => String(r.answerable) === 'true').length;
  const blocked = rows.length - answerable;
  $('auditSummary').innerHTML=[
    card('审计记录', rows.length, '最近 100 条'),
    card('可回答', answerable, 'answerable=true', 'ok'),
    card('不可回答', blocked, 'source constrained', blocked ? 'warning' : 'ok')
  ].join('');
  $('auditTable').innerHTML=rows.length ? `<div class="audit-list">${rows.map(r=>`<div class="audit-card"><div class="audit-question">${escapeHtml(r.query || '-')}</div><div class="audit-meta">${badge(String(r.answerable)==='true'?'ok':'failed', String(r.answerable)==='true'?'可回答':'不可回答')}<span>confidence=${escapeHtml(r.confidence ?? '-')}</span><span>${escapeHtml(r.created_at || '-')}</span><span>citations=${citationTotal(r.citations)}</span></div></div>`).join('')}</div>` : '<div class="empty">暂无审计记录</div>';
}
async function loadHealth(){
  const data=await getJson('/api/health-detail');
  const s=data.summary||{};
  updateGlobal(s.overall || 'unknown');
  updateStateBand(s);
  renderPipeline(data);
  renderDashboardHealth(data);
  $('healthResult').textContent=pretty(data);
  $('healthCheckedAt').textContent=s.checked_at || '';
  $('healthSummary').innerHTML=[
    card('总体', s.overall || '-', 'overall', s.overall),
    card('检查项', s.checks, 'checks'),
    card('正常', s.ok, 'ok', 'ok'),
    card('异常', s.failed, 'failed', s.failed>0?'failed':''),
    card('警告', s.warnings, 'warnings', s.warnings>0?'warning':'')
  ].join('');
  const rows=(data.checks||[]).map(item=>`<div class="health-row"><div><div class="health-name">${escapeHtml(item.name)}</div></div><div>${badge(item.status,item.status)}</div><div class="health-message" title="${escapeHtml(item.message||'')}">${escapeHtml(item.message||'')}</div></div>`).join('');
  $('healthRows').innerHTML=rows||'<div class="empty">暂无检查结果</div>';
}
async function loadSchema(){ const data=await getJson('/api/schema-template'); $('schemaTemplate').textContent=data.content || pretty(data); }
async function loadObsidianWiki(){ const data=await getJson('/api/obsidian-wiki'); $('obsidianInfo').textContent=pretty(data); }
$('now').textContent=new Date().toLocaleString();
loadStatus();
loadHealth();
loadFiles('.');
