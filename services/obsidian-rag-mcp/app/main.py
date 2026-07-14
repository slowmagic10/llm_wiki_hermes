from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.db import ping_db
from app.indexer import run_sync
from app.profiles import ProfileConfigError
from app.retriever import search
from app.vector_store import milvus_enabled, ping_milvus, vector_backend_name


class SearchRequest(BaseModel):
    query: str
    product: str | None = None
    tags: list[str] = Field(default_factory=list)
    domain: str | None = None
    profile: str | None = None


class DomainEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    product: str | None = None
    tags: list[str] = Field(default_factory=list)


app = FastAPI(title="Obsidian RAG MCP", version="0.1.0")


@app.get("/health")
def health() -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True, "db": ping_db(), "vector_backend": vector_backend_name()}
    if milvus_enabled():
        try:
            result["milvus"] = {"ok": True, **ping_milvus()}
        except Exception as exc:
            result["milvus"] = {"ok": False, "error": str(exc)}
    return result


@app.post("/admin/sync/run")
async def sync_run() -> dict[str, Any]:
    try:
        return await run_sync()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/rag/search")
async def rag_search(request: SearchRequest) -> dict[str, Any]:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    try:
        return await search(
            request.query,
            product=request.product,
            tags=request.tags,
            domain=request.domain,
            profile=request.profile,
        )
    except ProfileConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _answer(
    query: str,
    *,
    product: str | None,
    tags: list[str],
    domain: str | None,
    profile: str | None,
) -> dict[str, Any]:
    clean_query = query.strip()
    result = await search(
        clean_query,
        product=product,
        tags=tags,
        domain=domain,
        profile=profile,
    )
    from app.mcp_server import _build_final_answer, _final_answer_has_no_basis, _mark_no_supported_answer

    result["final_answer"] = await _build_final_answer(clean_query, result)
    if _final_answer_has_no_basis(result["final_answer"]):
        _mark_no_supported_answer(clean_query, result)
    result["response_contract"] = (
        "Use final_answer as the user-facing answer. Do not add facts that are not "
        "present in citations or chunks."
    )
    return result


@app.post("/rag/answer")
async def rag_answer(request: SearchRequest) -> dict[str, Any]:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    try:
        return await _answer(
            request.query,
            product=request.product,
            tags=request.tags,
            domain=request.domain,
            profile=request.profile,
        )
    except ProfileConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/rag/domains/{domain}/answer")
async def domain_rag_answer(domain: str, request: DomainEntryRequest) -> dict[str, Any]:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    try:
        result = await _answer(
            request.query,
            product=request.product,
            tags=request.tags,
            domain=domain,
            profile=None,
        )
        result["entrypoint_isolated"] = True
        return result
    except ProfileConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
