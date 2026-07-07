from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from config import DOMAIN_REGISTRY_PATH, LITELLM_API_KEY, LITELLM_BASE_URL, RAG_BASE_URL, VAULT_PATH
from db import fetch_one
from domains_service import domain_registry_status
from obsidian_service import obsidian_wiki
from shell import run_command
from sync_status import read_sync_status
from utils import jsonable
from wiki_health_service import wiki_health


def health_item(name: str, ok: bool, *, status: str | None = None, message: str = "", details: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "status": status or ("ok" if ok else "failed"),
        "message": message,
        "details": jsonable(details),
    }


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def health_detail() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    try:
        db_info = fetch_one("""
            select
              (select count(*) from documents) as documents,
              (select count(*) from chunks) as chunks,
              (select count(*) from indexed_files) as indexed_files,
              (select count(*) from knowledge_gaps where status='open') as open_gaps,
              (select count(*) from audit_logs) as audit_logs
        """)
        checks.append(health_item("postgres", True, message="数据库连接正常", details=db_info))
        chunks = int(db_info.get("chunks") or 0)
        documents = int(db_info.get("documents") or 0)
        checks.append(health_item(
            "index_counts",
            chunks > 0 and documents > 0,
            status="ok" if chunks > 0 and documents > 0 else "warning",
            message=f"documents={documents}, chunks={chunks}",
            details={"documents": documents, "chunks": chunks},
        ))
    except Exception as exc:
        checks.append(health_item("postgres", False, message=str(exc)))

    try:
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            response = await client.get(f"{RAG_BASE_URL}/health")
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
        ok = response.status_code < 400 and bool(body.get("ok", True) if isinstance(body, dict) else True)
        checks.append(health_item("rag_api", ok, message=f"HTTP {response.status_code}", details=body))
        if isinstance(body, dict):
            vector_backend = body.get("vector_backend") or "unknown"
            milvus = body.get("milvus") or {}
            if vector_backend == "milvus":
                milvus_ok = bool(milvus.get("ok"))
                checks.append(health_item(
                    "milvus",
                    milvus_ok,
                    message=(
                        f"collection={milvus.get('collection')}, entities={milvus.get('entities')}"
                        if milvus_ok else str(milvus.get("error") or "Milvus 检查失败")
                    ),
                    details=milvus,
                ))
            else:
                checks.append(health_item(
                    "milvus",
                    False,
                    status="warning",
                    message=f"未启用 Milvus，当前后端: {vector_backend}",
                    details=body,
                ))
    except Exception as exc:
        checks.append(health_item("rag_api", False, message=str(exc), details={"base_url": RAG_BASE_URL}))

    try:
        headers = {"Authorization": f"Bearer {LITELLM_API_KEY}"} if LITELLM_API_KEY else {}
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.get(f"{LITELLM_BASE_URL.rstrip('/')}/models", headers=headers)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        model_ids = [item.get("id") for item in body.get("data", []) if isinstance(item, dict)] if isinstance(body, dict) else []
        required = ["Qwen3-Embedding-4B", "Qwen3-Reranker-0.6B"]
        missing = [model for model in required if model not in model_ids]
        checks.append(health_item(
            "litellm_models",
            response.status_code < 400 and not missing,
            status="ok" if response.status_code < 400 and not missing else "warning",
            message="模型接口正常" if not missing else f"缺少模型: {', '.join(missing)}",
            details={"status_code": response.status_code, "models": model_ids},
        ))
    except Exception as exc:
        checks.append(health_item("litellm_models", False, message=str(exc), details={"base_url": LITELLM_BASE_URL}))

    try:
        registry = domain_registry_status()
        summary = registry.get("summary", {})
        errors = int(summary.get("errors") or 0)
        warnings_count = int(summary.get("warnings") or 0)
        domain_count = int(summary.get("domains") or 0)
        enabled_count = int(summary.get("enabled") or 0)
        checks.append(health_item(
            "domain_registry",
            errors == 0 and domain_count > 0 and enabled_count > 0,
            status="ok" if errors == 0 and warnings_count == 0 and domain_count > 0 and enabled_count > 0 else ("warning" if errors == 0 else "failed"),
            message=f"domains={domain_count}, enabled={enabled_count}, issues={summary.get('issues')}",
            details=registry,
        ))
    except Exception as exc:
        checks.append(health_item("domain_registry", False, message=str(exc), details={"path": str(DOMAIN_REGISTRY_PATH)}))

    git_head = run_command(["git", "log", "-1", "--oneline", "--decorate"], cwd=VAULT_PATH, timeout=10)
    git_status = run_command(["git", "status", "--short"], cwd=VAULT_PATH, timeout=10)
    git_ok = git_head.get("ok", False) and git_status.get("ok", False)
    dirty = bool((git_status.get("stdout") or "").strip())
    checks.append(health_item(
        "vault_git",
        git_ok and not dirty,
        status="ok" if git_ok and not dirty else "warning",
        message="Vault Git 工作区干净" if git_ok and not dirty else "Vault Git 有未提交改动或检查失败",
        details={"head": git_head, "status": git_status},
    ))

    sync = read_sync_status()
    sync_status_value = sync.get("status")
    ended_at = parse_iso_datetime(sync.get("ended_at") or sync.get("started_at"))
    age_hours = None
    if ended_at:
        age_hours = round((datetime.now(timezone.utc) - ended_at).total_seconds() / 3600, 2)
    sync_ok = sync_status_value == "success"
    sync_warn = sync_ok and age_hours is not None and age_hours > 36
    checks.append(health_item(
        "sync_status",
        sync_ok and not sync_warn,
        status="ok" if sync_ok and not sync_warn else ("warning" if sync_ok else "failed"),
        message=f"最近同步状态: {sync_status_value or 'unknown'}" + (f", {age_hours} 小时前" if age_hours is not None else ""),
        details=sync,
    ))

    try:
        wiki = wiki_health()
        summary = wiki.get("summary", {})
        errors = int(summary.get("errors") or 0)
        warnings = int(summary.get("warnings") or 0)
        checks.append(health_item(
            "wiki_quality",
            errors == 0,
            status="ok" if errors == 0 and warnings == 0 else ("warning" if errors == 0 else "failed"),
            message=f"errors={errors}, warnings={warnings}",
            details=wiki,
        ))
    except Exception as exc:
        checks.append(health_item("wiki_quality", False, message=str(exc)))

    try:
        obsidian = obsidian_wiki()
        installed = bool(obsidian.get("installed"))
        info_ok = bool((obsidian.get("info") or {}).get("ok"))
        checks.append(health_item(
            "obsidian_wiki",
            installed and info_ok,
            status="ok" if installed and info_ok else "warning",
            message="obsidian-wiki 可用" if installed and info_ok else "obsidian-wiki 需要检查",
            details=obsidian,
        ))
    except Exception as exc:
        checks.append(health_item("obsidian_wiki", False, message=str(exc)))

    failed = sum(1 for item in checks if item["status"] == "failed")
    warnings = sum(1 for item in checks if item["status"] == "warning")
    ok_count = sum(1 for item in checks if item["status"] == "ok")
    overall = "failed" if failed else ("warning" if warnings else "ok")
    return {
        "summary": {
            "overall": overall,
            "checks": len(checks),
            "ok": ok_count,
            "failed": failed,
            "warnings": warnings,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
        "checks": checks,
    }
