from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.db import ping_db
from app.indexer import run_sync
from app.retriever import search


class SearchRequest(BaseModel):
    query: str
    product: str | None = None
    tags: list[str] = []


app = FastAPI(title="Obsidian RAG MCP", version="0.1.0")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "db": ping_db()}


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
        return await search(request.query, product=request.product, tags=request.tags)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/rag/answer")
async def rag_answer(request: SearchRequest) -> dict[str, Any]:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    try:
        clean_query = request.query.strip()
        result = await search(clean_query, product=request.product, tags=request.tags)
        from app.mcp_server import _build_final_answer, _final_answer_has_no_basis, _mark_no_supported_answer

        result["final_answer"] = await _build_final_answer(clean_query, result)
        if _final_answer_has_no_basis(result["final_answer"]):
            _mark_no_supported_answer(clean_query, result)
        result["response_contract"] = (
            "Use final_answer as the user-facing answer. Do not add facts that are "
            "not present in citations or chunks."
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
