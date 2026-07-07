from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import INDEX_HTML, MODEL_SETTINGS_PATH, WEB_DIR
from domains_service import domain_registry_status
from files_service import file_preview as get_file_preview
from files_service import list_files, schema_template as get_schema_template
from health_service import health_detail as get_health_detail
from knowledge_map_service import knowledge_map_data
from model_settings import (
    effective_model_settings,
    list_litellm_models,
    model_defaults,
    read_model_settings,
    write_model_settings,
)
from obsidian_service import obsidian_wiki as get_obsidian_wiki
from qa_service import audit as get_audit
from qa_service import gaps as get_gaps
from rag_service import answer as rag_answer
from status_service import status as get_status
from sync_service import full_sync as run_full_sync
from sync_service import git_pull as run_git_pull
from sync_service import sync_index as run_sync_index
from sync_service import sync_status as get_sync_status
from wiki_health_service import wiki_health as get_wiki_health

app = FastAPI(title="LLM Wiki Admin", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


class QueryRequest(BaseModel):
    query: str


class ModelConfigRequest(BaseModel):
    chat_model: str
    reranker_model: str


def read_index_html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return read_index_html()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return await get_status()


@app.get("/api/model-config")
async def model_config() -> dict[str, Any]:
    try:
        available_models = await list_litellm_models()
        litellm_error = None
    except Exception as exc:
        available_models = []
        litellm_error = str(exc)
    return {
        "settings_path": str(MODEL_SETTINGS_PATH),
        "defaults": model_defaults(),
        "saved": read_model_settings(),
        "effective": effective_model_settings(),
        "available_models": available_models,
        "litellm_error": litellm_error,
        "notes": {
            "scope": "Only Wiki/RAG service models are managed here. Hermes model config is separate.",
            "embedding_model": "Displayed only in the first version. Changing embedding requires a full re-embedding workflow.",
        },
    }


@app.post("/api/model-config")
async def save_model_config(request: ModelConfigRequest) -> dict[str, Any]:
    chat_model = request.chat_model.strip()
    reranker_model = request.reranker_model.strip()
    if not chat_model or not reranker_model:
        raise HTTPException(status_code=400, detail="chat_model and reranker_model are required")

    try:
        available_models = await list_litellm_models()
    except Exception:
        available_models = []

    if available_models:
        invalid = [model for model in (chat_model, reranker_model) if model not in available_models]
        if invalid:
            raise HTTPException(status_code=400, detail=f"model is not available from LiteLLM: {', '.join(invalid)}")

    saved = write_model_settings({"chat_model": chat_model, "reranker_model": reranker_model})
    return {
        "ok": True,
        "settings_path": str(MODEL_SETTINGS_PATH),
        "saved": saved,
        "effective": effective_model_settings(),
        "available_models": available_models,
    }


@app.get("/api/domains")
def domains() -> dict[str, Any]:
    return domain_registry_status()


@app.get("/api/knowledge-map")
def knowledge_map() -> dict[str, Any]:
    return knowledge_map_data()


@app.get("/api/sync-status")
def sync_status() -> dict[str, Any]:
    return get_sync_status()


@app.post("/api/git-pull")
def git_pull() -> dict[str, Any]:
    return run_git_pull()


@app.post("/api/sync-index")
async def sync_index() -> dict[str, Any]:
    return await run_sync_index()


@app.post("/api/full-sync")
def full_sync() -> dict[str, Any]:
    return run_full_sync()


@app.post("/api/rag-test")
async def rag_test(request: QueryRequest) -> dict[str, Any]:
    return await rag_answer(request.query)


@app.get("/api/files")
def files(path: str = Query(".")) -> dict[str, object]:
    return list_files(path)


@app.get("/api/file")
def file_preview(path: str) -> dict[str, str]:
    return get_file_preview(path)


@app.get("/api/gaps")
def gaps() -> list[dict[str, Any]]:
    return get_gaps()


@app.get("/api/audit")
def audit() -> list[dict[str, Any]]:
    return get_audit()


@app.get("/api/wiki-health")
def wiki_health() -> dict[str, Any]:
    return get_wiki_health()


@app.get("/api/health-detail")
async def health_detail() -> dict[str, Any]:
    return await get_health_detail()


@app.get("/api/schema-template")
def schema_template() -> dict[str, str]:
    return get_schema_template()


@app.get("/api/obsidian-wiki")
def obsidian_wiki() -> dict[str, Any]:
    return get_obsidian_wiki()
