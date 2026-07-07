from __future__ import annotations

from typing import Any

import httpx

from config import PROJECT_ROOT, RAG_BASE_URL, VAULT_PATH
from db import fetch_one
from shell import run_command
from sync_status import read_sync_status
from utils import jsonable


async def status() -> dict[str, Any]:
    counts = fetch_one("""
        select
          (select count(*) from documents) as documents,
          (select count(*) from chunks) as chunks,
          (select count(*) from indexed_files) as indexed_files,
          (select count(*) from knowledge_gaps where status='open') as knowledge_gaps_open,
          (select count(*) from audit_logs) as audit_logs
    """)
    latest_index = fetch_one("select path, status, indexed_at, error from indexed_files order by indexed_at desc limit 1")
    latest_quality = fetch_one("select created_at, summary, issues from quality_reports order by created_at desc limit 1")
    git_head = run_command(["git", "log", "-1", "--oneline", "--decorate"], cwd=VAULT_PATH, timeout=10)
    git_status = run_command(["git", "status", "--short"], cwd=VAULT_PATH, timeout=10)
    services = {
        name: run_command(["systemctl", "is-active", name], timeout=5)["stdout"].strip()
        for name in ["obsidian-rag-mcp.service", "obsidian-rag-mcp-bridge.service", "llm-wiki-sync.timer"]
    }
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            rag_health = (await client.get(f"{RAG_BASE_URL}/health")).json()
    except Exception as exc:
        rag_health = {"ok": False, "error": str(exc)}
    return jsonable({
        "vault_path": str(VAULT_PATH),
        "project_root": str(PROJECT_ROOT),
        "counts": counts,
        "latest_index": latest_index,
        "latest_quality": latest_quality,
        "git_head": git_head,
        "git_status": git_status,
        "services": services,
        "rag_health": rag_health,
        "sync_status": read_sync_status(),
    })
