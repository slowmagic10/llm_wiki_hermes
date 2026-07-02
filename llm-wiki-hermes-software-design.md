# LLM Wiki + Hermes 软件设计文档

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | LLM Wiki + Hermes 软件设计文档 |
| 版本 | v0.1 |
| 日期 | 2026-06-17 |
| 阶段 | 第一版设计 |
| 目标用户 | 内部业务用户 |
| 主要知识源 | Obsidian Markdown |
| 最终对话入口 | Hermes Agent |

## 2. 背景

当前目标是构建一套面向内部业务团队咨询的内部产品知识问答系统。系统需要基于稳定的产品知识回答问题，并且所有知识类回答必须可追溯到 Obsidian Wiki 中的 Markdown 来源。

用户已经具备本地模型部署能力，并已通过 LiteLLM 接入模型网关。因此本设计不展开模型部署细节，重点设计 Hermes、Obsidian Wiki、RAG 检索层和 Docker 化组件组合。

## 3. 设计目标

第一版完成后应满足：

1. Hermes 作为最终对话入口。
2. Obsidian Vault 作为唯一稳定知识源。
3. Hermes 不直接写入或修改 Obsidian Markdown。
4. 知识更新只通过人工修改 Markdown 文件完成。
5. RAG 服务每天自动从 Obsidian Vault 同步索引。
6. RAG 服务解析 Obsidian 的 frontmatter、tags、双链、标题层级和文件路径。
7. 检索使用 Postgres + pgvector + FTS。
8. 检索结果通过 0.6B reranker 重排并进行可回答性门控。
9. Hermes 对知识类问题必须基于 RAG 来源回答。
10. 无可靠来源时不回答问题本身，只在系统侧记录知识缺口。
11. 第一版默认输出内部答案，不生成客户可直接发送话术。
12. 所有组件优先支持 Docker 部署。
13. 使用 `ar9av/obsidian-wiki` 作为 Obsidian Wiki 离线维护工具集。

## 4. 非目标

第一版不做以下内容：

1. 不使用 Dify 作为对话入口。
2. 不使用 RAGFlow 作为主 RAG 系统。
3. 不引入 Qdrant、OpenSearch、Milvus。
4. 不做知识图谱。
5. 不做自动关系抽取。
6. 不做历史版本管理。
7. 不做管理 UI。
8. 不做复杂多用户权限。
9. 不让 Hermes 自动写入 Obsidian。
10. 不让 Hermes 使用 web/browser/terminal/file write/长期 memory 回答该业务场景。
11. 不把 `obsidian-wiki` 放入实时问答链路。
12. 不让 `obsidian-wiki` 自动改写正式知识；第一版只输出维护建议，由人工修改 Markdown。

## 5. 总体架构

```text
企业微信 / CLI / Web
        ↓
Hermes llm-wiki profile
        ↓ MCP
Obsidian RAG MCP Server
        ↓
Postgres + pgvector + FTS
        ↓
只读挂载 Obsidian Vault
```

离线维护链路：

```text
人工触发 / 定期检查
        ↓
obsidian-wiki skills
        ↓
Wiki lint / cross-link / tag taxonomy / ingest 建议
        ↓
系统侧维护报告或对话中展示建议
        ↓
人工修改 Obsidian Markdown
        ↓
下一次 RAG 同步
```

模型调用链路：

```text
Hermes
  ↓
LiteLLM
  ↓
本地对话模型

Obsidian RAG MCP Server
  ↓
LiteLLM
  ↓
Embedding 模型

Obsidian RAG MCP Server
  ↓
LiteLLM 或本地 reranker endpoint
  ↓
0.6B reranker
```

## 6. 组件设计

### 6.1 Hermes Agent

职责：

1. 作为最终对话入口。
2. 承接企业微信、CLI 或 Web 入口。
3. 使用独立 `llm-wiki` profile。
4. 通过 MCP 调用 Obsidian RAG MCP Server。
5. 基于 RAG 返回的 chunks 和 citations 组织最终答案。
6. 在无来源时拒绝回答知识问题。

不负责：

1. 不负责索引 Obsidian。
2. 不负责写入 Obsidian。
3. 不负责长期记忆沉淀。
4. 不负责直接访问数据库。

### 6.2 LiteLLM

职责：

1. 统一对接本地模型。
2. 为 Hermes 提供对话模型调用。
3. 为 RAG 服务提供 embedding 调用。
4. 在支持时为 RAG 服务提供 reranker 调用。

### 6.3 Obsidian Vault

职责：

1. 保存稳定产品知识。
2. 作为系统唯一事实来源。
3. 由人工维护 Markdown 文件。

约束：

1. Docker 中只读挂载。
2. 不保存 Hermes 运行日志。
3. 不保存聊天历史。
4. 不保存知识缺口报告。
5. 不保存质量检查报告。

建议目录：

```text
10_Knowledge/
  Products/
    产品A/
      功能概览.md
      集成方式.md
      部署形态.md
      常见问题.md
  Business/
    Scenarios/
    FAQ/
90_Archive/
Templates/
Assets/
```

### 6.4 Obsidian RAG MCP Server

实现建议：

```text
Python + FastAPI + FastMCP
```

职责：

1. 每日扫描 Obsidian Vault。
2. 执行只读 Wiki 质量检查。
3. 解析 Markdown、frontmatter、tags、双链和标题层级。
4. 对 Markdown 进行 chunk。
5. 调用 LiteLLM 生成 embedding。
6. 写入 Postgres + pgvector + FTS。
7. 执行混合检索。
8. 命中 FAQ/业务场景页时扩展读取双链指向的产品事实页。
9. 调用 0.6B reranker。
10. 根据 reranker 分数判断是否可回答。
11. 通过 MCP 向 Hermes 暴露工具。
12. 在无来源时记录系统侧知识缺口。

不负责：

1. 不生成最终自然语言答案。
2. 不写入 Obsidian Markdown。
3. 不承担 Hermes 的会话管理。

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

每日同步由 Obsidian RAG MCP Server 内置 scheduler 触发。

```text
每日定时任务
  ↓
扫描 Obsidian Vault
  ↓
读取 indexed_files
  ↓
计算文件 hash / mtime
  ↓
识别新增、修改、删除、排除文件
  ↓
执行只读 Wiki 质量检查
  ↓
增量解析 Markdown
  ↓
生成 chunks
  ↓
调用 LiteLLM embedding API
  ↓
写入 Postgres + pgvector + FTS
  ↓
保存同步状态和质量报告
```

如果启用 `obsidian-wiki` 离线维护任务，则它在 RAG 同步之前或人工维护时运行：

```text
obsidian-wiki skills
  ↓
生成维护建议
  ↓
人工确认并修改 Markdown
  ↓
RAG MCP Server 下一次同步
```

注意：`obsidian-wiki` 的输出不直接进入 RAG 索引，只有人工修改后的 Markdown 才进入下一次同步。

失败策略：

1. 单个文件失败不影响整体同步。
2. 失败文件记录到 `indexed_files.error`。
3. 下一轮同步继续重试。
4. 删除或移出索引目录的文件，需要删除对应 documents 和 chunks。

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

## 14. Hermes llm-wiki Profile 设计

### 14.1 Profile 目标

`llm-wiki` profile 只服务内部业务内部产品知识问答，不影响日常 Hermes 使用。

### 14.2 工具边界

启用：

```text
mcp-obsidian-rag
```

禁用：

```text
web
browser
terminal
file write
long-term memory
```

### 14.3 系统提示核心规则

```text
你是内部业务内部产品知识助手。

所有正式知识、业务咨询、FAQ 类问题必须调用 Obsidian RAG MCP。
只能基于 MCP 返回的 chunks 回答。
如果 answerable=false、citations 为空、或来源不足，不能回答问题本身。
回答必须包含来源路径和标题。
不要使用模型常识补充产品事实。
不要写入 Obsidian。
不要使用 web/browser/terminal/file write/长期 memory。
默认输出内部答案，不生成客户可直接发送话术。
```

### 14.4 回答格式

建议格式：

```text
结论：
- ...

依据：
- ...

Wiki 未覆盖：
- ...

来源：
- 10_Knowledge/Products/产品A/SSO支持情况.md > 支持范围
```

需要区分：

1. 明确支持。
2. 明确不支持。
3. Wiki 未覆盖。

第一版暂不专门维护“不支持/限制边界”页面，因此没有明确来源时应归入“Wiki 未覆盖”，不能推断为“不支持”。

## 15. Docker 部署设计

第一版服务：

```text
hermes
litellm
obsidian-rag-mcp
postgres
```

示例 Compose 结构：

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: rag
      POSTGRES_USER: rag
      POSTGRES_PASSWORD: rag
    volumes:
      - postgres_data:/var/lib/postgresql/data

  obsidian-rag-mcp:
    build: ./services/obsidian-rag-mcp
    depends_on:
      - postgres
    environment:
      VAULT_PATH: /vault
      DATABASE_URL: postgresql://rag:rag@postgres:5432/rag
      LITELLM_BASE_URL: http://litellm:4000
      EMBEDDING_MODEL: your-embedding-model
      RERANKER_URL: http://reranker:8000/rerank
    volumes:
      - /path/to/obsidian-vault:/vault:ro
    ports:
      - "8080:8080"

volumes:
  postgres_data:
```

注意：

1. Obsidian Vault 必须只读挂载。
2. Postgres 数据需要持久化。
3. Hermes 通过 MCP HTTP endpoint 连接 `obsidian-rag-mcp`。
4. LiteLLM 可复用你现有部署。

## 16. 管理 API

第一版不做管理 UI，只保留 HTTP API。

建议接口：

```text
GET /health
GET /admin/sync/latest
POST /admin/sync/run
GET /admin/quality/latest
GET /admin/gaps?status=open
```

用途：

1. 健康检查。
2. 手动触发同步。
3. 查看最近同步状态。
4. 查看质量报告。
5. 查看知识缺口。

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

1. Obsidian Vault 只读挂载。
2. Hermes 不启用写文件工具。
3. `llm-wiki` 不启用 web/browser/terminal。
4. `llm-wiki` 关闭长期 memory。
5. 知识类回答必须有 RAG 来源。
6. 无来源不回答。
7. 系统侧记录长期保存，第一版不自动清理。

第一版暂不做：

1. 企业微信发送前硬门控。
2. 复杂 ACL。
3. 多部门隔离。

但数据模型保留未来扩展空间：

```yaml
visibility: internal
owner: nick
allowed_groups: [internal]
```

## 19. 实施计划

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

## 20. 验收标准

第一版验收通过条件：

1. Docker 环境能启动 `postgres`、`obsidian-rag-mcp`、Hermes 相关服务。
2. Obsidian Vault 以只读方式挂载。
3. 手动触发同步成功。
4. 每日自动同步任务可运行。
5. Markdown 修改后，下一次同步能更新索引。
6. Hermes 能通过 MCP 查询 RAG。
7. 有来源的问题能返回答案和引用。
8. 无来源的问题不回答，并写入知识缺口。
9. Hermes 不使用 web/browser/terminal/file write/长期 memory。
10. 第一版不生成客户话术，只输出内部答案。
11. `obsidian-wiki` 可作为离线维护工具运行并输出建议。
12. `obsidian-wiki` 不参与实时问答链路，不绕过 RAG 来源约束。

## 21. 后续演进

第二版可考虑：

1. 企业微信正式接入。
2. 客户话术按钮。
3. `customer_safe: true` 内容过滤。
4. 管理 UI。
5. 正式测试集评测。
6. 权限模型。
7. 发送前硬门控。
8. Qdrant/OpenSearch 拆分。
9. 更强 reranker。
10. 知识缺口审核流。
11. 将 `obsidian-wiki` 的维护建议接入管理 UI。
12. 对 `obsidian-wiki` 写入类操作增加人工审批流。

## 22. 多领域普适性设计边界

当前系统第一版仍然以内部业务产品知识库为落地场景，但架构目标不是只服务业务场景。后续可以扩展到 HR 制度库、运维手册库、法务知识库、研发知识库等正式知识库场景。

本节只定义未来演进边界。当前阶段不迁移生产 Vault 目录、不拆数据库、不切换 Milvus、不新增多领域 Hermes hook、不改运行服务。

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
    enabled: true

  ops:
    display_name: 运维知识库
    profile: ops
    vault_subpath: domains/ops
    rag_base_url: http://127.0.0.1:18180
    enabled: false
```

第一版 `domains.yml` 只作为 Admin 领域注册表，不作为 RAG、hook、sync-runner 的全系统配置中心。当前 Admin Web 已提供只读接口 `/api/domains` 和页面“领域注册表”，并在 `/api/health-detail` 中检查 `domain_registry`。

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

未来多领域运行时采用“共享代码镜像，不同实例配置”的方式：

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

1. 不同领域独立数据库或独立 schema。
2. 不同领域独立 vector collection。
3. 不同领域独立 RAG 服务端口。
4. 不同领域独立 Hermes hook。
5. 不同领域 gaps 在领域内记录，统一 Admin 聚合展示。

### 22.8 Hermes hook 策略

用户侧入口按领域隔离，不做自动跨领域路由。

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

当前阶段只有一个管理员，不实现复杂 RBAC。第一版管理侧可以采用单管理员模式：

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

### 22.11 当前阶段明确不做

当前阶段不做：

1. 不迁移当前业务 Vault 到 `domains/default`。
2. 不拆当前数据库。
3. 不上线 Milvus。
4. 不新增多领域 RAG 实例。
5. 不新增多领域 Hermes hook。
6. 不实现统一 Admin 多领域管理。
7. 不实现复杂 RBAC。
8. 不实现完整 VectorStore adapter。
9. 不做模型通用建议入口。

当前阶段只把上述原则写入设计文档和待办，保证当前通用第一版稳定运行。
