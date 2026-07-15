# LLM Wiki + Hermes 恢复操作手册

更新时间：2026-07-14

本文档用于服务器重启、Docker 服务异常退出、手动升级镜像、或需要恢复整套 LLM Wiki + Hermes 服务时使用。

项目目录：

```bash
/root/llm_wiki_hermes
```

主要入口：

- Admin Web: `http://192.168.121.20:18090`
- RAG REST: `http://192.168.121.20:18080`
- MCP Bridge: `http://127.0.0.1:18081/mcp`
- Postgres: `llm-wiki-postgres`
- Milvus: `llm-wiki-milvus`
- LiteLLM: `http://127.0.0.1:14000/v1`
- Hermes: Docker 容器 `hermes`

## 1. 当前架构

| 组件 | 运行方式 | 作用 |
| --- | --- | --- |
| `llm-wiki-postgres` | `/root/llm_wiki_hermes/postgress/docker-compose.yml` | PostgreSQL，存储文档、chunk 正文/metadata、索引状态、FTS、知识缺口和审计日志 |
| `llm-wiki-milvus` | `/root/llm_wiki_hermes/docker-compose.yml` | Milvus standalone，正式向量检索后端，当前 collection 为 `llm_wiki_chunks_v2` |
| `llm-wiki-milvus-etcd` | `/root/llm_wiki_hermes/docker-compose.yml` | Milvus 元数据依赖 |
| `llm-wiki-milvus-minio` | `/root/llm_wiki_hermes/docker-compose.yml` | Milvus 对象存储依赖 |
| LiteLLM | 独立服务 | 本地模型 OpenAI-compatible API 入口 |
| `llm-wiki-rag-api` | `/root/llm_wiki_hermes/docker-compose.yml` | RAG REST 服务，端口 `18080` |
| `llm-wiki-mcp-bridge` | `/root/llm_wiki_hermes/docker-compose.yml` | MCP bridge，端口 `127.0.0.1:18081` |
| `llm-wiki-admin-web` | `/root/llm_wiki_hermes/docker-compose.yml` | 管理后台，端口 `18090` |
| `llm-wiki-sync-runner` | `/root/llm_wiki_hermes/docker-compose.yml` | 每天一次 `git pull` + 重新索引 |
| `hermes` | Docker 容器 | QQBot / Hermes 对话入口 |

注意：

- RAG、MCP bridge、Admin Web 已经改成自包含 Docker 镜像运行。
- 服务代码在镜像内 `/app`，Python 依赖安装在镜像内。
- 开发和维护代码仍在宿主 `/root/llm_wiki_hermes`。
- Vault、logs、bin、docs、SSH、obsidian-wiki 配置和 `config/model-settings.json` 通过 volume/bind mount 提供给容器。
- 当前 RAG 向量后端为 Milvus：`VECTOR_BACKEND=milvus`，`MILVUS_COLLECTION=llm_wiki_chunks_v2`。
- Postgres 仍保留 `pgvector` 扩展作为兼容和 fallback，但正常检索优先走 Milvus。
- RAG 侧 chat/rerank 模型在 Admin Web 的“模型配置”页面管理；Hermes 自身模型不在这里管理。
- 旧 systemd 服务已停用，恢复时不要再启动 `obsidian-rag-mcp.service`、`obsidian-rag-mcp-bridge.service`、`llm-wiki-admin-web.service`、`llm-wiki-sync.timer`。

## 2. 服务器重启后快速检查

登录服务器后执行：

```bash
cd /root/llm_wiki_hermes

docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "llm-wiki|hermes|litellm" || true

docker compose ps

cd /root/llm_wiki_hermes/postgress
docker compose ps
```

正常应看到：

- `llm-wiki-postgres` 为 `Up`，最好是 `healthy`
- `llm-wiki-milvus` 为 `Up`
- `llm-wiki-milvus-etcd` 为 `Up`
- `llm-wiki-milvus-minio` 为 `Up`
- `llm-wiki-rag-api` 为 `Up`，最好是 `healthy`
- `llm-wiki-admin-web` 为 `Up`，最好是 `healthy`
- `llm-wiki-mcp-bridge` 为 `Up`
- `llm-wiki-sync-runner` 为 `Up`
- `hermes` 为 `Up`
- LiteLLM 相关容器或进程已运行

检查 HTTP：

```bash
curl --noproxy "*" http://127.0.0.1:18080/health
curl --noproxy "*" http://127.0.0.1:18090/health
curl --noproxy "*" http://127.0.0.1:18090/api/health-detail
curl --noproxy "*" http://127.0.0.1:18090/api/wiki-health
```

`18080/health` 正常应包含：

```json
{
  "ok": true,
  "vector_backend": "milvus",
  "milvus": {
    "ok": true,
    "collection": "llm_wiki_chunks_v2",
    "exists": true
  }
}
```

检查 LiteLLM 模型接口：

```bash
set -a
. /etc/obsidian-rag-mcp.env
set +a

curl --noproxy "*" http://127.0.0.1:14000/v1/models \
  -H "Authorization: Bearer $LITELLM_API_KEY"
```

不要把 `$LITELLM_API_KEY` 输出到聊天、截图或共享日志里。

## 3. 标准恢复顺序

如果服务器重启后服务没有自动恢复，按下面顺序启动。

### 3.1 启动 Postgres/pgvector

```bash
cd /root/llm_wiki_hermes/postgress
docker compose up -d postgres
docker compose ps
```

检查数据库和 vector 扩展：

```bash
docker exec -it llm-wiki-postgres psql -U rag -d rag -c "select 1;"
docker exec -it llm-wiki-postgres psql -U rag -d rag -c "\dx"
```

`\dx` 结果里应包含 `vector`。

### 3.2 启动 LiteLLM

LiteLLM 不在当前项目根 Compose 里。先检查：

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -i litellm || true
ss -ltnp | grep ':14000' || true
```

如果未启动，进入 LiteLLM 原本的 compose 目录执行：

```bash
docker compose up -d
```

验证模型：

```bash
set -a
. /etc/obsidian-rag-mcp.env
set +a

curl --noproxy "*" http://127.0.0.1:14000/v1/models \
  -H "Authorization: Bearer $LITELLM_API_KEY"
```

应包含：

- `Qwen3.6-35B-A3B-FP8`
- `Qwen3-Embedding-4B`
- `Qwen3-Reranker-0.6B`

当前 RAG 模型配置文件：

```bash
cat /root/llm_wiki_hermes/config/model-settings.json
```

通常应包含：

- `chat_model`
- `embedding_model`
- `reranker_model`

第一版 Admin Web 只开放保存 `chat_model` 和 `reranker_model`。`embedding_model` 只展示；切换 embedding 需要重新嵌入全部文档后再开放。

### 3.3 恢复 Docker 防火墙临时规则

当前服务器防火墙默认较严格。服务器重启或 Docker 网络重建后，如果宿主访问 `18080/18090` 超时，或容器访问宿主 LiteLLM `14000` 失败，需要重新检查规则。

先确认 Docker bridge 名称：

```bash
APP_BRIDGE="br-$(docker network inspect -f '{{.Id}}' llm_wiki_hermes_default | cut -c1-12)"
POSTGRES_BRIDGE="br-$(docker network inspect -f '{{.Id}}' postgress_default | cut -c1-12)"

echo "APP_BRIDGE=$APP_BRIDGE"
echo "POSTGRES_BRIDGE=$POSTGRES_BRIDGE"
```

应用当前所需规则：

```bash
iptables -C INPUT -i "$APP_BRIDGE" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null \
  || iptables -I INPUT 1 -i "$APP_BRIDGE" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

iptables -C INPUT -i "$POSTGRES_BRIDGE" -p tcp --dport 14000 -j ACCEPT 2>/dev/null \
  || iptables -I INPUT 1 -i "$POSTGRES_BRIDGE" -p tcp --dport 14000 -j ACCEPT
```

检查：

```bash
iptables -S INPUT | head -20
```

说明：

- 第一条用于宿主访问 Compose 发布端口时的回包。
- 第二条用于应用容器通过 Docker bridge 访问宿主 LiteLLM `14000`。
- 当前规则是临时规则，后续应持久化到 Shorewall、iptables-persistent 或 systemd oneshot。

### 3.4 启动 Milvus / RAG / MCP / Admin / Sync

```bash
cd /root/llm_wiki_hermes
docker compose up -d
docker compose ps
```

领域配置可在 Admin Web 的“领域管理”页面维护：先编辑并保存，再点击“应用入口配置”。页面提示需要重启时，在服务器执行 `docker restart hermes`。

配置保存前的版本保存在 `config/domains.yml.bak`。如果页面不可用，使用下面的 CLI 检查领域注册表与运行时 Hermes hooks 是否一致：

```bash
cd /root/llm_wiki_hermes
python3 bin/sync_hermes_domain_hooks.py --check
```

`--check` 返回 `status: ok` 时不需要改写 hook。若刚修改 `config/domains.yml` 或检查提示 drift，再执行：

```bash
cd /root/llm_wiki_hermes
python3 bin/sync_hermes_domain_hooks.py
python3 bin/sync_hermes_domain_hooks.py --check
docker restart hermes
```

如果只需要单独启动 Milvus 相关服务：

```bash
cd /root/llm_wiki_hermes
docker compose up -d etcd minio milvus
docker compose ps etcd minio milvus
```

如果刚更新过代码或 Dockerfile，先 build：

```bash
cd /root/llm_wiki_hermes
docker compose build
docker compose up -d --force-recreate
docker compose ps
```

构建注意：

- Dockerfile 里不要升级 pip。
- 之前升级 pip 后，远端 pip 源曾出现 `pydantic-core==2.46.4` 解析失败。
- 当前可工作的方式是使用 `python:3.12-slim` 自带 pip 直接安装 `requirements.txt`。

验证容器是否真的使用镜像内代码：

```bash
docker exec llm-wiki-rag-api sh -lc 'pwd; python -c "import app,sys; print(app.__file__); print(sys.executable)"'
```

正常应看到：

```text
/app
/app/app/__init__.py
/usr/local/bin/python
```

检查 Milvus collection：

```bash
curl --noproxy "*" http://127.0.0.1:18080/health
```

当前正常状态：

- `vector_backend` 为 `milvus`
- `milvus.collection` 为 `llm_wiki_chunks_v2`
- `milvus.exists` 为 `true`
- `milvus.entities` 应与 Postgres `chunks` 数量一致

检查 Postgres chunk 数量：

```bash
docker exec -i llm-wiki-postgres psql -U rag -d rag -c "select count(*) as chunks from chunks;"
```

如果 Milvus collection 丢失或实体数明显不一致，可以用 Postgres 中已有 embedding 重建 Milvus，不需要重新调用 embedding 模型：

```bash
docker exec -w /app -e PYTHONPATH=/app -i llm-wiki-rag-api python - <<'PY'
import math
from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
from app.config import settings
from app.db import get_conn

def parse_vector(value):
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [float(item) for item in text.split(",") if item]

def normalize(values):
    norm = math.sqrt(sum(item * item for item in values))
    return values if norm <= 0 else [item / norm for item in values]

with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("select id::text, path, embedding from chunks order by path, id")
        rows = cur.fetchall()

ids, paths, embeddings = [], [], []
for chunk_id, path, embedding in rows:
    ids.append(chunk_id)
    paths.append(path)
    embeddings.append(normalize(parse_vector(embedding)))

dim = len(embeddings[0])
connections.connect(alias="default", uri=settings.milvus_uri)
if utility.has_collection(settings.milvus_collection):
    utility.drop_collection(settings.milvus_collection)

schema = CollectionSchema([
    FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
    FieldSchema(name="path", dtype=DataType.VARCHAR, max_length=1024),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
], description="LLM Wiki chunk embeddings")

collection = Collection(settings.milvus_collection, schema=schema)
collection.create_index(
    field_name="embedding",
    index_params={
        "index_type": "HNSW",
        "metric_type": "IP",
        "params": {"M": 16, "efConstruction": 200},
    },
)
collection.insert([ids, paths, embeddings])
collection.flush()
collection.load()
print({
    "collection": settings.milvus_collection,
    "dim": dim,
    "postgres_chunks": len(rows),
    "milvus_entities": collection.num_entities,
})
PY
```

重建后再检查：

```bash
curl --noproxy "*" http://127.0.0.1:18080/health
curl --noproxy "*" http://127.0.0.1:18090/api/health-detail
```

### 3.5 启动 Hermes

Hermes 是独立 Docker 容器，正常情况下 `restart policy` 会自动恢复。

检查：

```bash
docker ps --filter name=hermes --format "table {{.Names}}\t{{.Status}}"
```

如果没有运行：

```bash
docker start hermes
```

如果需要重启：

```bash
docker restart hermes
```

查看 QQBot/Hermes 日志：

```bash
tail -200 /root/.hermes/logs/gateway.log
```

重点看：

```text
qqbot connected
hook(s) loaded
Gateway running
```

完整的单领域、多领域接入、hook 生成和故障排查参见 `docs/hermes-integration-guide.md`。

## 4. 知识更新流程

本地 Obsidian 修改 Markdown 后：

> 只执行 Git 更新不会自动更新已存在的检索索引。服务器拉取最新 Vault 后，还必须执行 RAG 同步；每日任务或下面的手动操作会完成这一步。

```bash
git add .
git commit -m "update default wiki"
git push
```

服务器通常由 `llm-wiki-sync-runner` 每天自动同步一次。

如果想立刻生效：

```bash
cd /root/llm_wiki_hermes/vault
git pull --ff-only
curl --noproxy "*" -X POST http://127.0.0.1:18080/admin/sync/run
```

或者在 Admin Web 点击：

```text
Git Pull + 重新索引
```

查看最近一次同步结果：

```bash
cat /root/llm_wiki_hermes/logs/llm-wiki-sync-status.json
curl --noproxy "*" http://127.0.0.1:18090/api/sync-status
```

文档目录、frontmatter、增删改、归档和同步验收的完整规则参见 `docs/obsidian-vault-maintenance-guide.md`。

查看同步容器日志：

```bash
docker logs --tail 120 llm-wiki-sync-runner
```

同步脚本会保留最近 20 个日志文件：

```bash
ls -lh /root/llm_wiki_hermes/logs/llm-wiki-sync-*.log
```

## 5. 功能验证

### 5.1 RAG 直接验证

```bash
curl --noproxy "*" -sS -X POST http://127.0.0.1:18080/rag/answer \
  -H 'Content-Type: application/json' \
  -d '{"query":"FTLC4353RHPL对应我司哪个型号，使用场景是什么？"}'
```

正常应返回：

- `answerable: true`
- 答案包含 `QSFP-100G-DR`
- 来源包含 `10_Knowledge/Products/QSFP-100G-DR-FR.md`

未命中验证：

```bash
curl --noproxy "*" -sS -X POST http://127.0.0.1:18080/rag/answer \
  -H 'Content-Type: application/json' \
  -d '{"query":"火星基地的咖啡机采购型号是什么？"}'
```

正常应返回：

- `answerable: false`
- `reason: no_supported_answer`
- 来源为无可靠来源

### 5.2 Admin Web 验证

```bash
curl --noproxy "*" http://127.0.0.1:18090/health
curl --noproxy "*" http://127.0.0.1:18090/api/wiki-health
curl --noproxy "*" http://127.0.0.1:18090/api/obsidian-wiki
```

Admin Web 地址：

```text
http://192.168.121.20:18090
```

推荐检查页面：

- 仪表盘
- RAG 测试
- 文档浏览
- 健康检查
- Schema 模板
- obsidian-wiki

### 5.3 obsidian-wiki 验证

Admin Web 镜像内已经安装 `obsidian-wiki`。Admin 容器启动时会自动执行：

```bash
obsidian-wiki setup --vault /root/llm_wiki_hermes/vault
```

配置目录持久化在：

```text
/root/llm_wiki_hermes/obsidian-wiki-config
```

手动验证：

```bash
docker exec llm-wiki-admin-web obsidian-wiki info
```

应看到：

- `config: /root/.obsidian-wiki/config`
- `vault: /root/llm_wiki_hermes/vault`
- agent skill install status 为已安装

### 5.4 QQBot 验证

普通消息不查 Wiki：

```text
你好
```

正式 Wiki 查询需要显式前缀：

```text
/wiki FTLC4353RHPL对应我司哪个型号，使用场景是什么？
```

如果普通对话残留旧上下文，可以在 QQBot 里发：

```text
/new
```

## 6. 常见问题处理

### 6.1 Admin Web 打不开

检查：

```bash
cd /root/llm_wiki_hermes
docker compose ps admin-web
docker logs --tail 120 llm-wiki-admin-web
ss -lntp | grep 18090 || true
curl --noproxy "*" http://127.0.0.1:18090/health
```

重启：

```bash
cd /root/llm_wiki_hermes
docker compose restart admin-web
```

如果 `127.0.0.1:18090` 超时，优先检查第 `3.3` 节防火墙规则。

### 6.2 RAG 返回 500 或索引失败

查看日志：

```bash
docker logs --tail 200 llm-wiki-rag-api
docker logs --tail 120 llm-wiki-sync-runner
```

常见原因：

- LiteLLM 未启动或 key 不对
- Postgres 未启动
- Docker bridge 到宿主 LiteLLM `14000` 的防火墙规则丢失
- Markdown frontmatter YAML 格式错误
- embedding/rerank 模型不可用

检查依赖：

```bash
curl --noproxy "*" http://127.0.0.1:18080/health

set -a
. /etc/obsidian-rag-mcp.env
set +a

curl --noproxy "*" http://127.0.0.1:14000/v1/models \
  -H "Authorization: Bearer $LITELLM_API_KEY"

docker exec -it llm-wiki-postgres psql -U rag -d rag -c "select count(*) from documents; select count(*) from chunks;"
```

### 6.3 领域入口没有走正式 Wiki

先校验注册表与生成的 hooks：

```bash
cd /root/llm_wiki_hermes
python3 bin/sync_hermes_domain_hooks.py --check
curl --noproxy "*" http://127.0.0.1:18090/api/domains
```

若检查提示 drift，重新生成并重启 Hermes：

```bash
cd /root/llm_wiki_hermes
python3 bin/sync_hermes_domain_hooks.py
python3 bin/sync_hermes_domain_hooks.py --check
docker restart hermes
```

检查默认领域 hook 和 Hermes 加载日志：

```bash
ls -l /root/.hermes/hooks/llm_wiki_router
sed -n '1,180p' /root/.hermes/hooks/llm_wiki_router/handler.py
tail -200 /root/.hermes/logs/gateway.log | grep -E "llm_wiki_router|installed domain=|hook\\(s\\) loaded|qqbot connected"
```

每个启用领域必须在 `config/domains.yml` 中使用唯一的 `entrypoint`、aliases 和 `hermes_hook`。

### 6.4 普通聊天总是提示“正式 Wiki 中没有检索到...”

这通常说明 QQBot 普通对话还暴露了 Wiki 工具，或缓存了旧 system prompt。

检查配置：

```bash
grep -n "system_prompt\|platform_toolsets\|llm_wiki" -C 3 /root/.hermes/config.yaml
```

当前推荐状态：

```yaml
agent:
  tool_use_enforcement: false

platform_toolsets:
  qqbot: []
```

`/wiki` 查询由 hook 直接调用 RAG，不依赖 QQBot 普通工具集。

清理 QQBot 会话缓存：

```bash
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect('/root/.hermes/state.db')
cur = conn.cursor()
cur.execute("update sessions set system_prompt = null where source = 'qqbot'")
print('cleared', cur.rowcount)
conn.commit()
conn.close()
PY

docker restart hermes
```

### 6.5 Postgres 没起来

```bash
cd /root/llm_wiki_hermes/postgress
docker compose up -d postgres
docker compose ps
docker logs --tail 120 llm-wiki-postgres
```

确认数据库：

```bash
docker exec -it llm-wiki-postgres psql -U rag -d rag -c "select 1;"
docker exec -it llm-wiki-postgres psql -U rag -d rag -c "\dx"
```

### 6.6 LiteLLM 没起来

查容器或进程：

```bash
docker ps -a | grep -i litellm || true
ss -ltnp | grep ':14000' || true
```

进入 LiteLLM 的 compose 目录启动：

```bash
docker compose up -d
```

验证：

```bash
set -a
. /etc/obsidian-rag-mcp.env
set +a

curl --noproxy "*" http://127.0.0.1:14000/v1/models \
  -H "Authorization: Bearer $LITELLM_API_KEY"
```

### 6.7 Compose build 失败

常见检查：

```bash
cd /root/llm_wiki_hermes
docker compose config
docker compose build rag-api admin-web
```

如果遇到 `pydantic-core==2.46.4` 找不到：

- 确认 Dockerfile 没有执行 `python -m pip install --upgrade pip`
- 使用 `python:3.12-slim` 自带 pip 直接安装 `requirements.txt`

如果 apt 下载失败：

- 检查服务器 DNS 和代理
- 稍后重试 `docker compose build admin-web`

## 7. 重要文件位置

| 路径 | 说明 |
| --- | --- |
| `/root/llm_wiki_hermes/docker-compose.yml` | RAG、MCP bridge、Admin Web、sync-runner Compose |
| `/root/llm_wiki_hermes/postgress/docker-compose.yml` | Postgres/pgvector Compose |
| `/root/llm_wiki_hermes/vault` | Obsidian Markdown 正式知识库 |
| `/root/llm_wiki_hermes/services/obsidian-rag-mcp` | RAG REST + MCP 代码和 Dockerfile |
| `/root/llm_wiki_hermes/services/admin-web` | Admin Web 代码和 Dockerfile |
| `/root/llm_wiki_hermes/bin/sync_vault_and_rag_container.sh` | 容器内 Git pull + RAG sync 脚本 |
| `/root/llm_wiki_hermes/bin/sync_loop_container.sh` | 每日同步循环脚本 |
| `/root/llm_wiki_hermes/logs` | 同步日志和状态文件 |
| `/root/llm_wiki_hermes/obsidian-wiki-config` | Admin 容器内 obsidian-wiki 持久配置 |
| `/etc/obsidian-rag-mcp.env` | RAG/LiteLLM 环境变量和密钥 |
| `/root/.hermes/config.yaml` | Hermes 配置 |
| `/root/llm_wiki_hermes/config/domains.yml` | 领域、profile、入口和 Hermes hook 注册表 |
| `/root/llm_wiki_hermes/config/domains.yml.bak` | 网页保存前的领域注册表备份 |
| `/root/llm_wiki_hermes/bin/sync_hermes_domain_hooks.py` | 根据注册表生成并校验独立领域 hooks |
| `/root/.hermes/hooks/<hermes_hook>` | 各领域生成的 Hermes 固定入口 hook |
| `/root/.hermes/logs/gateway.log` | Hermes 网关日志 |
| `/root/llm_wiki_hermes/docs/wiki-frontmatter-schema.md` | Wiki frontmatter 规范 |
| `/root/llm_wiki_hermes/docs/obsidian-vault-maintenance-guide.md` | Obsidian Vault 更新维护手册 |
| `/root/llm_wiki_hermes/docs/hermes-integration-guide.md` | Hermes 单领域与多领域接入手册 |

## 8. 备份和回滚

运行时配置和数据库可以用脚本统一备份：

```bash
/root/llm_wiki_hermes/bin/backup_runtime.sh
```

备份文件默认写入：

```bash
/root/llm_wiki_hermes/backups/runtime/
```

默认保留最近 14 个备份包。备份包权限为 `600`，因为其中包含 `/etc/obsidian-rag-mcp.env`、Hermes 配置和运行时模型配置。

备份内容包括：

- Postgres `rag` 数据库 dump：`postgres/rag.dump`
- RAG/Admin/Hermes 运行配置：`project/config/`、`etc/obsidian-rag-mcp.env`
- Hermes `config.yaml`、hooks、memories
- 关键 Compose 文件和软件设计/恢复手册
- `MANIFEST.txt`，记录项目 Git、Vault Git 和容器状态

手动调整保留数量：

```bash
RETENTION_COUNT=30 /root/llm_wiki_hermes/bin/backup_runtime.sh
```

查看最新备份包内容：

```bash
cd /root/llm_wiki_hermes
tar -tzf backups/runtime/$(ls -t backups/runtime | head -1) | head -80
```

正式知识文件只通过 Git 管理：

```bash
cd /root/llm_wiki_hermes/vault
git status
git log --oneline -5
```

如果需要回滚应用服务镜像或配置，优先使用 Git/Docker 镜像版本记录。当前本地镜像名：

```text
llm-wiki-rag:local
llm-wiki-admin-web:local
```

不建议恢复到旧 systemd 部署，除非明确需要紧急回退。旧 systemd 服务当前应保持 disabled/inactive。

检查旧 systemd 状态：

```bash
systemctl is-enabled obsidian-rag-mcp.service obsidian-rag-mcp-bridge.service llm-wiki-admin-web.service llm-wiki-sync.timer || true
systemctl is-active obsidian-rag-mcp.service obsidian-rag-mcp-bridge.service llm-wiki-admin-web.service llm-wiki-sync.timer || true
```

## 9. 最小恢复检查清单

服务器重启后，只想快速确认可用，执行：

```bash
cd /root/llm_wiki_hermes/postgress
docker compose up -d postgres

cd /root/llm_wiki_hermes
docker compose up -d

python3 bin/sync_hermes_domain_hooks.py --check
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "llm-wiki|hermes|litellm" || true

curl --noproxy "*" http://127.0.0.1:18080/health
curl --noproxy "*" http://127.0.0.1:18090/health
curl --noproxy "*" http://127.0.0.1:18090/api/domains
curl --noproxy "*" http://127.0.0.1:18090/api/wiki-health

cat /root/llm_wiki_hermes/logs/llm-wiki-sync-status.json
```

全部正常后，在 QQBot 测：

```text
/wiki FTLC4353RHPL对应我司哪个型号，使用场景是什么？
```

## 附录：Vue 管理端构建与单独恢复

管理前端源码位于：

```text
/root/llm_wiki_hermes/services/admin-web/frontend
```

技术栈为 Vue 3 + TypeScript + Vite。生产环境不在宿主机直接运行 Node 服务；Node 22 只用于 Docker 多阶段构建，最终仍由 FastAPI 在 `18090` 端口提供页面和 API。

仅更新或恢复管理端：

```bash
cd /root/llm_wiki_hermes
docker pull node:22-alpine
docker compose build admin-web
docker compose up -d --no-deps --force-recreate admin-web
docker compose ps admin-web
curl --noproxy "*" http://127.0.0.1:18090/health
curl --noproxy "*" http://127.0.0.1:18090/api/status
```

前端依赖和类型检查都在镜像构建阶段通过 `npm ci`、`vue-tsc` 和 `vite build` 完成。不要把 `frontend/node_modules` 提交到 Git 或复制进镜像上下文。

如构建停在 Node 镜像元数据：

```bash
docker pull node:22-alpine
docker compose build admin-web
```

如果容器反复重启：

```bash
docker logs --tail 120 llm-wiki-admin-web
docker inspect llm-wiki-admin-web --format 'status={{.State.Status}} exit={{.State.ExitCode}} restarts={{.RestartCount}}'
```

正常首页应包含 `/assets/index-*.js` 和 `/assets/index-*.css`，不再依赖旧的 `/static/admin.js`。
