# Hermes 接入 LLM Wiki 手册

更新时间：2026-07-14

本文档说明如何把 LLM Wiki 接入 Hermes、如何为不同知识领域创建独立入口，以及如何验证和排查接入问题。

## 1. 当前接入方式

当前用户侧正式链路使用 Hermes hook，不依赖模型自动判断是否调用知识库：

```text
QQBot 用户消息
  -> /wiki 问题
  -> llm_wiki_router
  -> POST /rag/domains/default/answer
  -> default 领域 + product profile
  -> Postgres FTS + Milvus + reranker
  -> 来源约束答案
  -> hook 校验 domain 和 entrypoint_isolated
  -> 返回用户
```

核心原则：

1. 每个领域使用独立 Hermes hook。
2. 每个 hook 绑定固定领域 REST endpoint。
3. 请求体只发送 `query`，不能覆盖 `domain` 或 `profile`。
4. 不使用模型自动选择领域。
5. 普通 Hermes 对话不自动进入 Wiki。
6. Wiki 查询不写入 Hermes 长期 memory。
7. Hermes 不写入 Obsidian Vault。

## 2. 当前默认入口

当前领域：

```text
domain: default
profile: product
hook: llm_wiki_router
endpoint: /rag/domains/default/answer
```

当前触发词：

```text
/wiki
/llmwiki
wiki:
wiki：
llmwiki:
llmwiki：
```

示例：

```text
/wiki OSFP-QDD-CU3可以用于CX7 NIC互连吗？
```

普通消息：

```text
你好
```

不会进入 Wiki hook，继续使用 Hermes 原有对话链路。

## 3. 前置条件

接入前确认：

1. RAG API 正常：`http://127.0.0.1:18080/health`。
2. Admin 正常：`http://127.0.0.1:18090/health`。
3. Hermes 容器正在运行。
4. 目标领域已经在 `config/domains.yml` 注册并启用。
5. 目标领域 Vault 子目录存在且已经索引。
6. Hermes 容器能够访问 RAG API。

检查：

```bash
curl --noproxy "*" http://127.0.0.1:18080/health
curl --noproxy "*" http://127.0.0.1:18090/api/domains

docker ps --filter name=hermes   --format "table {{.Names}}	{{.Status}}"
```

## 4. 推荐接入流程：Admin Web

打开：

```text
http://192.168.121.20:18090
领域管理
```

### 4.1 配置领域

需要填写：

| 字段 | 说明 | 示例 |
| --- | --- | --- |
| 领域 ID | 稳定的机器标识，创建后不修改 | `ops` |
| 显示名称 | 管理页面名称 | 运维知识库 |
| Profile | 检索参数和答案格式 | `product` |
| Vault 子目录 | 该领域知识范围 | `domains/ops` |
| 主入口 | 用户触发词 | `/opswiki` |
| 入口别名 | 可选的其他触发词 | `opswiki:` |
| 入口平台 | Hermes adapter 平台名 | `qqbot` |
| Hermes hook | 独立 hook 名 | `llm_wiki_ops_router` |
| Hermes RAG 地址 | Hermes 访问 RAG 的地址 | `http://127.0.0.1:18080` |
| 启用领域 | 是否生成入口并允许查询 | `true` |

保存前会检查：

1. 领域 ID 格式。
2. Profile 是否存在。
3. Vault 路径是否安全。
4. 启用领域的 Vault 路径是否重叠。
5. 主入口和别名是否冲突。
6. Hermes hook 名是否冲突。
7. 默认领域是否保持启用。

### 4.2 保存领域

点击“校验”，确认没有 error 后点击“保存领域”。

保存结果：

1. 原子更新 `config/domains.yml`。
2. 上一个版本备份到 `config/domains.yml.bak`。
3. RAG 新请求立即读取新的领域注册表。
4. 此时 Hermes hook 尚未更新。

### 4.3 应用入口配置

点击“应用入口配置”。

系统执行：

```text
检查当前 hooks
  -> 生成新增或变化的 hook
  -> 停用不再启用的生成式 hook
  -> 再次校验
```

如果页面显示无需重启，说明运行时文件没有变化。

如果页面返回 `restart_required=true`，在服务器执行：

```bash
docker restart hermes
```

Admin 不挂载 Docker socket，因此不会直接重启宿主机容器。

## 5. CLI 接入方式

页面不可用时，可以直接维护 `config/domains.yml`，然后执行：

```bash
cd /root/llm_wiki_hermes

python3 bin/sync_hermes_domain_hooks.py
python3 bin/sync_hermes_domain_hooks.py --check

docker restart hermes
```

正常检查结果包含：

```json
{
  "check": true,
  "domains": [
    {
      "domain": "default",
      "hook_name": "llm_wiki_router",
      "status": "ok"
    }
  ]
}
```

不要直接修改生成的 `handler.py`。下次应用领域配置时，生成器会覆盖它。

## 6. Hook 文件位置

配置来源：

```text
/root/llm_wiki_hermes/config/domains.yml
```

生成脚本：

```text
/root/llm_wiki_hermes/bin/sync_hermes_domain_hooks.py
```

运行时 hooks：

```text
/root/.hermes/hooks/<hermes_hook>/
  HOOK.yaml
  handler.py
```

生成式 handler 包含标识：

```text
Generated domain-isolated Hermes Wiki router
```

停用或重命名领域时，生成器只清理带该标识的受管 hook 文件，不处理人工创建的其他 Hermes hooks。

## 7. 固定领域 API

每个领域的用户入口调用：

```text
POST /rag/domains/{domain}/answer
```

请求：

```json
{
  "query": "OSFP-QDD-CU3可以用于CX7 NIC互连吗？"
}
```

响应关键字段：

```json
{
  "domain": "default",
  "profile": "product",
  "entrypoint_isolated": true,
  "answerable": true,
  "citations": [],
  "final_answer": "..."
}
```

安全约束：

1. 请求体包含 `domain` 或 `profile` 会返回 422。
2. 未注册领域返回 404。
3. 已停用领域不能查询。
4. Hook 会拒绝领域不一致或缺少 `entrypoint_isolated=true` 的响应。

直接测试：

```bash
curl --noproxy "*"   -X POST http://127.0.0.1:18080/rag/domains/default/answer   -H "Content-Type: application/json"   -d '{"query":"OSFP-QDD-CU3可以用于CX7 NIC互连吗？"}'
```

该接口会执行真实检索、rerank 和答案生成。

## 8. 新增第二个领域示例

假设新增运维知识库。

### 8.1 准备 Vault

```text
vault/domains/ops/
  00_Templates/
  10_Knowledge/
  90_Archive/
```

正式文档 frontmatter：

```yaml
domain: ops
status: active
rag: true
```

### 8.2 注册入口

建议配置：

```yaml
ops:
  display_name: 运维知识库
  description: 内部系统运行和故障处理知识。
  profile: product
  vault_subpath: domains/ops
  target_vault_subpath: domains/ops
  isolation_mode: domain_subpath
  rag_base_url: http://rag-api:18080
  sync_status_file: /root/llm_wiki_hermes/logs/llm-wiki-sync-status.json
  vector_backend: milvus
  vector_collection: llm_wiki_chunks_v2
  entrypoint: /opswiki
  entrypoint_aliases:
    - "opswiki:"
  entrypoint_platforms:
    - qqbot
  hermes_hook: llm_wiki_ops_router
  hermes_rag_base_url: http://127.0.0.1:18080
  enabled: true
```

当前可以共享 RAG 实例、Postgres 和 Milvus collection。检索依靠 `vault_subpath` 强制隔离。

当权限、容量或运维边界需要时，再为该领域拆分独立 database/schema、Milvus collection 或 RAG 实例；Hermes 入口协议不需要改变。

### 8.3 应用和验证

1. 在 Admin 保存领域。
2. 点击“应用入口配置”。
3. 如有变化，执行 `docker restart hermes`。
4. 运行 RAG 同步。
5. 测试 `/opswiki`。
6. 在 Admin 审计和 RAG 测试中确认来源全部属于 `domains/ops`。

## 9. Hermes 容器地址配置

生成 hook 默认使用领域中的 `hermes_rag_base_url`。

当前 Hermes 使用：

```text
http://127.0.0.1:18080
```

生成 hook 也支持环境变量覆盖：

```text
LLM_WIKI_<DOMAIN>_RAG_ANSWER_URL
LLM_WIKI_RAG_TIMEOUT_SECONDS
```

例如 `default` 领域：

```text
LLM_WIKI_DEFAULT_RAG_ANSWER_URL
```

只有 Hermes 与 RAG 的网络位置变化时才需要覆盖。修改 Hermes 容器环境变量后必须重建或重新创建 Hermes 容器。

## 10. MCP 接入的定位

MCP Bridge 地址：

```text
http://127.0.0.1:18081/mcp
```

MCP 适用于：

1. Hermes 内部 profile 显式使用知识检索工具。
2. 开发调试或其他 agent 集成。
3. 需要返回 chunks、citations 和领域/profile 信息的工具调用。

MCP 不是当前 QQBot `/wiki` 的必需链路。当前正式用户入口使用固定领域 hook，原因是：

1. 不依赖模型决定是否调用工具。
2. 不会误触发普通对话。
3. 领域边界在 endpoint 层固定。
4. 响应时间和故障位置更容易判断。

如果未来启用 MCP 工具，不要把通用 Wiki 工具暴露给普通聊天 profile；应为目标场景设置明确工具集和领域参数。

## 11. 企业微信接入预留

未来接入企业微信时：

1. 先确认 Hermes 企业微信 adapter 的实际 platform 名。
2. 在领域的 `entrypoint_platforms` 中加入该 platform。
3. 保留独立触发词，不做模型自动选领域。
4. 企业微信用户不进入 Admin。
5. 第一版仍输出内部答案。
6. “生成客户话术”作为后续独立按钮或流程，不与正式知识答案混合。

在实际 adapter 完成前，不要猜测 platform 标识并写入生产配置。

## 12. 安全边界

1. Hermes hook 只能读取 RAG 答案，不写 Vault。
2. 正式回答必须有可靠来源。
3. 无来源时返回不能回答，不使用模型常识补充。
4. 不把 LiteLLM API key 写入 hook、文档或截图。
5. 普通 QQBot 工具集不要暴露通用文件写入、终端或长期 memory。
6. Admin 当前为单管理员模式；扩大网络访问前应增加认证。
7. Admin 不获得 Docker socket。

## 13. 重启与恢复

服务器重启后：

```bash
cd /root/llm_wiki_hermes
python3 bin/sync_hermes_domain_hooks.py --check

docker ps --filter name=hermes   --format "table {{.Names}}	{{.Status}}"
```

如果 hook 有 drift：

```bash
python3 bin/sync_hermes_domain_hooks.py
python3 bin/sync_hermes_domain_hooks.py --check
docker restart hermes
```

查看加载日志：

```bash
tail -200 /root/.hermes/logs/gateway.log |   grep -E "installed domain=|hook\(s\) loaded|qqbot connected|Gateway running"
```

当前默认入口正常时应看到：

```text
llm_wiki_router
installed domain=default
qqbot connected
```

## 14. 常见问题

### 14.1 普通聊天也提示 Wiki 未命中

检查 Hermes 普通对话工具集是否暴露了 Wiki MCP 工具。正式 `/wiki` 已由 hook 处理，普通聊天不需要通用 Wiki 工具。

### 14.2 输入 /wiki 没有进入知识库

检查：

```bash
python3 /root/llm_wiki_hermes/bin/sync_hermes_domain_hooks.py --check

ls -l /root/.hermes/hooks/llm_wiki_router

tail -200 /root/.hermes/logs/gateway.log
```

如果刚生成 hook 但没有重启 Hermes，执行：

```bash
docker restart hermes
```

### 14.3 返回“检索服务暂不可用”

依次检查：

```bash
curl --noproxy "*" http://127.0.0.1:18080/health
docker logs --tail 200 llm-wiki-rag-api
tail -200 /root/.hermes/logs/gateway.log
```

### 14.4 回答来自错误领域

这是必须阻断的问题。

检查：

1. Hook 的 `DOMAIN_ID`。
2. Hook 的 `RAG_ANSWER_URL`。
3. API 响应的 `domain`。
4. `entrypoint_isolated` 是否为 `true`。
5. citations 路径是否位于目标 `vault_subpath`。

重新从注册表生成 hook，不要手工修补 handler。

### 14.5 Hook 应用后页面仍显示 not ready

1. 检查 Admin 的 hooks 挂载是否可写。
2. 查看“应用入口配置”返回详情。
3. 运行 CLI `--check`。
4. 确认 hook 名符合小写字母、数字和下划线规则。
5. 确认生成文件位于 `/root/.hermes/hooks/<hook>`。

## 15. 接入验收清单

- [ ] 领域已注册并启用。
- [ ] Vault 子目录存在且 frontmatter domain 正确。
- [ ] 领域配置校验无 error。
- [ ] Hook 生成器 `--check` 返回 ok。
- [ ] Hermes 已在 hook 变化后重启。
- [ ] Hermes 日志显示 hook 已加载。
- [ ] 普通聊天不触发 Wiki。
- [ ] 领域触发词能够返回答案或可靠拒答。
- [ ] 响应 `domain` 与入口一致。
- [ ] 响应 `entrypoint_isolated` 为 true。
- [ ] citations 全部位于目标领域。
- [ ] Wiki 问答不写入 Vault 或长期 memory。
