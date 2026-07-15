# Knowledge Hub Admin

企业知识库管理控制台。前端和管理 API 分层开发，生产环境仍通过同一个 FastAPI 容器和 `18090` 端口发布。

## 目录结构

- `frontend/`：Vue 3 + TypeScript + Vite 前端。
- `main.py`：FastAPI 初始化和管理 API 路由。
- `config.py`：路径、服务地址和环境配置。
- `*_service.py`：状态、同步、文档、RAG、领域、健康检查等后端服务。
- `web/`：旧版原生前端，仅保留为历史参考，不进入生产镜像。
- `web-vue/`：历史构建目录，不再使用。
- 生产静态文件由 Docker 多阶段构建写入镜像内的 `/app/web`。

## 前端开发

宿主机 Node 版本较旧时，优先使用 Docker 完整构建。需要本地调试时要求 Node.js 22：

```bash
cd /root/llm_wiki_hermes/services/admin-web/frontend
npm ci
npm run dev -- --host 0.0.0.0
```

Vite 开发服务器使用 `5173`，并将 `/api` 和 `/health` 代理到 `127.0.0.1:18090`。

## 生产构建

```bash
cd /root/llm_wiki_hermes
docker compose build admin-web
docker compose up -d --no-deps --force-recreate admin-web
curl --noproxy "*" http://127.0.0.1:18090/health
```

Dockerfile 的第一阶段使用 Node 22 执行 `npm ci`、`vue-tsc` 和 `vite build`；最终镜像只包含 Python、FastAPI 和构建后的静态文件。

Markdown 正式知识仍由独立 Vault Git 仓库人工维护，管理页面不会自动把草稿写入正式 Vault。
