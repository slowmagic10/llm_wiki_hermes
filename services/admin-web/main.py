from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from config import INDEX_HTML, MODEL_SETTINGS_PATH, WEB_DIR
from document_rewriter_service import rewrite_document
from domain_admin_service import (
    DomainAdminError,
    apply_domain_hooks,
    save_domain_update,
    validate_domain_update,
)
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
from pdf_import_service import extract_pdf as extract_pdf_upload
from qa_service import audit as get_audit
from qa_service import gaps as get_gaps
from rag_service import answer as rag_answer
from status_service import status as get_status
from sync_service import full_sync as run_full_sync
from sync_service import git_pull as run_git_pull
from sync_service import sync_index as run_sync_index
from sync_service import sync_status as get_sync_status
from wiki_health_service import wiki_health as get_wiki_health

app = FastAPI(title="Knowledge Hub Admin", version="0.2.0")
if (WEB_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")


class QueryRequest(BaseModel):
    query: str
    domain: str | None = None
    profile: str | None = None


class ModelConfigRequest(BaseModel):
    chat_model: str
    reranker_model: str


class DomainConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str
    description: str = ""
    profile: str
    vault_subpath: str
    target_vault_subpath: str = ""
    isolation_mode: str = "domain_subpath"
    rag_base_url: str = "http://rag-api:18080"
    sync_status_file: str = "/root/llm_wiki_hermes/logs/llm-wiki-sync-status.json"
    vector_backend: str = "milvus"
    vector_collection: str = "llm_wiki_chunks_v2"
    entrypoint: str
    entrypoint_aliases: list[str] = []
    entrypoint_platforms: list[str] = ["qqbot"]
    hermes_hook: str
    hermes_rag_base_url: str = "http://127.0.0.1:18080"
    enabled: bool = True
    make_default: bool = False


class RewriteDocumentRequest(BaseModel):
    raw_markdown: str
    domain: str = "default"
    profile: str = "product"
    doc_type: str = "product_note"
    owner: str = "nick"


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


@app.post("/api/domains/validate")
def validate_domain(domain_id: str, request: DomainConfigRequest) -> dict[str, Any]:
    return validate_domain_update(
        domain_id.strip(),
        request.model_dump(exclude={"make_default"}),
        make_default=request.make_default,
    )


@app.put("/api/domains/{domain_id}")
def save_domain(domain_id: str, request: DomainConfigRequest) -> dict[str, Any]:
    try:
        return save_domain_update(
            domain_id.strip(),
            request.model_dump(exclude={"make_default"}),
            make_default=request.make_default,
        )
    except DomainAdminError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "issues": exc.issues}) from exc


@app.post("/api/domain-hooks/apply")
def apply_hooks() -> dict[str, Any]:
    try:
        return apply_domain_hooks()
    except DomainAdminError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "issues": exc.issues}) from exc


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
    return await rag_answer(request.query, domain=request.domain, profile=request.profile)


@app.post("/api/rewrite-document")
async def rewrite_document_api(request: RewriteDocumentRequest) -> dict[str, Any]:
    return await rewrite_document(
        raw_markdown=request.raw_markdown,
        domain=request.domain.strip() or "default",
        profile=request.profile.strip() or "product",
        doc_type=request.doc_type.strip() or "product_note",
        owner=request.owner.strip() or "nick",
    )


@app.post("/api/extract-pdf")
async def extract_pdf(file: UploadFile) -> dict[str, Any]:
    return await extract_pdf_upload(file)


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
def schema_template() -> dict[str, Any]:
    return get_schema_template()


@app.get("/api/obsidian-wiki")
def obsidian_wiki() -> dict[str, Any]:
    return get_obsidian_wiki()
