# LLM Wiki Admin Web

Internal management UI for the LLM Wiki RAG stack.

Features:

- Service and index status dashboard
- Git pull / RAG sync controls
- RAG answer testing with citations and scores
- Read-only Markdown vault browser
- Knowledge gaps and audit log views
- obsidian-wiki installation/status detection

Structure:

- `main.py`: FastAPI app initialization and route registration.
- `config.py`: environment-derived paths, URLs, and constants.
- `db.py`: Postgres connection and query helpers.
- `shell.py`: subprocess command helper.
- `*_service.py`: feature-specific backend logic for status, sync, files, RAG, domains, health, knowledge map, etc.
- `web/index.html`: Admin page markup.
- `web/static/admin.css`: UI styles.
- `web/static/admin.js`: browser-side behavior.

Run locally on the server:

```bash
cd /root/llm_wiki_hermes/services/admin-web
/root/llm_wiki_hermes/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 18090
```

The UI is read-only for Markdown content. Knowledge updates still happen through Git-managed Markdown files.
