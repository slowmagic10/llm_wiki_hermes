from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from config import RAG_BASE_URL, SYNC_SCRIPT, VAULT_PATH
from shell import run_command
from sync_status import read_sync_status
from utils import jsonable


def sync_status() -> dict[str, Any]:
    return jsonable(read_sync_status())


def git_pull() -> dict[str, Any]:
    return run_command(["git", "pull", "--ff-only"], cwd=VAULT_PATH, timeout=180)


async def sync_index() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
        response = await client.post(f"{RAG_BASE_URL}/admin/sync/run")
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
    return {"ok": response.status_code < 400, "status_code": response.status_code, "body": body}


def full_sync() -> dict[str, Any]:
    if not SYNC_SCRIPT.exists():
        raise HTTPException(status_code=500, detail=f"sync script not found: {SYNC_SCRIPT}")
    return run_command([str(SYNC_SCRIPT)], timeout=900)
