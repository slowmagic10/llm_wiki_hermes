# LLM Wiki + Hermes 软件设计文档

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | LLM Wiki + Hermes 软件设计文档 |
| 版本 | v0.4 |
| 日期 | 2026-07-14 |
| 阶段 | 基础能力已部署，多领域能力持续演进 |
| 目标用户 | 企业内部知识库用户与管理员 |
| 主要知识源 | Obsidian Markdown |
| 最终对话入口 | Hermes Agent |
## 2. 背景

系统用于构建企业内部正式知识问答底座。产品与售前知识是第一个落地领域，但核心能力按多领域设计，可扩展到运维、HR、法务和研发等稳定知识场景。

所有正式知识回答必须可追溯到 Obsidian Vault 中经人工确认的 Markdown。模型部署由现有 LiteLLM 统一提供；本系统负责知识维护、增量索引、混合检索、rerank、可回答性门控、固定领域入口和管理控制台。

当前实现以 Hermes 独立领域 hook 作为用户侧入口，以固定领域 REST API 作为正式问答主链路；MCP Bridge 保留给内部 agent 或其他工具集成，不是当前 `/wiki` 的必需路径。
## 3. 设计目标

第一版完成后应满足：

1. Hermes 作为最终对话入口。
2. Obsidian Vault 作为唯一稳定知识源。
3. Hermes 不直接写入或修改 Obsidian Markdown。
4. 知识更新只通过人工修改 Markdown 文件完成。
5. RAG 服务每天自动从 Obsidian Vault 同步索引。
6. RAG 服务解析 Obsidian 的 frontmatter、tags、双链、标题层级和文件路径。
7. 检索使用 Postgres 元数据 + Milvus 向量检索 + FTS，pgvector 可作为早期或轻量部署的备选。
8. 检索结果通过 0.6B reranker 重排并进行可回答性门控。
9. Hermes 对知识类问题必须基于 RAG 来源回答。
10. 无可靠来源时不回答问题本身，只在系统侧记录知识缺口。
11. 第一版默认输出内部答案，不生成客户可直接发送话术。
12. 所有组件优先支持 Docker 部署。
13. 使用 `ar9av/obsidian-wiki` 作为 Obsidian Wiki 离线维护工具集。
14. 提供 Admin Web 用于健康检查、同步管理、文档浏览、模型配置、RAG 测试和知识图谱可视化。

## 4. 非目标

第一版不做以下内容：

1. 不使用 Dify 作为对话入口。
2. 不使用 RAGFlow 作为主 RAG 系统。
3. 不做独立大型图数据库系统。
4. 不做自动关系抽取；知识图谱只展示 Markdown 路径、frontmatter、双链和索引元数据中的显式关系。
5. 不做历史版本管理。
6. 不做复杂多用户权限。
7. 不让 Hermes 自动写入 Obsidian。
8. 不让 Hermes 使用 web/browser/terminal/file write/长期 memory 回答该业务场景。
9. 不把 `obsidian-wiki` 放入实时问答链路。
10. 不让 `obsidian-wiki` 自动改写正式知识；第一版只输出维护建议，由人工修改 Markdown。

## 5. 总体架构

正式用户问答链路：

```text
QQBot / CLI / 未来企业微信
        ↓
Hermes 独立领域 hook
        ↓
POST /rag/domains/{domain}/answer
        ↓
领域注册表固定 domain + profile
        ↓
Postgres 元数据与 FTS + Milvus 向量召回
        ↓
0.6B reranker + 可回答性门控
        ↓
来源约束答案
```

管理链路：

```text
Admin Web
  ├─ 健康检查 / 模型配置 / 领域管理
  ├─ Git Pull + RAG 同步
  ├─ 文档浏览 / PDF 与 Markdown 草稿标准化
  ├─ RAG 测试 / 知识缺口 / 审计
  └─ obsidian-wiki 状态与离线维护入口
```

可选 agent 集成链路：

```text
Hermes 或其他 Agent
        ↓ MCP
MCP Bridge :18081
        ↓
RAG 服务
```

离线知识维护链路：

```text
本地 Obsidian 人工编辑
        ↓ Git push
服务器 Vault 部署副本
        ↓ 每日 sync-runner 或 Admin 手动同步
RAG 增量索引
```

模型调用统一经过 LiteLLM：

```text
RAG answer -> 对话模型
RAG indexing -> Embedding 模型
RAG retrieval -> 0.6B Reranker
```
## 6. 组件设计

### 6.1 Hermes Agent

职责：

1. 作为最终对话入口。
2. 承接 QQBot、CLI 和未来企业微信 adapter。
3. 为每个知识领域加载独立生成式 hook。
4. 只在用户显式使用领域触发词时调用固定领域 RAG endpoint。
5. 校验响应 `domain` 与 `entrypoint_isolated=true`。
6. 普通聊天继续走 Hermes 原有链路，不自动触发 Wiki。

不负责：

1. 不索引或修改 Obsidian。
2. 不直接访问数据库或向量库。
3. 不使用长期 memory 沉淀 Wiki 查询。
4. 不由模型自动判断或切换知识领域。
5. 不绕过 RAG 来源约束补充模型常识。
### 6.2 LiteLLM

职责：

1. 统一对接本地模型。
2. 为 Hermes 提供对话模型调用。
3. 为 RAG 服务提供 embedding 调用。
4. 在支持时为 RAG 服务提供 reranker 调用。

### 6.3 Obsidian Vault

职责：

1. 保存稳定且经人工确认的正式知识。
2. 作为系统唯一事实来源。
3. 在一个 Vault 内按 `domains/<domain>` 隔离知识。
4. 通过独立 Git 仓库维护和同步。

约束：

1. RAG API 与 MCP Bridge 只读挂载 Vault。
2. Admin 与 sync-runner 仅为 Git 同步、文档维护流程保留受控写权限。
3. Hermes、模型推理和 obsidian-wiki 不自动写入正式 Markdown。
4. 不保存聊天历史、运行日志、知识缺口或数据库文件。
5. 正式文档位于 `domains/<domain>/10_Knowledge`。
6. 草稿和归档分别使用 `00_Templates` 与 `90_Archive`。

详细维护流程参见 `docs/obsidian-vault-maintenance-guide.md`。
### 6.4 Obsidian RAG 服务与 MCP Bridge

实现：

```text
Python + FastAPI + MCP Bridge
```

职责：

1. 解析 Markdown、frontmatter、标题层级、tags 和显式双链。
2. 按文件 hash 执行增量索引并处理删除。
3. 生成 chunks 并通过 LiteLLM 调用 embedding 模型。
4. 将 documents、chunks metadata、FTS、状态、缺口和审计写入 Postgres。
5. 将向量写入 Milvus；pgvector 保留为兼容或轻量 fallback。
6. 执行 FTS + Milvus 混合召回。
7. 调用 0.6B reranker。
8. 根据领域 profile 进行阈值和答案结构选择。
9. 执行可回答性门控。
10. 生成只基于正式来源的最终答案。
11. 暴露通用 REST、固定领域 REST、管理同步 API 和 MCP 工具。
12. 无可靠来源时只记录系统侧知识缺口。

不负责：

1. 不处理 Hermes 会话和平台连接。
2. 不写回 Obsidian Markdown。
3. 不自动判断用户应进入哪个领域。
### 6.5 Postgres + pgvector + FTS

职责：

1. 存储文件索引状态。
2. 存储文档元数据。
3. 存储 chunks。
4. 存储 embedding。
5. 提供 pgvector 向量检索。
6. 提供 Postgres FTS 全文检索。
7. 存储质量报告。
8. 存储知识缺口。
9. 存储审计日志。

### 6.6 obsidian-wiki Skills

使用项目：

```text
ar9av/obsidian-wiki
```

定位：

```text
Obsidian Wiki 离线维护工具集
```

职责：

1. 对 Obsidian Vault 做只读结构检查。
2. 检查断链、孤立页面、重复主题和标签混乱。
3. 生成 cross-link 建议。
4. 生成 tag taxonomy 建议。
5. 辅助导入稳定资料并生成 Markdown 草稿建议。
6. 辅助检查 Wiki 是否符合 LLM Wiki 风格。
7. 为人工维护 Markdown 提供建议。

使用边界：

1. 第一版不进入 Hermes 实时问答链路。
2. 第一版不自动修改正式 Obsidian Markdown。
3. 第一版不作为 RAG 检索源。
4. 第一版不替代 Obsidian RAG MCP Server。
5. 第一版输出建议后，由用户人工确认并修改 Markdown。

推荐接入方式：

```text
维护用 Hermes profile: wiki-maintainer
  - 可启用 obsidian-wiki skills
  - 用于维护建议、lint、cross-link、tag taxonomy
  - 不面向业务最终问答

问答用 Hermes profile: llm-wiki
  - 只启用 Obsidian RAG MCP
  - 不启用 obsidian-wiki 写入类能力
```

## 7. Obsidian Markdown 规范

### 7.1 基础 frontmatter

建议每个正式知识页包含：

```yaml
---
title: SSO 支持情况
product: 产品A
tags: [sso, security, deployment]
status: active
applies_to: [cloud, private_deploy]
plans: [enterprise]
audience: sales_internal
customer_safe: false
rag: true
---
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `title` | 页面标题 |
| `product` | 所属产品 |
| `tags` | 主题标签 |
| `status` | 页面状态，第一版主要使用 `active` |
| `applies_to` | 适用部署形态 |
| `plans` | 适用套餐 |
| `audience` | 目标受众 |
| `customer_safe` | 是否可用于第二版客户话术 |
| `rag` | 是否进入 RAG，`false` 表示排除 |

### 7.2 索引规则

默认索引：

```text
10_Knowledge/**
```

默认不索引：

```text
90_Archive/**
Templates/**
Assets/**
```

单页排除：

```yaml
---
rag: false
---
```

索引条件：

```text
在允许目录中
且不是模板/附件
且 frontmatter.rag != false
且 status != archived
```

### 7.3 产品事实与 FAQ 规则

产品事实只维护在 `Products` 下。

业务 FAQ 和场景页不复制大段事实，只通过 Obsidian 双链引用事实页：

```markdown
## 事实依据

- [[Products/产品A/部署形态]]
- [[Products/产品A/SSO支持情况]]
```

这样可以避免重复维护和事实冲突。

## 8. 数据模型

### 8.1 indexed_files

用于记录文件同步状态。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `path` | text | Vault 内相对路径 |
| `content_hash` | text | 文件内容 hash |
| `mtime` | timestamptz | 文件修改时间 |
| `indexed_at` | timestamptz | 最近索引时间 |
| `status` | text | `indexed` / `skipped` / `error` |
| `error` | text | 错误信息 |

### 8.2 documents

用于记录 Markdown 页面元数据。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | uuid | 文档 ID |
| `path` | text | 文件路径 |
| `title` | text | 标题 |
| `frontmatter` | jsonb | frontmatter 原始结构 |
| `tags` | text[] | 标签 |
| `outlinks` | text[] | 页面双链 |
| `status` | text | 状态 |
| `product` | text | 产品 |
| `applies_to` | text[] | 适用部署形态 |
| `plans` | text[] | 适用套餐 |
| `customer_safe` | boolean | 是否客户可用 |

### 8.3 chunks

用于检索和引用。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | uuid | chunk ID |
| `document_id` | uuid | 所属文档 |
| `path` | text | 文件路径 |
| `heading_path` | text[] | 标题层级 |
| `text` | text | chunk 文本 |
| `token_count` | integer | token 数 |
| `embedding` | vector | pgvector 向量 |
| `fts` | tsvector | 全文检索字段 |
| `metadata` | jsonb | 额外元数据 |

### 8.4 quality_reports

用于保存每日只读质量检查报告。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | uuid | 报告 ID |
| `created_at` | timestamptz | 创建时间 |
| `summary` | text | 摘要 |
| `issues` | jsonb | 问题列表 |

### 8.5 knowledge_gaps

用于保存无来源问题产生的知识缺口。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | uuid | 缺口 ID |
| `query` | text | 用户问题 |
| `suggested_title` | text | 建议页面标题 |
| `suggested_path` | text | 建议路径 |
| `frequency` | integer | 出现次数 |
| `status` | text | `open` / `ignored` / `resolved` |
| `first_seen_at` | timestamptz | 首次出现 |
| `last_seen_at` | timestamptz | 最近出现 |

### 8.6 audit_logs

用于记录检索与回答依据。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | uuid | 日志 ID |
| `query` | text | 用户问题 |
| `answerable` | boolean | 是否可回答 |
| `confidence` | numeric | 置信度 |
| `citations` | jsonb | 引用来源 |
| `created_at` | timestamptz | 创建时间 |

## 9. 同步流程

当前由 Docker 服务 `llm-wiki-sync-runner` 每 86400 秒执行一次：

```text
git pull --ff-only
  ↓
POST http://rag-api:18080/admin/sync/run
  ↓
扫描启用领域的 Vault 子目录
  ↓
计算文件 hash
  ↓
识别新增、修改、删除和跳过文件
  ↓
解析 Markdown 与 frontmatter
  ↓
调用 LiteLLM embedding
  ↓
更新 Postgres 元数据与 FTS
  ↓
更新 Milvus 向量
  ↓
保存同步状态和日志
```

管理员也可以在 Admin Web“同步管理”执行“Git Pull + 重新索引”。

同步边界：

1. 只有 Git 仓库中的 Markdown 是正式输入。
2. obsidian-wiki 只提供维护建议，不直接进入索引。
3. 单个文件失败记录错误，下一轮继续重试。
4. 删除或移出正式目录的文件会删除对应 documents、chunks 和向量。
5. 同步状态保存在 `logs/llm-wiki-sync-status.json`。
6. 详细维护流程参见 `docs/obsidian-vault-maintenance-guide.md`。
## 10. 质量检查

每日同步前执行只读检查，不自动修改文件。

检查项：

1. frontmatter 是否可解析。
2. 是否缺少 `title`。
3. 是否缺少 `tags`。
4. 是否存在断开的双链。
5. 是否存在重复标题。
6. 是否存在空页面或过短页面。
7. 是否存在 `status: archived` 但仍位于正式目录的页面。
8. 是否存在正式目录页面设置了 `rag: false`。

处理规则：

1. 严重错误：跳过该文件并记录错误。
2. 轻微问题：继续索引，但写入质量报告。
3. 质量报告只保存系统侧，不写回 Obsidian。

## 11. 检索流程

```text
用户问题
  ↓
Postgres FTS 召回 top 30
  ↓
pgvector 召回 top 30
  ↓
合并去重
  ↓
规则预排
  ↓
FAQ/场景页双链扩展
  ↓
0.6B reranker 重排
  ↓
可回答性门控
  ↓
返回 top 5-8 chunks + citations
```

规则预排参考：

```text
vector_score * 0.45
+ fts_score * 0.35
+ title_match * 0.10
+ tag_match * 0.05
+ path_match * 0.05
```

FAQ/场景页扩展规则：

1. 如果 top 结果命中 `Business/FAQ` 或 `Business/Scenarios`。
2. 读取该页面 chunk 的 `outlinks`。
3. 补充召回双链指向的 `Products` 页面。
4. 原始召回结果和扩展结果一起进入 reranker。
5. 最终引用优先使用 `Products` 事实页。

## 12. 可回答性门控

RAG 服务根据 reranker 分数判断是否可回答。

初始策略：

```text
如果 top1 rerank_score < 阈值：
  answerable = false

如果 citations 为空：
  answerable = false

如果 top chunks 主题分散且无法支撑同一结论：
  answerable = false

否则：
  answerable = true
```

阈值需要后续通过测试集校准。第一版可以先使用经验阈值，再根据业务问题测试集调整。

无来源时：

1. 不回答问题本身。
2. 记录 `knowledge_gaps`。
3. 返回 `answerable=false` 给 Hermes。

## 13. MCP 工具设计

### 13.1 obsidian_rag_search

用途：内部业务产品知识检索。

输入：

```json
{
  "query": "客户问产品A是否支持SSO",
  "user_id": "nick",
  "product": "产品A",
  "tags": ["sso"]
}
```

输出：

```json
{
  "answerable": true,
  "confidence": 0.82,
  "reason": "found_reliable_sources",
  "citations": [
    {
      "path": "10_Knowledge/Products/产品A/SSO支持情况.md",
      "heading": "支持范围",
      "score": 0.91
    }
  ],
  "chunks": [
    {
      "text": "产品A企业版支持SSO，适用于云版和私有化部署。",
      "path": "10_Knowledge/Products/产品A/SSO支持情况.md",
      "heading_path": ["SSO 支持情况", "支持范围"],
      "tags": ["sso", "security", "deployment"],
      "score": 0.91
    }
  ]
}
```

### 13.2 obsidian_wiki_health_latest

用途：查询最近一次 Wiki 质量检查结果。

第一版可选实现。

### 13.3 obsidian_rag_gap_latest

用途：查询系统侧知识缺口摘要。

第一版可选实现。

## 14. Hermes 领域入口设计

### 14.1 当前主链路

当前 `/wiki` 不依赖模型工具选择，使用生成式 hook 直接调用：

```text
POST /rag/domains/default/answer
```

Hook 只发送 `query`，API 从注册表固定解析 domain 和 profile。请求体不能覆盖它们。

### 14.2 入口边界

1. 每个领域有唯一入口、aliases 和 hook 名。
2. 普通聊天不触发 Wiki。
3. 不做模型自动领域路由。
4. 不跨领域回退。
5. Hook 校验响应领域和隔离标记。
6. Hook 不写 Vault，不写长期 memory。
7. MCP 只作为可选 agent 集成，不是当前 QQBot 主链路。

### 14.3 生成与应用

`bin/sync_hermes_domain_hooks.py` 从 `config/domains.yml` 生成 hooks。Admin Web 可校验、保存领域配置并应用入口；hook 变化后由管理员显式重启 Hermes。

详细步骤参见 `docs/hermes-integration-guide.md`。

### 14.4 回答格式

最终答案栏目、来源数量、检索候选数和阈值由领域 profile 决定。当前 product profile 输出：

```text
结论
适用场景
注意事项
可替代方案
来源
```

没有可靠正式来源时拒绝回答，不提供模型通用建议入口。
## 15. Docker 部署设计

当前项目根 Compose 管理：

| 服务 | 容器 | 作用 |
| --- | --- | --- |
| RAG API | `llm-wiki-rag-api` | REST、索引、检索与答案 |
| MCP Bridge | `llm-wiki-mcp-bridge` | 可选 MCP 接入 |
| Admin Web | `llm-wiki-admin-web` | 管理控制台 |
| Sync Runner | `llm-wiki-sync-runner` | 每日 Git Pull + 增量索引 |
| Milvus | `llm-wiki-milvus` | 主向量检索 |
| etcd | `llm-wiki-milvus-etcd` | Milvus 元数据 |
| MinIO | `llm-wiki-milvus-minio` | Milvus 对象存储 |

Postgres 使用 `postgress/docker-compose.yml` 独立运行。LiteLLM 和 Hermes 为外部已有服务。

当前端口：

```text
Admin Web: 0.0.0.0:18090
RAG REST:  0.0.0.0:18080
MCP Bridge: 127.0.0.1:18081
Milvus:     127.0.0.1:19530
Postgres:   0.0.0.0:25432
LiteLLM:    127.0.0.1:14000
```

部署原则：

1. 开发代码保留在宿主项目目录，镜像通过 Docker build 复制代码。
2. Vault、config、logs 和必要运行配置通过 bind mount 提供。
3. RAG 与 MCP 对 Vault 只读。
4. Admin 不挂载 Docker socket。
5. Admin 只能写领域配置和受管 Hermes hooks；重启 Hermes 由管理员确认执行。
6. Postgres 与 Milvus 数据卷必须持久化。
7. 完整启动与恢复步骤参见 `operations-restart-runbook.md`。
## 16. Admin Web 与管理 API

Admin Web 当前地址：

```text
http://192.168.121.20:18090
```

当前页面：

1. 仪表盘与健康检查。
2. 模型配置。
3. 领域管理。
4. 同步管理。
5. 知识地图。
6. 文档浏览。
7. 文档入库与 PDF 文本提取。
8. Schema 模板。
9. RAG 测试。
10. 知识缺口与审计日志。
11. obsidian-wiki 状态。

关键 API：

```text
GET  /health
GET  /api/health-detail
GET  /api/domains
POST /api/domains/validate
PUT  /api/domains/{domain_id}
POST /api/domain-hooks/apply
POST /api/full-sync
POST /api/rag-test
POST /api/rewrite-document
POST /api/extract-pdf
GET  /api/wiki-health
```

管理边界：

1. 领域保存采用原子替换，并生成 `config/domains.yml.bak`。
2. Profiles 当前只读。
3. Hook 应用不自动重启 Hermes。
4. 当前为单管理员模式；扩大网络范围前应增加认证。
## 17. 测试与评测

第一版预留评测机制，测试集由用户后续提供。

建议文件：

```text
eval_cases.yaml
scripts/run_eval.py
```

测试集格式：

```yaml
- question: "产品A支持SSO吗？"
  expected_answerable: true
  expected_sources:
    - "10_Knowledge/Products/产品A/SSO支持情况.md"

- question: "产品A和竞品X有什么区别？"
  expected_answerable: false
```

评测指标：

1. `answerable` 判断准确率。
2. 来源命中率。
3. 平均 rerank score。
4. 无来源问题误答率。
5. 引用为空率。

## 18. 安全与边界

安全原则：

1. 正式知识只来自人工维护的 Obsidian Markdown。
2. RAG API 与 MCP Bridge 对 Vault 只读。
3. Hermes hook 不启用文件写入、终端、web 或长期 memory。
4. 固定领域 API 禁止请求体覆盖 domain/profile。
5. 不做模型自动领域路由。
6. 所有正式答案必须有来源；无来源拒答。
7. Admin 不挂载 Docker socket。
8. LiteLLM API key 不写入文档、hook 或截图。
9. 领域配置写入前校验路径重叠、入口冲突和 hook 冲突。
10. 当前 Admin 为单管理员模式，复杂 RBAC 尚未实现。

第一版暂不做：

1. 企业微信发送前硬门控。
2. 复杂 ACL 和部门权限映射。
3. 自动清理知识缺口和审计记录。
4. 客户话术生成入口。

数据模型保留未来扩展：

```yaml
visibility: internal
owner: nick
allowed_groups:
  - internal
```
## 19. 实施状态与剩余工作

以下阶段记录第一版建设过程。基础服务、同步、Milvus 检索、reranker、固定领域 Hermes hook、Admin Web 和 Docker Compose 已经部署；正式回归测试集与企业微信接入仍未完成。

### 阶段 1：基础服务

完成标准：

1. Postgres + pgvector 可启动。
2. Obsidian RAG MCP Server 可启动。
3. Vault 只读挂载成功。
4. `/health` 返回正常。

### 阶段 1.5：obsidian-wiki 离线维护工具接入

完成标准：

1. 安装并配置 `ar9av/obsidian-wiki`。
2. 能识别目标 Obsidian Vault。
3. Hermes 维护 profile 能调用相关 wiki skills。
4. 能输出 Wiki lint / cross-link / tag taxonomy 建议。
5. 不自动修改正式 Markdown，或所有写入能力默认关闭。

### 阶段 2：Markdown 解析与同步

完成标准：

1. 能扫描正式知识目录。
2. 能解析 frontmatter、tags、双链、标题层级。
3. 能生成 chunks。
4. 能写入 documents、chunks、indexed_files。
5. 能处理删除和跳过规则。

### 阶段 3：Embedding 与检索

完成标准：

1. 能通过 LiteLLM 生成 embedding。
2. pgvector 检索可用。
3. FTS 检索可用。
4. 混合召回可用。

### 阶段 4：Reranker 与门控

完成标准：

1. 能调用 0.6B reranker。
2. 能返回 rerank 分数。
3. 能根据阈值输出 `answerable`。
4. 无来源时写入 `knowledge_gaps`。

### 阶段 5：MCP 接入 Hermes

完成标准：

1. MCP server 暴露 `obsidian_rag_search`。
2. Hermes `llm-wiki` profile 能发现该工具。
3. Hermes 能调用该工具。
4. Hermes 有来源才回答，无来源不回答。

### 阶段 6：Smoke Test

完成标准：

1. 使用 5-10 个手工问题测试。
2. 正确问题能返回引用。
3. Wiki 未覆盖问题不回答。
4. FAQ/场景页能扩展到产品事实页。

## 20. 当前验收标准

当前基础版本验收条件：

1. Postgres、Milvus、RAG、MCP、Admin 和 sync-runner 容器可恢复启动。
2. Admin 健康检查全部通过。
3. Vault Git 更新后可以自动或手动增量索引。
4. 新增、修改和删除 Markdown 能正确更新 Postgres 与 Milvus。
5. 领域路径和 frontmatter domain 一致。
6. 固定领域 API 禁止 domain/profile 覆盖。
7. Hermes 领域 hook 只响应显式触发词。
8. 普通聊天不触发 Wiki。
9. 有来源的问题返回答案和 citations。
10. 无来源的问题拒答并记录系统侧知识缺口。
11. Admin 可校验和原子保存领域配置。
12. obsidian-wiki 不进入实时问答链路，不自动写正式知识。
13. 软件设计、恢复、知识维护和 Hermes 接入文档与运行实现一致。
## 21. 后续演进

后续按优先级考虑：

1. 建立正式 RAG 回归测试集和自动评测。
2. 企业微信 adapter 与真实用户入口。
3. “生成客户话术”独立按钮和 `customer_safe` 过滤。
4. Admin basic/token 认证。
5. 多领域权限和部门映射。
6. 按领域拆分 Milvus collection 或数据库 schema。
7. 发送前硬门控。
8. 更完整的 VectorStore adapter。
9. 更强 reranker 或领域专用 profile。
10. 知识缺口审核流。
11. obsidian-wiki 维护建议的人工审批工作流。
12. 知识图谱可视化的关系治理和降噪。
## 22. 多领域普适性设计边界

当前系统第一版仍然以内部业务产品知识库为落地场景，但架构目标不是只服务业务场景。后续可以扩展到 HR 制度库、运维手册库、法务知识库、研发知识库等正式知识库场景。

当前已完成 Vault domain 子目录迁移、Milvus 接入、领域注册表、检索与答案 profile 化以及多领域入口隔离。数据库、Milvus collection 和 RAG 实例目前仍可共享，但查询强制按注册表中的 `vault_subpath` 隔离；每个启用领域通过独立 Hermes hook 调用固定领域 API，调用方不能在请求体中切换领域。独立 collection 和独立 RAG 实例留到数据规模或权限边界需要时再启用。

### 22.1 设计定位

系统采用“通用核心 + 领域 profile”的方向。

通用核心包括：

1. Markdown/Vault 解析。
2. frontmatter 读取。
3. chunk 生成。
4. embedding 生成。
5. hybrid search。
6. rerank。
7. 来源引用。
8. 可回答性门控。
9. gaps 记录。
10. sync 和 Admin 基础能力。

领域 profile 包括：

1. 领域字段加权规则。
2. 领域答案格式。
3. 领域 frontmatter 扩展字段。
4. 领域 Hermes hook。
5. 领域 RAG 实例配置。

业务场景是第一个 profile，而不是唯一可支持场景。

### 22.2 仓库边界

知识内容和应用代码分开管理：

```text
知识库仓库：Obsidian Vault 仓库
应用仓库：RAG 服务、Admin Web、Docker Compose、Hermes hook、脚本、设计文档
```

当前远端目录可以继续保持：

```text
/root/llm_wiki_hermes
  services/
  docker-compose.yml
  bin/
  docs/
  vault/        # 独立 Git 仓库，存放 Obsidian Markdown
```

其中 `vault/` 是知识库仓库，应用层文件属于应用仓库。同步器只对 `vault/` 执行 `git pull`。

### 22.3 Vault 多领域目录规划

当前 `default` 领域已迁移到 domain 子目录：

```text
vault/
  domains/
    default/
      00_Templates/
      10_Knowledge/
      90_Archive/
```

管理侧已经在 `config/domains.yml` 中记录：

```yaml
vault_layout:
  mode: domain_subpath
  target_root: domains
  migration: completed

domains:
  default:
    vault_subpath: domains/default
    target_vault_subpath: domains/default
    isolation_mode: domain_subpath
```

Admin Web 的“领域注册表”页面会展示每个 domain 的当前 `vault_subpath`、目标 `target_vault_subpath`、Markdown 文件数和已索引文件数。`wiki_health` 也会按启用领域的 `vault_subpath/10_Knowledge` 扫描。

未来如果引入第二个领域，Vault 建议演进为：

```text
vault/
  domains/
    default/
      00_Templates/
      10_Knowledge/
      90_Archive/
    ops/
      00_Templates/
      10_Knowledge/
      90_Archive/
    hr/
      00_Templates/
      10_Knowledge/
      90_Archive/
```

原则：

1. 一个 Obsidian Vault 仓库内按 `domains/<domain>` 隔离。
2. 每个领域 RAG 实例只索引自己的子目录。
3. 不做全量索引后再靠过滤隔离。
4. 未来若某个领域需要独立权限或独立负责人，再拆成独立 Vault 仓库。
5. 迁移现有 `default` 领域时必须人工移动 Markdown、更新内部 wikilink、重新嵌入索引，并确认 `/api/health-detail` 和 `/api/domains` 正常。

### 22.4 domain 与 profile

`domain` 和 `profile` 分开定义：

```text
domain  = 数据所属业务空间
profile = 处理规则、答案格式、检索加权策略
```

文档 frontmatter 只要求声明 `domain`：

```yaml
rag: true
domain: default
title: QSFP-100G-DR/FR
type: product_faq
status: active
owner: nick
tags: [internal, product, optical]
updated: 2026-07-01
sources: []
```

`profile` 由领域注册表决定，不要求每篇文档重复声明。

当前 `domains/default/**` 下的正式知识文档和模板已统一补充：

```yaml
domain: default
```

Admin Web `wiki_health` 会检查 `domain` 是否缺失，并检查它是否与领域注册表中的路径归属一致。

当前已落地的第一版领域注册表位于：

```text
/root/llm_wiki_hermes/config/domains.yml
```

当前配置示例：

```yaml
version: 1
default_domain: default

vault_layout:
  mode: domain_subpath
  target_root: domains
  migration: completed

domains:
  default:
    display_name: 默认知识库
    profile: product
    vault_subpath: domains/default
    target_vault_subpath: domains/default
    isolation_mode: domain_subpath
    rag_base_url: http://rag-api:18080
    sync_status_file: /root/llm_wiki_hermes/logs/llm-wiki-sync-status.json
    vector_backend: milvus
    vector_collection: llm_wiki_chunks_v2
    entrypoint: /wiki
    entrypoint_aliases: [/llmwiki, "wiki:", "wiki：", "llmwiki:", "llmwiki："]
    entrypoint_platforms: [qqbot]
    hermes_hook: llm_wiki_router
    hermes_rag_base_url: http://127.0.0.1:18080
    enabled: true

  ops:
    display_name: 运维知识库
    profile: ops
    vault_subpath: domains/ops
    rag_base_url: http://127.0.0.1:18180
    enabled: false
```

`domains.yml` 已同时作为 Admin 领域注册表和 RAG profile 配置来源。HTTP `/rag/search`、`/rag/answer` 与 MCP `search_llm_wiki` 均接受可选的 `domain`、`profile` 参数；未传入时使用 `default_domain` 及该领域注册的 profile。检索会按 `vault_subpath` 限制 FTS、pgvector/Milvus 回表结果，并读取 profile 的候选数、rerank 数和可回答阈值。答案生成会读取 profile 的栏目顺序、领域指令、最大来源数和输出 token 上限。Admin Web 已提供只读接口 `/api/domains`、领域/profile 展示和 RAG 测试选择器，并在 `/api/health-detail` 中检查 `domain_registry`。

### 22.5 frontmatter 策略

采用“核心字段统一 + profile 扩展字段”。

核心字段：

```yaml
rag: true
domain: default
title: 文档标题
type: 文档类型
status: active
owner: nick
tags: []
summary: 简短摘要
updated: 2026-07-01
sources: []
visibility: internal
```

业务 profile 扩展字段示例：

```yaml
sku: []
aliases: []
product_line: optical
compatible_with: []
alternatives: []
customer_safe: false
limitations: []
applies_to: []
```

未来其他 profile 可以定义自己的扩展字段。例如：

```yaml
# ops profile
service: nginx
environment: production
error_code: 502
rollback: []
```

```yaml
# hr profile
policy_id: annual_leave
department: all
effective_date: 2026-01-01
employee_scope: full_time
```

Admin health check 未来应检查：

1. `domains/<domain>/**` 路径与 frontmatter `domain` 一致。
2. 核心字段完整。
3. profile 扩展字段符合该 profile schema。

### 22.6 数据库与向量库演进

当前第一版使用 Postgres + pgvector。长期设计是：

```text
Postgres = 系统事实库
Milvus/Qdrant/其他向量库 = 可替换向量检索后端
```

Postgres 保留：

1. documents。
2. chunks metadata。
3. indexed_files。
4. gaps。
5. audit logs。
6. sync status。
7. profile/domain 配置。
8. 权限与用户配置。

向量库保留：

1. chunk_id。
2. embedding vector。
3. 必要 metadata scalar fields。

未来如果升级 Milvus，推荐：

```text
Milvus instance:
  collection wiki_chunks
  collection ops_chunks
  collection hr_chunks
```

每个领域一套 collection，不必每个领域一套 Milvus 实例。不同领域仍可使用独立 Postgres database 或独立 schema。

当前不实现完整 VectorStore adapter，只要求新增向量相关逻辑时保持边界，不把 pgvector SQL 扩散到 Admin、Hermes hook 或同步脚本里。

### 22.7 多领域服务隔离

当前先采用“独立用户入口 + 固定领域 API + `vault_subpath` 强制过滤”，共享 RAG 实例、数据库和 collection；达到权限或容量边界后，再升级为“共享代码镜像，不同实例配置”：

```text
shared image:
  default instance:
    VAULT_SUBPATH=domains/default
    DATABASE_URL=postgresql://.../sales_rag
    WIKI_PROFILE=default
    VECTOR_COLLECTION=wiki_chunks

  ops instance:
    VAULT_SUBPATH=domains/ops
    DATABASE_URL=postgresql://.../ops_rag
    WIKI_PROFILE=ops
    VECTOR_COLLECTION=ops_chunks
```

原则：

1. 当前每个领域使用独立 Hermes hook 和唯一触发词。
2. 用户 hook 只调用 `/rag/domains/{domain}/answer`，请求体不能覆盖 `domain/profile`。
3. 检索结果必须属于该领域 `vault_subpath`，不跨领域回退。
4. 独立数据库/schema、vector collection 和 RAG 端口属于后续物理隔离选项。
5. 不同领域 gaps 在领域内记录，统一 Admin 聚合展示。

### 22.8 Hermes hook 策略

用户侧入口按领域隔离，不做自动跨领域路由。`bin/sync_hermes_domain_hooks.py` 根据 `config/domains.yml` 为每个启用领域生成独立 hook。

示例：

```text
llm_wiki_router -> default RAG
ops_wiki_router   -> ops RAG
hr_wiki_router    -> hr RAG
```

触发方式示例：

```text
/wiki      # 当前默认 default，保持兼容
/saleswiki # 显式 default
/opswiki   # 未来 ops
/hrwiki    # 未来 hr
```

Admin Web 的“领域管理”页面支持新增、编辑、启用或停用领域，保存前会检查领域 ID、profile、Vault 路径重叠、入口冲突和 hook 名冲突。保存采用原子替换，并在 `config/domains.yml.bak` 保留上一次配置。

网页中的“应用入口配置”会生成并校验 hooks。若页面返回 `restart_required=true`，管理员再在服务器执行 `docker restart hermes`；Admin 不挂载 Docker socket，不直接控制宿主容器。

CLI 回退方式：

```bash
cd /root/llm_wiki_hermes
python3 bin/sync_hermes_domain_hooks.py
python3 bin/sync_hermes_domain_hooks.py --check
docker restart hermes
```

生成器会拒绝重复触发词、重复 hook 名和不安全标识。生成的 hook 只发送 `query`，并校验响应中的 `domain` 和 `entrypoint_isolated=true`。

原则：

1. 不同领域 hook 独立调用自己的 RAG endpoint。
2. 不同领域 hook 不共享知识问答上下文。
3. Wiki 查询不写入 Hermes 长期 memory。
4. 第一版每次查询尽量自包含。
5. 不做模型自动判断领域，避免错路由。

### 22.9 Admin 策略

用户不进入 Admin。用户只通过 Hermes、企业微信、hook 或按钮查询知识。

管理侧采用统一 Admin Portal 的方向：

```text
Admin Portal:
  用户管理
  领域注册表
  各领域 health
  各领域 sync status
  各领域 gaps
  各领域 schema health
```

当前已落地统一领域管理页面和 API：

1. `POST /api/domains/validate`：只校验候选配置。
2. `PUT /api/domains/{domain_id}`：校验通过后原子保存。
3. `POST /api/domain-hooks/apply`：生成、清理停用入口并再次校验 hooks。
4. Profiles 当前只读，避免在同一表单中混合领域边界与复杂检索参数。

当前阶段只有一个管理员，不实现复杂 RBAC。后续对 Admin 开放更广网络访问前，应增加 basic/token 认证。第一版管理侧可以采用单管理员模式：

```text
ADMIN_AUTH_MODE=basic 或 token
ADMIN_USER=nick
```

未来接企业微信后，再考虑用户组、角色和部门映射。

### 22.10 答案格式与来源约束

所有正式知识库入口统一严格来源约束：

```text
没有可靠正式来源 = 不回答
```

不提供“模型通用建议”入口，避免用户混淆正式知识和模型常识。

接口响应结构保持通用：

```json
{
  "domain": "default",
  "profile": "product",
  "retrieval_profile": {
    "vector_top_k": 30,
    "fts_top_k": 30,
    "pre_rerank_top_k": 20,
    "rerank_top_k": 8,
    "answerable_threshold": 0.5
  },
  "answerable": true,
  "confidence": 0.8,
  "reason": "found_reliable_sources",
  "citations": [],
  "final_answer": "..."
}
```

最终展示格式由 profile 决定。

业务 profile 当前格式：

```text
结论
适用场景
注意事项
可替代方案
来源
```

未来示例：

```text
ops profile:
判断
处理步骤
回滚方案
风险点
来源
```

```text
hr profile:
结论
适用对象
办理方式
注意事项
来源
```

### 22.11 当前阶段边界

当前已落地：

1. Vault 按 `domains/<domain>` 隔离并完成 `default` 迁移。
2. Milvus 作为当前向量后端。
3. Admin 可校验并原子保存领域配置、应用独立入口，同时只读展示检索/答案 profiles。
4. RAG HTTP、Admin 测试和 Hermes MCP 工具支持 `domain/profile`。
5. 检索强制按领域 `vault_subpath` 过滤，答案格式与阈值由 profile 驱动。
6. 固定领域 API 禁止请求体切换领域，脚本按注册表生成并校验独立 Hermes hooks。

当前仍不做：

1. 不拆当前 PostgreSQL 数据库。
2. 不为每个领域强制建立独立 Milvus collection 或独立 RAG 实例。
3. 不在保存注册表后自动重启 Hermes；管理员显式生成、校验并重启。
4. 不实现复杂 RBAC。
5. 不实现完整 VectorStore adapter。
6. 不做模型通用建议入口。

## 23. 文档标准化入库助手

### 23.1 定位

文档标准化入库助手用于把粗糙 Markdown、产品说明或售前资料整理成符合 Wiki schema 的草稿。

它属于管理侧维护功能，不属于正式问答链路：

```text
原始 Markdown / 产品说明
        ↓
Admin Web 文档入库
        ↓
确定性预清洗
        ↓
LiteLLM 单次重写
        ↓
标准 Markdown 草稿 + 缺口报告
        ↓
人工确认
```

### 23.2 第一版边界

第一版只生成预览，不写入 Vault：

1. 不调用 Hermes。
2. 不依赖 skill。
3. 不自动写入正式 Wiki。
4. 不覆盖已有 Markdown。
5. 不触发 Git commit。
6. 不触发重新索引。
7. 不把粗糙资料直接变成 active 知识。

文档入库会在模型重写前做确定性预清洗，只移除明显不属于产品知识主体的内容：

1. PDF 页眉、页脚、页码。
2. 官网访问 CTA、营销跳转链接、URL。
3. 版权、商标、法律声明。
4. 数据表脚注、一致性测试说明、文档追踪编号。
5. 导入草稿自身的 frontmatter 和来源提示。

预清洗不负责判断产品事实真伪，不会把缺失事实补齐。被清洗内容会进入 `review_report.removed_irrelevant_content`，供管理员检查是否存在误删。

### 23.3 草稿硬规则

自动生成的 Markdown 必须默认：

```yaml
status: draft
rag: false
customer_safe: false
```

原文没有提供的技术事实不能补全，只能写：

```text
待确认：原始文档未提供明确依据。
```

转为正式知识必须人工确认后再手动调整：

```yaml
status: active
rag: true
```

### 23.4 输出结构

接口返回：

```json
{
  "rewritten_markdown": "...",
  "review_report": {
    "missing_fields": [],
    "uncertain_claims": [],
    "suggested_questions": [],
    "removed_irrelevant_content": [],
    "suggested_path": "domains/default/20_Drafts/xxx.md",
    "ready_for_active": false,
    "notes": []
  },
  "validation": {
    "ok": true,
    "missing_required_fields": [],
    "errors": [],
    "warnings": []
  }
}
```

### 23.5 后续增强

第二版可以增加保存到 `20_Drafts`，但仍需要人工确认。

只有在出现批量入库、重复判断、多轮补信息需求后，再考虑把同一套能力包装成 maintenance skill。Hermes 不应获得自动写正式 Wiki 的权限。

### 23.6 PDF 文本导入

文档入库助手支持文本型 PDF 的第一版导入：

```text
PDF 上传
        ↓
应用层抽取文本
        ↓
中间 Markdown
        ↓
文档入库助手生成 draft 草稿
```

第一版范围：

1. 只支持文本型 PDF。
2. 不做 OCR。
3. 不解析图片内文字。
4. 不保证复杂表格结构还原。
5. 不让模型直接读取 PDF 文件。
6. 抽取结果按页组织为 Markdown，供草稿重写使用。
7. 抽取后的 Markdown 会先经过预清洗，再进入标准化草稿生成。

当前后端接口：

```text
POST /api/extract-pdf
```

接口返回 `extracted_markdown`、页数、字符数和 warnings。若抽取文本过少，提示可能是扫描件，仍不进入自动正式知识链路。



## 24. 配套运维与接入文档

1. 服务启动、恢复和故障处理：`operations-restart-runbook.md`。
2. Obsidian Vault 新增、修改、删除、Git 同步和索引验证：`docs/obsidian-vault-maintenance-guide.md`。
3. Hermes 单领域与多领域 hook 接入：`docs/hermes-integration-guide.md`。
4. Frontmatter 字段规范：`docs/wiki-frontmatter-schema.md`。

### 24.1 管理前端实现

管理端采用前后端分层但保持单端口部署：

- 前端：Vue 3、TypeScript、Vite、Lucide Vue。
- 前端源码：`services/admin-web/frontend`。
- 后端：现有 FastAPI 管理 API，继续负责领域、模型、同步、文档和问答操作。
- 生产构建：Admin Dockerfile 使用 Node 22 多阶段构建，最终镜像只保留 Python 运行时与 `dist` 静态产物。
- 发布方式：FastAPI 在 `/assets` 提供前端资源，在同源 `/api/*` 提供管理 API，避免额外反向代理和跨域配置。
- 路由方式：前端使用 Hash 路由状态，刷新页面不会绕过 FastAPI 首页。

当前不引入 Node.js 业务后端。后续只有在用户、权限、任务编排等管理逻辑明显增长时，才考虑增加 NestJS BFF；RAG、解析、Embedding、Rerank 和 Milvus 链路继续由 Python 服务负责。
