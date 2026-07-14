from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from config import RAG_BASE_URL


async def answer(
    query: str,
    domain: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    if not query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        response = await client.post(
            f"{RAG_BASE_URL}/rag/answer",
            json={"query": query.strip(), "domain": domain, "profile": profile},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()
