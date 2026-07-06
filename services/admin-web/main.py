from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import yaml

import httpx
import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/root/llm_wiki_hermes"))
VAULT_PATH = Path(os.getenv("VAULT_PATH", str(PROJECT_ROOT / "vault"))).resolve()
RAG_BASE_URL = os.getenv("RAG_BASE_URL", "http://127.0.0.1:18080")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rag:rag@127.0.0.1:25432/rag")
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:14000/v1")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
SYNC_SCRIPT = Path(os.getenv("SYNC_SCRIPT", str(PROJECT_ROOT / "bin/sync_vault_and_rag.sh")))
SYNC_STATUS_FILE = Path(os.getenv("SYNC_STATUS_FILE", str(PROJECT_ROOT / "logs/llm-wiki-sync-status.json")))
SCHEMA_DOC = PROJECT_ROOT / "docs" / "wiki-frontmatter-schema.md"
MODEL_SETTINGS_PATH = Path(os.getenv("MODEL_SETTINGS_PATH", str(PROJECT_ROOT / "config/model-settings.json")))
DOMAIN_REGISTRY_PATH = Path(os.getenv("DOMAIN_REGISTRY_PATH", str(PROJECT_ROOT / "config/domains.yml")))

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
REQUIRED_FRONTMATTER = ("title", "type", "status", "owner", "updated", "domain")
VALID_STATUS = {"active", "draft", "archived"}
SKU_KEYS = ("sku", "aliases")

app = FastAPI(title="LLM Wiki Admin", version="0.1.0")


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 120) -> dict[str, Any]:
    env = os.environ.copy()
    env.update({"NO_PROXY": "*", "no_proxy": "*"})
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "returncode": 124, "stdout": exc.stdout or "", "stderr": "timeout"}
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout[-12000:],
        "stderr": result.stderr[-12000:],
    }


def _conn():
    return psycopg2.connect(DATABASE_URL)


def _fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row or {})


def _fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def _safe_rel_path(value: str) -> Path:
    rel = Path(value or ".")
    if rel.is_absolute() or ".." in rel.parts:
        raise HTTPException(status_code=400, detail="invalid path")
    target = (VAULT_PATH / rel).resolve()
    if not str(target).startswith(str(VAULT_PATH)):
        raise HTTPException(status_code=400, detail="invalid path")
    return target


def _read_sync_status() -> dict[str, Any]:
    if not SYNC_STATUS_FILE.exists():
        return {"exists": False, "path": str(SYNC_STATUS_FILE)}
    try:
        data = json.loads(SYNC_STATUS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"exists": True, "path": str(SYNC_STATUS_FILE), "error": str(exc)}
    data["exists"] = True
    data["path"] = str(SYNC_STATUS_FILE)
    log_file = data.get("log_file")
    if log_file:
        log_path = Path(str(log_file))
        if log_path.exists():
            try:
                data["log_tail"] = log_path.read_text(encoding="utf-8", errors="replace")[-12000:]
            except Exception as exc:
                data["log_tail_error"] = str(exc)
    return data


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _litellm_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_API_KEY}"
    return headers


def _read_model_settings() -> dict[str, Any]:
    if not MODEL_SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(MODEL_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _model_defaults() -> dict[str, str]:
    return {
        "chat_model": os.getenv("CHAT_MODEL", "Qwen3.6-27B-FP8"),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "Qwen3-Embedding-4B"),
        "reranker_model": os.getenv("RERANKER_MODEL", "Qwen3-Reranker-0.6B"),
    }


def _effective_model_settings() -> dict[str, str]:
    defaults = _model_defaults()
    saved = _read_model_settings()
    return {
        "chat_model": str(saved.get("chat_model") or defaults["chat_model"]),
        "embedding_model": str(saved.get("embedding_model") or defaults["embedding_model"]),
        "reranker_model": str(saved.get("reranker_model") or defaults["reranker_model"]),
    }


def _write_model_settings(values: dict[str, str]) -> dict[str, Any]:
    MODEL_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **_effective_model_settings(),
        **values,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    MODEL_SETTINGS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _default_domain_registry() -> dict[str, Any]:
    return {
        "version": 1,
        "default_domain": "default",
        "vault_layout": {
            "mode": "legacy_root",
            "target_root": "domains",
            "migration": "manual",
        },
        "domains": {
            "default": {
                "display_name": "默认知识库",
                "description": "当前单领域正式 Wiki；第一版不迁移 Vault 目录。",
                "profile": "product",
                "vault_subpath": ".",
                "target_vault_subpath": "domains/default",
                "isolation_mode": "legacy_root",
                "rag_base_url": RAG_BASE_URL,
                "sync_status_file": str(SYNC_STATUS_FILE),
                "vector_backend": os.getenv("VECTOR_BACKEND", "milvus"),
                "vector_collection": os.getenv("MILVUS_COLLECTION", "llm_wiki_chunks_v2"),
                "entrypoint": "/wiki",
                "enabled": True,
            }
        },
    }


def _read_domain_registry() -> dict[str, Any]:
    source = "file"
    if DOMAIN_REGISTRY_PATH.exists():
        raw = yaml.safe_load(DOMAIN_REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    else:
        raw = _default_domain_registry()
        source = "default"
    if not isinstance(raw, dict):
        raw = {}
    domains = raw.get("domains")
    if not isinstance(domains, dict):
        domains = {}
    normalized: dict[str, Any] = {
        "version": raw.get("version", 1),
        "default_domain": str(raw.get("default_domain") or "default"),
        "vault_layout": raw.get("vault_layout") if isinstance(raw.get("vault_layout"), dict) else {},
        "registry_path": str(DOMAIN_REGISTRY_PATH),
        "source": source,
        "domains": domains,
        "notes": raw.get("notes", []),
    }
    return normalized


def _validate_domain_registry(registry: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    domains = registry.get("domains") or {}
    if not domains:
        issues.append({"severity": "error", "domain": "-", "code": "empty_domains", "message": "domains 不能为空"})
        return issues
    default_domain = str(registry.get("default_domain") or "")
    if default_domain and default_domain not in domains:
        issues.append({"severity": "error", "domain": default_domain, "code": "missing_default_domain", "message": "default_domain 未在 domains 中定义"})
    required = ("display_name", "profile", "vault_subpath", "rag_base_url", "sync_status_file", "enabled")
    for domain_id, config in domains.items():
        if not isinstance(config, dict):
            issues.append({"severity": "error", "domain": str(domain_id), "code": "invalid_domain_config", "message": "领域配置必须是对象"})
            continue
        for key in required:
            if key not in config:
                issues.append({"severity": "warning", "domain": str(domain_id), "code": "missing_field", "message": f"缺少字段: {key}"})
        subpath = str(config.get("vault_subpath") or "")
        if subpath.startswith("/") or ".." in Path(subpath).parts:
            issues.append({"severity": "error", "domain": str(domain_id), "code": "invalid_vault_subpath", "message": f"vault_subpath 不安全: {subpath}"})
        target_subpath = str(config.get("target_vault_subpath") or "")
        if target_subpath and (target_subpath.startswith("/") or ".." in Path(target_subpath).parts):
            issues.append({"severity": "error", "domain": str(domain_id), "code": "invalid_target_vault_subpath", "message": f"target_vault_subpath 不安全: {target_subpath}"})
    return issues


def _domain_path_status(subpath: str) -> dict[str, Any]:
    rel = subpath or "."
    if rel.startswith("/") or ".." in Path(rel).parts:
        return {"safe": False, "exists": False, "markdown_files": 0, "path": rel}
    target = (VAULT_PATH / rel).resolve()
    if not str(target).startswith(str(VAULT_PATH)):
        return {"safe": False, "exists": False, "markdown_files": 0, "path": rel}
    exists = target.exists() and target.is_dir()
    markdown_files = len(list(target.rglob("*.md"))) if exists else 0
    return {
        "safe": True,
        "exists": exists,
        "markdown_files": markdown_files,
        "path": rel,
        "absolute_path": str(target),
    }


def _domain_indexed_count(subpath: str) -> int | None:
    rel = subpath or "."
    try:
        if rel == ".":
            row = _fetch_one("select count(*) as count from indexed_files")
        else:
            prefix = rel.rstrip("/") + "/"
            row = _fetch_one("select count(*) as count from indexed_files where path = %s or path like %s", (rel, prefix + "%"))
        return int(row.get("count") or 0)
    except Exception:
        return None


def _domain_registry_status() -> dict[str, Any]:
    registry = _read_domain_registry()
    issues = _validate_domain_registry(registry)
    domains = registry.get("domains") or {}
    enriched_domains: dict[str, Any] = {}
    for domain_id, config in domains.items():
        if not isinstance(config, dict):
            enriched_domains[str(domain_id)] = config
            continue
        current_status = _domain_path_status(str(config.get("vault_subpath") or "."))
        target_status = _domain_path_status(str(config.get("target_vault_subpath") or ""))
        enriched_domains[str(domain_id)] = {
            **config,
            "vault_status": {
                **current_status,
                "indexed_files": _domain_indexed_count(str(config.get("vault_subpath") or ".")),
            },
            "target_vault_status": target_status if config.get("target_vault_subpath") else None,
        }
    enabled_domains = [item for item in enriched_domains.values() if isinstance(item, dict) and bool(item.get("enabled"))]
    return {
        **registry,
        "domains": enriched_domains,
        "summary": {
            "domains": len(enriched_domains),
            "enabled": len(enabled_domains),
            "isolated": sum(1 for item in enabled_domains if item.get("isolation_mode") == "domain_subpath"),
            "legacy_root": sum(1 for item in enabled_domains if item.get("isolation_mode") == "legacy_root"),
            "issues": len(issues),
            "errors": sum(1 for item in issues if item.get("severity") == "error"),
            "warnings": sum(1 for item in issues if item.get("severity") == "warning"),
        },
        "issues": issues,
    }


async def _list_litellm_models() -> list[str]:
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        response = await client.get(f"{LITELLM_BASE_URL.rstrip('/')}/models", headers=_litellm_headers())
        response.raise_for_status()
        payload = response.json()
    models = []
    for item in payload.get("data", []):
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id:
            models.append(model_id)
    return sorted(set(models))


class QueryRequest(BaseModel):
    query: str


class ModelConfigRequest(BaseModel):
    chat_model: str
    reranker_model: str


HTML_PAGE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>LLM Wiki Admin</title>
  <style>
    :root {
      color-scheme: light;
      --bg:#f4f6f8;
      --surface:#ffffff;
      --surface-soft:#f8fafc;
      --line:#d8dee8;
      --line-strong:#c3cad6;
      --text:#17202a;
      --muted:#647084;
      --blue:#2563eb;
      --blue-soft:#e8f0ff;
      --green:#0f8f52;
      --green-soft:#e7f6ee;
      --red:#b42318;
      --red-soft:#fdebea;
      --amber:#a16207;
      --amber-soft:#fff6db;
      --code:#111827;
      --shadow:0 1px 2px rgba(15,23,42,.06), 0 10px 24px rgba(15,23,42,.05);
    }
    * { box-sizing:border-box; }
    body {
      margin:0;
      background:var(--bg);
      color:var(--text);
      font:14px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    }
    .shell { min-height:100vh; display:grid; grid-template-columns:248px 1fr; }
    aside {
      background:var(--surface);
      border-right:1px solid var(--line);
      padding:18px 14px;
      position:sticky;
      top:0;
      height:100vh;
      overflow:auto;
    }
    .brand { padding:0 8px 16px; border-bottom:1px solid var(--line); margin-bottom:14px; }
    .brand-title { font-size:18px; font-weight:720; letter-spacing:0; }
    .brand-subtitle { color:var(--muted); font-size:12px; margin-top:3px; }
    nav { display:grid; gap:4px; }
    .nav-group { color:var(--muted); font-size:11px; font-weight:720; letter-spacing:.08em; text-transform:uppercase; padding:12px 10px 5px; }
    nav button {
      border:0;
      background:transparent;
      color:var(--text);
      border-radius:7px;
      cursor:pointer;
      display:flex;
      align-items:center;
      justify-content:space-between;
      min-height:38px;
      padding:8px 10px;
      text-align:left;
    }
    nav button:hover { background:var(--surface-soft); }
    nav button.active { background:var(--blue-soft); color:#1749b5; font-weight:650; }
    .nav-key { color:var(--muted); font-size:12px; }
    .page { min-width:0; }
    header {
      min-height:64px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:16px;
      padding:14px 24px;
      background:rgba(255,255,255,.92);
      border-bottom:1px solid var(--line);
      position:sticky;
      top:0;
      z-index:10;
    }
    .header-title { font-size:17px; font-weight:700; }
    .header-meta { color:var(--muted); font-size:12px; margin-top:2px; }
    .header-right { display:flex; align-items:center; gap:10px; flex-wrap:wrap; justify-content:flex-end; }
    section { display:none; padding:22px 24px 36px; max-width:1440px; }
    section.active { display:block; }
    .section-head {
      display:flex;
      align-items:flex-end;
      justify-content:space-between;
      gap:16px;
      margin-bottom:14px;
    }
    h2 { margin:0; font-size:20px; line-height:1.25; }
    .section-desc { margin-top:5px; color:var(--muted); max-width:760px; }
    .toolbar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
    button, input, textarea { font:inherit; }
    button.action {
      border:1px solid var(--line-strong);
      background:var(--surface);
      color:var(--text);
      border-radius:7px;
      min-height:36px;
      padding:7px 11px;
      cursor:pointer;
      box-shadow:0 1px 1px rgba(15,23,42,.03);
    }
    button.action:hover { border-color:#8fa0b8; background:#fbfcfe; }
    button.primary { background:var(--blue); color:#fff; border-color:var(--blue); }
    button.primary:hover { background:#1d4ed8; border-color:#1d4ed8; }
    .grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); }
    .dashboard-grid { display:grid; gap:14px; grid-template-columns:1.25fr .75fr; align-items:start; }
    .card {
      background:var(--surface);
      border:1px solid var(--line);
      border-radius:8px;
      padding:14px;
      box-shadow:var(--shadow);
      min-width:0;
    }
    .panel {
      background:var(--surface);
      border:1px solid var(--line);
      border-radius:8px;
      box-shadow:var(--shadow);
      overflow:hidden;
    }
    .panel-head {
      padding:12px 14px;
      border-bottom:1px solid var(--line);
      background:var(--surface-soft);
      display:flex;
      justify-content:space-between;
      gap:10px;
      align-items:center;
    }
    .panel-body { padding:14px; }
    .metric-label { color:var(--muted); font-size:12px; }
    .metric { font-size:27px; line-height:1.15; font-weight:760; margin-top:5px; }
    .metric-sub { color:var(--muted); font-size:12px; margin-top:7px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .state-band {
      display:grid;
      grid-template-columns:1fr auto;
      gap:14px;
      align-items:center;
      padding:16px;
      border:1px solid var(--line);
      border-radius:8px;
      background:var(--surface);
      box-shadow:var(--shadow);
      margin-bottom:14px;
    }
    .state-title { display:flex; align-items:center; gap:10px; font-size:18px; font-weight:760; }
    .state-desc { color:var(--muted); margin-top:6px; }
    .pipeline {
      display:grid;
      grid-template-columns:repeat(5,minmax(120px,1fr));
      gap:10px;
    }
    .node {
      border:1px solid var(--line);
      background:var(--surface);
      border-radius:8px;
      padding:12px;
      min-height:92px;
      box-shadow:0 1px 2px rgba(15,23,42,.04);
      position:relative;
    }
    .node::after {
      content:"";
      position:absolute;
      top:45px;
      right:-10px;
      width:10px;
      height:1px;
      background:var(--line-strong);
    }
    .node:last-child::after { display:none; }
    .node-name { font-weight:730; margin-bottom:8px; }
    .node-msg { color:var(--muted); font-size:12px; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
    .list { display:grid; gap:8px; }
    .list-row { display:grid; grid-template-columns:1fr auto; gap:10px; align-items:center; padding:9px 0; border-bottom:1px solid var(--line); }
    .list-row:last-child { border-bottom:0; }
    .list-title { font-weight:650; }
    .list-sub { color:var(--muted); font-size:12px; margin-top:2px; }
    details.raw { margin-top:14px; }
    details.raw summary { cursor:pointer; color:var(--muted); font-weight:650; margin-bottom:8px; }
    .muted { color:var(--muted); }
    .badge {
      display:inline-flex;
      align-items:center;
      justify-content:center;
      min-height:24px;
      padding:2px 9px;
      border-radius:999px;
      border:1px solid var(--line);
      background:var(--surface-soft);
      color:var(--muted);
      font-size:12px;
      font-weight:650;
      white-space:nowrap;
    }
    .badge.ok { color:var(--green); background:var(--green-soft); border-color:#b8e3c8; }
    .badge.bad { color:var(--red); background:var(--red-soft); border-color:#f2b7b2; }
    .badge.warn { color:var(--amber); background:var(--amber-soft); border-color:#efd184; }
    .ok { color:var(--green); font-weight:650; }
    .bad { color:var(--red); font-weight:650; }
    .warn { color:var(--amber); font-weight:650; }
    input, textarea, select {
      border:1px solid var(--line-strong);
      border-radius:7px;
      padding:10px 11px;
      width:100%;
      background:#fff;
      color:var(--text);
      outline:none;
    }
    textarea { min-height:118px; resize:vertical; }
    input:focus, textarea:focus, select:focus { border-color:var(--blue); box-shadow:0 0 0 3px rgba(37,99,235,.13); }
    select:disabled { color:var(--muted); background:var(--surface-soft); }
    .form-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }
    .field { display:grid; gap:7px; }
    .field label { font-weight:700; }
    .field-help { color:var(--muted); font-size:12px; }
    .notice { border:1px solid var(--line); border-radius:8px; padding:12px; background:var(--surface-soft); color:var(--muted); }
    pre {
      margin:0;
      white-space:pre-wrap;
      word-break:break-word;
      background:var(--code);
      color:#e5e7eb;
      border-radius:7px;
      padding:12px;
      max-height:540px;
      overflow:auto;
      font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    }
    table { width:100%; border-collapse:separate; border-spacing:0; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    th, td { border-bottom:1px solid var(--line); padding:10px 11px; vertical-align:top; text-align:left; }
    th { background:var(--surface-soft); font-size:12px; color:#344054; font-weight:700; }
    tr:last-child td { border-bottom:0; }
    tbody tr:hover td { background:#fbfcfe; }
    .split { display:grid; grid-template-columns:minmax(260px,340px) 1fr; gap:14px; }
    .docs-layout { display:grid; grid-template-columns:minmax(250px,320px) minmax(420px,1fr) minmax(260px,340px); gap:14px; align-items:start; }
    .file-list { display:grid; gap:3px; }
    .file-list a {
      display:flex;
      align-items:center;
      gap:8px;
      padding:7px 8px;
      color:var(--text);
      text-decoration:none;
      border-radius:6px;
      min-width:0;
    }
    .file-list a:hover { background:var(--blue-soft); color:#1749b5; }
    .file-kind {
      width:36px;
      flex:0 0 36px;
      color:var(--muted);
      font-size:11px;
      text-transform:uppercase;
    }
    .file-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .health-list { display:grid; gap:10px; }
    .health-row {
      display:grid;
      grid-template-columns:190px 100px 1fr 120px;
      gap:12px;
      align-items:center;
      padding:12px 14px;
      border:1px solid var(--line);
      border-radius:8px;
      background:var(--surface);
      box-shadow:0 1px 2px rgba(15,23,42,.04);
    }
    .health-name { font-weight:700; }
    .health-message { color:var(--muted); min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .two-col { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
    .rag-layout { display:grid; grid-template-columns:minmax(320px,.78fr) 1.22fr; gap:14px; align-items:start; }
    .quick-list { display:grid; gap:8px; margin-top:12px; }
    .quick-btn { width:100%; text-align:left; border:1px solid var(--line); background:var(--surface-soft); border-radius:7px; padding:9px 10px; cursor:pointer; color:var(--text); }
    .quick-btn:hover { border-color:var(--blue); color:#1749b5; background:var(--blue-soft); }
    .answer-box { min-height:220px; white-space:pre-wrap; line-height:1.68; font-size:15px; }
    .answer-meta { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-bottom:12px; }
    .mini-stat { border:1px solid var(--line); border-radius:8px; padding:10px; background:var(--surface-soft); }
    .mini-label { color:var(--muted); font-size:12px; }
    .mini-value { font-size:18px; font-weight:740; margin-top:3px; }
    .citation-list { display:grid; gap:8px; }
    .citation { border:1px solid var(--line); border-radius:7px; padding:9px 10px; background:#fff; }
    .citation-title { font-weight:680; word-break:break-word; }
    .citation-sub { color:var(--muted); font-size:12px; margin-top:3px; }
    .task-list { display:grid; gap:10px; }
    .task-card { border:1px solid var(--line); background:var(--surface); border-radius:8px; padding:13px; box-shadow:0 1px 2px rgba(15,23,42,.04); }
    .task-top { display:flex; gap:10px; align-items:flex-start; justify-content:space-between; }
    .task-title { font-weight:720; line-height:1.45; }
    .task-meta { color:var(--muted); font-size:12px; margin-top:8px; display:flex; gap:10px; flex-wrap:wrap; }
    .audit-list { display:grid; gap:10px; }
    .audit-card { border:1px solid var(--line); background:#fff; border-radius:8px; padding:12px; box-shadow:0 1px 2px rgba(15,23,42,.04); }
    .audit-question { font-weight:700; margin-bottom:8px; }
    .audit-meta { display:flex; gap:8px; flex-wrap:wrap; color:var(--muted); font-size:12px; }
    .doc-text { max-height:680px; }
    .kv { display:grid; gap:8px; }
    .kv-row { display:grid; grid-template-columns:92px 1fr; gap:10px; padding:8px 0; border-bottom:1px solid var(--line); }
    .kv-row:last-child { border-bottom:0; }
    .kv-key { color:var(--muted); font-size:12px; }
    .kv-value { font-weight:620; word-break:break-word; }
    .stack { display:grid; gap:14px; }
    .empty { border:1px dashed var(--line-strong); border-radius:8px; padding:18px; color:var(--muted); background:var(--surface); }
    @media (max-width: 980px) {
      .shell { grid-template-columns:1fr; }
      aside { position:relative; height:auto; border-right:0; border-bottom:1px solid var(--line); }
      nav { display:flex; overflow:auto; padding-bottom:2px; }
      nav button { min-width:max-content; }
      .nav-key { display:none; }
      header { position:relative; }
      section { padding:18px; }
      .split, .two-col, .dashboard-grid, .pipeline, .rag-layout, .answer-meta, .docs-layout { grid-template-columns:1fr; }
      .state-band { grid-template-columns:1fr; }
      .node::after { display:none; }
      .health-row { grid-template-columns:1fr; gap:8px; }
      .section-head { align-items:flex-start; flex-direction:column; }
    }
  </style>
</head>
<body>
<div class="shell">
<aside>
  <div class="brand">
    <div class="brand-title">LLM Wiki Admin</div>
    <div class="brand-subtitle">企业知识库管理控制台</div>
  </div>
  <nav>
    <div class="nav-group">总览</div>
    <button class="active" data-tab="dashboard"><span>仪表盘</span><span class="nav-key">01</span></button>
    <button data-tab="health"><span>健康检查</span><span class="nav-key">02</span></button>
    <button data-tab="models"><span>模型配置</span><span class="nav-key">03</span></button>
    <button data-tab="domains"><span>领域注册表</span><span class="nav-key">04</span></button>
    <div class="nav-group">知识维护</div>
    <button data-tab="sync"><span>同步管理</span><span class="nav-key">05</span></button>
    <button data-tab="docs"><span>文档浏览</span><span class="nav-key">06</span></button>
    <button data-tab="schema"><span>Schema 模板</span><span class="nav-key">07</span></button>
    <div class="nav-group">问答质量</div>
    <button data-tab="rag"><span>RAG 测试</span><span class="nav-key">08</span></button>
    <button data-tab="gaps"><span>知识缺口</span><span class="nav-key">09</span></button>
    <button data-tab="audit"><span>审计日志</span><span class="nav-key">10</span></button>
    <div class="nav-group">工具</div>
    <button data-tab="obsidian"><span>obsidian-wiki</span><span class="nav-key">11</span></button>
  </nav>
</aside>
<div class="page">
<header>
  <div>
    <div class="header-title" id="pageTitle">仪表盘</div>
    <div class="header-meta" id="pageMeta">企业正式 Wiki 运行状态</div>
  </div>
  <div class="header-right">
    <span class="badge" id="globalHealth">未检查</span>
    <span class="muted" id="now"></span>
  </div>
</header>
<main>
<section id="dashboard" class="active">
  <div class="section-head">
    <div><h2>仪表盘</h2><div class="section-desc">系统是否可用、知识是否新鲜、是否有待处理缺口，集中看这里。</div></div>
    <div class="toolbar"><button class="action" onclick="loadHealth()">运行健康检查</button><button class="action primary" onclick="loadStatus()">刷新状态</button></div>
  </div>
  <div class="state-band" id="stateBand">
    <div>
      <div class="state-title"><span class="badge" id="stateBadge">未检查</span><span id="stateTitle">等待健康检查</span></div>
      <div class="state-desc" id="stateDesc">页面加载后会自动检查关键链路。</div>
    </div>
    <div class="toolbar"><button class="action" onclick="showTab('health')">查看健康矩阵</button><button class="action" onclick="showTab('rag')">测试问答</button></div>
  </div>
  <div id="statusCards" class="grid"></div>
  <div class="panel" style="margin-top:14px">
    <div class="panel-head"><strong>系统链路</strong><span class="muted">Postgres -> RAG -> LiteLLM -> Vault -> Sync</span></div>
    <div class="panel-body"><div class="pipeline" id="systemPipeline"></div></div>
  </div>
  <div class="dashboard-grid" style="margin-top:14px">
    <div class="panel">
      <div class="panel-head"><strong>知识状态</strong><span id="qualityBadge" class="badge">unknown</span></div>
      <div class="panel-body"><div class="list" id="knowledgeList"></div></div>
    </div>
    <div class="panel">
      <div class="panel-head"><strong>待处理</strong><span class="muted">优先看 open gaps</span></div>
      <div class="panel-body"><div class="list" id="workList"></div></div>
    </div>
  </div>
  <details class="raw"><summary>调试详情</summary><div class="two-col"><div class="panel"><div class="panel-head"><strong>同步状态</strong><span id="syncBadge" class="badge">unknown</span></div><div class="panel-body"><pre id="syncRaw">loading...</pre></div></div><div class="panel"><div class="panel-head"><strong>原始状态</strong><span class="muted">/api/status</span></div><div class="panel-body"><pre id="statusRaw">loading...</pre></div></div></div></details>
</section>
<section id="models">
  <div class="section-head">
    <div><h2>模型配置</h2><div class="section-desc">从 LiteLLM 读取可用模型，配置正式 Wiki/RAG 服务使用的 chat 和 rerank 模型。Hermes 自身模型不在这里管理。</div></div>
    <div class="toolbar"><button class="action" onclick="loadModelConfig()">刷新模型</button><button class="action primary" onclick="saveModelConfig()">保存配置</button></div>
  </div>
  <div class="grid" id="modelCards" style="margin-bottom:14px"></div>
  <div class="panel">
    <div class="panel-head"><strong>RAG 模型选择</strong><span id="modelSaveState" class="muted">未保存</span></div>
    <div class="panel-body">
      <div class="form-grid">
        <div class="field">
          <label for="chatModel">回答模型</label>
          <select id="chatModel"></select>
          <div class="field-help">用于 `/rag/answer` 生成最终五段式答案。</div>
        </div>
        <div class="field">
          <label for="rerankerModel">Rerank 模型</label>
          <select id="rerankerModel"></select>
          <div class="field-help">用于候选文档重排，影响命中顺序和可回答判定。</div>
        </div>
        <div class="field">
          <label for="embeddingModel">Embedding 模型</label>
          <select id="embeddingModel" disabled></select>
          <div class="field-help">当前只展示不开放保存；切换 embedding 需要重新嵌入全部文档。</div>
        </div>
      </div>
      <div class="notice" style="margin-top:14px">保存后会写入共享配置文件，新请求会立即读取；不需要修改 Hermes 配置，也不需要重建镜像。</div>
    </div>
  </div>
  <details class="raw"><summary>调试详情</summary><div class="panel"><div class="panel-body"><pre id="modelConfigRaw">等待加载...</pre></div></div></details>
</section>
<section id="domains">
  <div class="section-head">
    <div><h2>领域注册表</h2><div class="section-desc">统一记录不同知识领域的 profile、Vault 子路径、RAG 入口、同步状态和向量 collection。第一版只读展示，不改变当前问答路由。</div></div>
    <div class="toolbar"><button class="action primary" onclick="loadDomains()">刷新注册表</button></div>
  </div>
  <div id="domainCards" class="grid" style="margin-bottom:14px"></div>
  <div class="panel">
    <div class="panel-head"><strong>领域列表</strong><span id="domainRegistryPath" class="muted"></span></div>
    <div class="panel-body"><div id="domainList" class="task-list"></div></div>
  </div>
  <div class="panel" style="margin-top:14px">
    <div class="panel-head"><strong>校验结果</strong><span id="domainIssueCount" class="badge">等待</span></div>
    <div class="panel-body"><div id="domainIssues"></div></div>
  </div>
  <details class="raw"><summary>调试详情</summary><div class="panel"><div class="panel-body"><pre id="domainsRaw">等待加载...</pre></div></div></details>
</section>
<section id="sync">
  <div class="section-head">
    <div><h2>同步管理</h2><div class="section-desc">手动拉取 Vault 仓库并刷新 RAG 索引。</div></div>
    <div class="toolbar"><button class="action" onclick="runAction('/api/git-pull')">Git Pull</button><button class="action" onclick="runAction('/api/sync-index')">重新索引</button><button class="action primary" onclick="runAction('/api/full-sync')">Git Pull + 重新索引</button></div>
  </div>
  <div class="panel"><div class="panel-head"><strong>执行结果</strong><span class="muted">最长等待 900 秒</span></div><div class="panel-body"><pre id="actionLog">等待操作...</pre></div></div>
</section>
<section id="rag">
  <div class="section-head">
    <div><h2>RAG 测试</h2><div class="section-desc">直接调用正式 Wiki 问答接口，检查检索、rerank 和答案约束。</div></div>
  </div>
  <div class="rag-layout">
    <div class="stack">
      <div class="panel">
        <div class="panel-head"><strong>测试问题</strong><span class="muted">正式 Wiki 来源约束</span></div>
        <div class="panel-body">
          <textarea id="query" placeholder="输入要测试的问题，例如：FTLC4353RHPL对应我司哪个型号，使用场景是什么？"></textarea>
          <div class="toolbar" style="margin-top:10px"><button class="action primary" onclick="testRag()">测试 RAG</button></div>
          <div class="quick-list">
            <button class="quick-btn" onclick="setQuery('FTLC4353RHPL对应我司哪个型号，使用场景是什么？')">FTLC4353RHPL 对应型号和场景</button>
            <button class="quick-btn" onclick="setQuery('OSFP-QDD-CU3可以用于CX7 NIC互连吗？')">OSFP-QDD-CU3 与 CX7 NIC</button>
            <button class="quick-btn" onclick="setQuery('火星基地的咖啡机采购型号是什么？')">未命中保护测试</button>
          </div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-head"><strong>判定</strong><span id="ragBadge" class="badge">等待</span></div>
        <div class="panel-body"><div id="ragMeta" class="answer-meta"></div></div>
      </div>
    </div>
    <div class="stack">
      <div class="panel">
        <div class="panel-head"><strong>答案预览</strong><span class="muted">final_answer</span></div>
        <div class="panel-body"><div id="ragAnswer" class="answer-box muted">等待查询...</div></div>
      </div>
      <div class="panel">
        <div class="panel-head"><strong>引用来源</strong><span id="citationCount" class="muted">0</span></div>
        <div class="panel-body"><div id="ragCitations" class="citation-list"></div></div>
      </div>
      <details class="raw"><summary>调试详情</summary><div class="panel"><div class="panel-body"><pre id="ragResult">等待查询...</pre></div></div></details>
    </div>
  </div>
</section>
<section id="docs">
  <div class="section-head">
    <div><h2>文档浏览</h2><div class="section-desc">只读浏览远端 Vault 中的 Markdown 文件。</div></div>
  </div>
  <div class="docs-layout">
    <div class="panel"><div class="panel-head"><strong>Vault 文件</strong><button class="action" onclick="loadFiles('.')">根目录</button></div><div class="panel-body"><div id="files" class="file-list">loading...</div></div></div>
    <div class="panel"><div class="panel-head"><strong id="docTitle">选择 Markdown 文件预览</strong><span id="docPath" class="muted"></span></div><div class="panel-body"><pre id="docPreview" class="doc-text"></pre></div></div>
    <div class="panel"><div class="panel-head"><strong>Frontmatter</strong><span id="docStatus" class="badge">等待</span></div><div class="panel-body"><div id="docMeta" class="kv"><div class="empty">选择文档后显示元数据</div></div></div></div>
  </div>
</section>
<section id="gaps">
  <div class="section-head">
    <div><h2>知识缺口</h2><div class="section-desc">正式 Wiki 无法回答的问题会记录在这里，后续用于补充 Markdown。</div></div>
    <div class="toolbar"><button class="action primary" onclick="loadGaps()">刷新</button></div>
  </div>
  <div id="gapsSummary" class="grid" style="margin-bottom:14px"></div>
  <div id="gapsTable"></div>
</section>
<section id="audit">
  <div class="section-head">
    <div><h2>审计日志</h2><div class="section-desc">查看最近问答请求、可回答性和引用来源。</div></div>
    <div class="toolbar"><button class="action primary" onclick="loadAudit()">刷新</button></div>
  </div>
  <div id="auditSummary" class="grid" style="margin-bottom:14px"></div>
  <div id="auditTable"></div>
</section>
<section id="health">
  <div class="section-head">
    <div><h2>健康检查</h2><div class="section-desc">聚合检查 Postgres、RAG、LiteLLM、Vault Git、同步器、Wiki 质量和 obsidian-wiki。</div></div>
    <div class="toolbar"><button class="action primary" onclick="loadHealth()">运行健康检查</button></div>
  </div>
  <div id="healthSummary" class="grid"></div>
  <div class="panel" style="margin-top:14px"><div class="panel-head"><strong>检查项</strong><span id="healthCheckedAt" class="muted"></span></div><div class="panel-body"><div id="healthRows" class="health-list"></div></div></div>
  <details class="raw"><summary>调试详情</summary><div class="panel"><div class="panel-head"><strong>原始详情</strong><span class="muted">/api/health-detail</span></div><div class="panel-body"><pre id="healthResult">等待检查...</pre></div></div></details>
</section>
<section id="schema">
  <div class="section-head">
    <div><h2>Schema 模板</h2><div class="section-desc">查看当前 Wiki frontmatter 规范和模板。</div></div>
    <div class="toolbar"><button class="action primary" onclick="loadSchema()">刷新模板</button></div>
  </div>
  <div class="panel"><div class="panel-body"><pre id="schemaTemplate">等待加载...</pre></div></div>
</section>
<section id="obsidian">
  <div class="section-head">
    <div><h2>obsidian-wiki</h2><div class="section-desc">检查容器内 obsidian-wiki 安装状态和 Vault 配置。</div></div>
    <div class="toolbar"><button class="action primary" onclick="loadObsidianWiki()">检测 obsidian-wiki</button></div>
  </div>
  <div class="panel"><div class="panel-body"><pre id="obsidianInfo">等待检测...</pre></div></div>
</section>
</main>
</div>
</div>
<script>
const $ = (id) => document.getElementById(id);
const pageInfo = {
  dashboard:['仪表盘','企业正式 Wiki 运行状态'],
  models:['模型配置','LiteLLM 可用模型与 RAG 运行模型'],
  domains:['领域注册表','多领域知识库的管理侧注册表'],
  sync:['同步管理','Git 同步和索引刷新'],
  rag:['RAG 测试','正式 Wiki 问答链路验证'],
  docs:['文档浏览','远端 Vault Markdown 只读浏览'],
  gaps:['知识缺口','未命中问题和补充线索'],
  audit:['审计日志','最近问答请求和来源记录'],
  health:['健康检查','系统依赖与知识质量检查'],
  schema:['Schema 模板','frontmatter 规范'],
  obsidian:['obsidian-wiki','维护工具状态']
};
function showTab(id){
  document.querySelectorAll('section').forEach(s=>s.classList.remove('active'));
  $(id).classList.add('active');
  document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active', b.dataset.tab===id));
  $('pageTitle').textContent=pageInfo[id]?.[0]||id;
  $('pageMeta').textContent=pageInfo[id]?.[1]||'';
  if(id === 'models') loadModelConfig();
  if(id === 'domains') loadDomains();
}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
function pretty(x){ return JSON.stringify(x,null,2); }
async function getJson(url, opts={}){ const r=await fetch(url, opts); const t=await r.text(); try{ const j=JSON.parse(t); if(!r.ok) throw j; return j; }catch(e){ if(!r.ok) throw new Error(t); return t; } }
function escapeHtml(s){ return String(s).replace(/[&<>"']/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function q(s){ return String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'"); }
function badge(status, text){
  const cls = status==='ok'?'ok':(status==='warning'||status==='warn'?'warn':(status==='failed'||status==='bad'?'bad':''));
  return `<span class="badge ${cls}">${escapeHtml(text ?? status ?? 'unknown')}</span>`;
}
function card(label,value,meta='',state=''){
  const cls = state==='ok'?'ok':(state==='warning'?'warn':(state==='failed'?'bad':''));
  return `<div class="card"><div class="metric-label">${escapeHtml(label)}</div><div class="metric ${cls}">${escapeHtml(value ?? '-')}</div><div class="metric-sub">${escapeHtml(meta || '')}</div></div>`;
}
function listRow(title, sub, right='', state=''){
  return `<div class="list-row"><div><div class="list-title">${escapeHtml(title)}</div><div class="list-sub">${escapeHtml(sub || '')}</div></div><div>${right ? badge(state || 'ok', right) : ''}</div></div>`;
}
function table(rows, cols){
  if(!rows.length) return '<div class="empty">暂无数据</div>';
  return '<table><thead><tr>'+cols.map(c=>`<th>${c[1]}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(c=>`<td>${escapeHtml(String(r[c[0]] ?? ''))}</td>`).join('')+'</tr>').join('')+'</tbody></table>';
}
function setQuery(text){ $('query').value = text; }
function mini(label, value, state=''){
  const cls = state==='ok'?'ok':(state==='warning'?'warn':(state==='failed'?'bad':''));
  return `<div class="mini-stat"><div class="mini-label">${escapeHtml(label)}</div><div class="mini-value ${cls}">${escapeHtml(value ?? '-')}</div></div>`;
}
function citationTotal(value){
  try {
    const parsed = typeof value === 'string' ? JSON.parse(value) : value;
    return Array.isArray(parsed) ? parsed.length : 0;
  } catch(e) {
    return 0;
  }
}
function parseFrontmatter(text){
  if(!text.startsWith('---')) return { meta:null, body:text };
  const end = text.indexOf('\n---', 3);
  if(end < 0) return { meta:null, body:text };
  const raw = text.slice(3, end).trim();
  const body = text.slice(text.indexOf('\n', end + 4) + 1);
  const meta = {};
  let currentKey = null;
  for(const line of raw.split('\n')){
    if(!line.trim()) continue;
    const m = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if(m){
      currentKey = m[1];
      let value = m[2].trim();
      value = value.replace(/^['"]|['"]$/g,'');
      meta[currentKey] = value || '';
    } else if(currentKey && line.trim().startsWith('- ')){
      const value = line.trim().slice(2).replace(/^['"]|['"]$/g,'');
      if(!Array.isArray(meta[currentKey])) meta[currentKey] = meta[currentKey] ? [meta[currentKey]] : [];
      meta[currentKey].push(value);
    }
  }
  return { meta, body };
}
function renderMeta(meta){
  if(!meta) return '<div class="empty">未检测到 frontmatter</div>';
  const preferred = ['title','type','status','owner','updated','tags','sku','aliases','summary'];
  const keys = [...preferred.filter(k => k in meta), ...Object.keys(meta).filter(k => !preferred.includes(k))];
  return keys.map(k => {
    const value = Array.isArray(meta[k]) ? meta[k].join(', ') : meta[k];
    return `<div class="kv-row"><div class="kv-key">${escapeHtml(k)}</div><div class="kv-value">${escapeHtml(value || '-')}</div></div>`;
  }).join('') || '<div class="empty">frontmatter 为空</div>';
}
function updateGlobal(status){
  const text = status==='ok'?'系统正常':(status==='warning'?'存在警告':(status==='failed'?'存在异常':'未检查'));
  $('globalHealth').outerHTML = `<span class="badge ${status==='ok'?'ok':(status==='warning'?'warn':(status==='failed'?'bad':''))}" id="globalHealth">${text}</span>`;
}
function updateStateBand(summary){
  const status = summary?.overall || 'unknown';
  const text = status==='ok'?'系统链路正常':(status==='warning'?'系统存在警告':(status==='failed'?'系统存在异常':'等待健康检查'));
  const desc = status==='ok'
    ? `全部 ${summary.checks ?? '-'} 个检查项通过，最近检查时间 ${summary.checked_at || '-'}`
    : `异常 ${summary.failed ?? 0} 项，警告 ${summary.warnings ?? 0} 项`;
  $('stateBadge').outerHTML = badge(status, status).replace('<span','<span id="stateBadge"');
  $('stateTitle').textContent = text;
  $('stateDesc').textContent = desc;
}
function checkByName(data, name){
  return (data?.checks || []).find(item => item.name === name) || {};
}
function renderPipeline(data){
  const specs = [
    ['postgres','Postgres'],
    ['rag_api','RAG API'],
    ['litellm_models','LiteLLM'],
    ['vault_git','Vault Git'],
    ['sync_status','Sync']
  ];
  $('systemPipeline').innerHTML = specs.map(([key,label]) => {
    const item = checkByName(data, key);
    const status = item.status || 'unknown';
    return `<div class="node"><div class="node-name">${escapeHtml(label)}</div><div>${badge(status, status)}</div><div class="node-msg">${escapeHtml(item.message || '等待检查')}</div></div>`;
  }).join('');
}
function renderDashboardHealth(data){
  const summary = data.summary || {};
  updateGlobal(summary.overall || 'unknown');
  updateStateBand(summary);
  renderPipeline(data);
  const wiki = checkByName(data, 'wiki_quality');
  const db = checkByName(data, 'postgres');
  const sync = checkByName(data, 'sync_status');
  const counts = db.details || {};
  const wikiSummary = wiki.details?.summary || {};
  $('qualityBadge').outerHTML = badge(wiki.status || 'unknown', wiki.status || 'unknown').replace('<span','<span id="qualityBadge"');
  $('knowledgeList').innerHTML = [
    listRow('文档规模', `documents=${counts.documents ?? '-'}, chunks=${counts.chunks ?? '-'}`, 'indexed', 'ok'),
    listRow('Wiki 质量', `errors=${wikiSummary.errors ?? '-'}, warnings=${wikiSummary.warnings ?? '-'}`, wiki.status || 'unknown', wiki.status),
    listRow('Vault Git', checkByName(data,'vault_git').message || '-', checkByName(data,'vault_git').status || 'unknown', checkByName(data,'vault_git').status),
    listRow('最近同步', sync.message || '-', sync.status || 'unknown', sync.status)
  ].join('');
}
async function loadStatus(){
  const data=await getJson('/api/status');
  $('statusRaw').textContent=pretty(data);
  const counts=data.counts||{};
  const sync=data.sync_status||{};
  const ragOk=!!data.rag_health?.ok;
  $('statusCards').innerHTML=[
    card('文档', counts.documents, 'documents'),
    card('Chunks', counts.chunks, 'indexed content'),
    card('索引文件', counts.indexed_files, 'indexed_files'),
    card('Open 缺口', counts.knowledge_gaps_open, 'knowledge_gaps'),
    card('审计记录', counts.audit_logs, 'audit_logs'),
    card('RAG API', ragOk?'OK':'FAIL', data.rag_health?.db?'db connected':'', ragOk?'ok':'failed'),
    card('同步', sync.status || '-', sync.ended_at || sync.started_at || '', sync.status==='success'?'ok':(sync.status==='failed'?'failed':'warning'))
  ].join('');
  $('syncRaw').textContent=pretty(sync);
  $('syncBadge').outerHTML=badge(sync.status==='success'?'ok':(sync.status==='failed'?'failed':'warning'), sync.status || 'unknown').replace('<span','<span id="syncBadge"');
  $('workList').innerHTML = [
    listRow('Open 知识缺口', `${counts.knowledge_gaps_open ?? 0} 条待补充`, counts.knowledge_gaps_open > 0 ? '处理' : '清零', counts.knowledge_gaps_open > 0 ? 'warning' : 'ok'),
    listRow('最近索引', data.latest_index?.path || '暂无索引记录', data.latest_index?.status || '-', data.latest_index?.status === 'indexed' ? 'ok' : '检查', data.latest_index?.status === 'indexed' ? 'ok' : 'warning'),
    listRow('Git 工作区', (data.git_status?.stdout || '').trim() ? '存在未提交改动' : '工作区干净', (data.git_status?.stdout || '').trim() ? '检查' : 'ok', (data.git_status?.stdout || '').trim() ? 'warning' : 'ok')
  ].join('');
}
function renderOptions(selectId, models, selected, fallback){
  const select = $(selectId);
  const values = [...new Set([selected, fallback, ...models].filter(Boolean))];
  select.innerHTML = values.map(model => `<option value="${escapeHtml(model)}" ${model===selected?'selected':''}>${escapeHtml(model)}</option>`).join('');
}
function classifyModels(models, kind){
  const items = models || [];
  if(kind === 'reranker') return items.filter(model => /rerank|reranker/i.test(model));
  if(kind === 'embedding') return items.filter(model => /embed|embedding/i.test(model));
  return items.filter(model => !/rerank|reranker|embed|embedding/i.test(model));
}
async function loadModelConfig(){
  const data = await getJson('/api/model-config');
  $('modelConfigRaw').textContent = pretty(data);
  const models = data.available_models || [];
  const effective = data.effective || {};
  const defaults = data.defaults || {};
  renderOptions('chatModel', classifyModels(models, 'chat'), effective.chat_model, defaults.chat_model);
  renderOptions('rerankerModel', classifyModels(models, 'reranker'), effective.reranker_model, defaults.reranker_model);
  renderOptions('embeddingModel', classifyModels(models, 'embedding'), effective.embedding_model, defaults.embedding_model);
  $('modelCards').innerHTML = [
    card('LiteLLM 模型', models.length, 'available models', models.length ? 'ok' : 'warning'),
    card('回答模型', effective.chat_model || '-', 'chat_model'),
    card('Rerank 模型', effective.reranker_model || '-', 'reranker_model'),
    card('Embedding', effective.embedding_model || '-', '只展示，切换需重建索引')
  ].join('');
  $('modelSaveState').textContent = data.settings_path || '';
}
async function saveModelConfig(){
  $('modelSaveState').textContent = '保存中...';
  try {
    const data = await getJson('/api/model-config', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        chat_model:$('chatModel').value,
        reranker_model:$('rerankerModel').value
      })
    });
    $('modelSaveState').textContent = '已保存';
    $('modelConfigRaw').textContent = pretty(data);
    await loadModelConfig();
  } catch(e) {
    $('modelSaveState').textContent = '保存失败';
    $('modelConfigRaw').textContent = String(e.stack || e);
  }
}
async function loadDomains(){
  const data = await getJson('/api/domains');
  $('domainsRaw').textContent = pretty(data);
  const summary = data.summary || {};
  $('domainRegistryPath').textContent = data.registry_path || '';
  $('domainCards').innerHTML = [
    card('领域数', summary.domains ?? 0, 'domains'),
    card('启用领域', summary.enabled ?? 0, 'enabled', summary.enabled > 0 ? 'ok' : 'warning'),
    card('已隔离', summary.isolated ?? 0, 'domain_subpath'),
    card('根目录兼容', summary.legacy_root ?? 0, 'legacy_root'),
    card('默认领域', data.default_domain || '-', 'default_domain'),
    card('配置来源', data.source || '-', data.registry_path || '')
  ].join('');
  const domains = data.domains || {};
  const entries = Object.entries(domains);
  $('domainList').innerHTML = entries.length ? entries.map(([id, cfg]) => {
    const enabled = !!cfg.enabled;
    const collection = cfg.vector_collection || cfg.milvus_collection || '-';
    const vault = cfg.vault_status || {};
    const target = cfg.target_vault_status || {};
    const isolation = cfg.isolation_mode || '-';
    const targetText = cfg.target_vault_subpath ? `${cfg.target_vault_subpath} (${target.exists ? 'exists' : 'not ready'})` : '-';
    return `<div class="task-card">
      <div class="task-top"><div><div class="task-title">${escapeHtml(cfg.display_name || id)}</div><div class="list-sub">${escapeHtml(id)} · profile=${escapeHtml(cfg.profile || '-')} · isolation=${escapeHtml(isolation)}</div></div>${badge(enabled ? 'ok' : 'warning', enabled ? 'enabled' : 'disabled')}</div>
      <div class="task-meta">
        <span>vault=${escapeHtml(cfg.vault_subpath || '-')} (${vault.exists ? 'exists' : 'missing'})</span>
        <span>target=${escapeHtml(targetText)}</span>
        <span>md=${escapeHtml(vault.markdown_files ?? '-')}</span>
        <span>indexed=${escapeHtml(vault.indexed_files ?? '-')}</span>
        <span>rag=${escapeHtml(cfg.rag_base_url || '-')}</span>
        <span>sync=${escapeHtml(cfg.sync_status_file || '-')}</span>
        <span>vector=${escapeHtml(cfg.vector_backend || '-')} / ${escapeHtml(collection)}</span>
        <span>entry=${escapeHtml(cfg.entrypoint || '-')}</span>
      </div>
      ${cfg.description ? `<div class="list-sub" style="margin-top:8px">${escapeHtml(cfg.description)}</div>` : ''}
    </div>`;
  }).join('') : '<div class="empty">未定义领域</div>';
  const issues = data.issues || [];
  $('domainIssueCount').outerHTML = badge(issues.length ? (summary.errors ? 'failed' : 'warning') : 'ok', `${issues.length} 项`).replace('<span','<span id="domainIssueCount"');
  $('domainIssues').innerHTML = issues.length ? `<div class="task-list">${issues.map(item=>`<div class="task-card"><div class="task-top"><div class="task-title">${escapeHtml(item.domain || '-')} · ${escapeHtml(item.code || '-')}</div>${badge(item.severity === 'error' ? 'failed' : 'warning', item.severity || '-')}</div><div class="task-meta"><span>${escapeHtml(item.message || '')}</span></div></div>`).join('')}</div>` : '<div class="empty">领域注册表校验通过</div>';
}
async function runAction(url){
  $('actionLog').textContent='running...';
  try{ const data=await getJson(url,{method:'POST'}); $('actionLog').textContent=pretty(data); loadStatus(); }
  catch(e){ $('actionLog').textContent=String(e.stack||e); }
}
async function testRag(){
  const query=$('query').value.trim();
  if(!query){ $('ragResult').textContent='请输入问题'; return; }
  $('ragAnswer').textContent='查询中...';
  $('ragAnswer').className='answer-box muted';
  $('ragResult').textContent='querying...';
  $('ragCitations').innerHTML='';
  $('citationCount').textContent='0';
  $('ragMeta').innerHTML='';
  try{
    const data=await getJson('/api/rag-test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query})});
    $('ragResult').textContent=pretty(data);
    const answerable = !!data.answerable;
    const status = answerable ? 'ok' : 'failed';
    $('ragBadge').outerHTML = badge(status, answerable ? '可回答' : '不可回答').replace('<span','<span id="ragBadge"');
    $('ragMeta').innerHTML = [
      mini('answerable', answerable ? 'true' : 'false', status),
      mini('confidence', data.confidence ?? '-', answerable ? 'ok' : 'failed'),
      mini('reason', data.reason || '-', answerable ? 'ok' : 'failed')
    ].join('');
    $('ragAnswer').className = 'answer-box';
    $('ragAnswer').textContent = data.final_answer || '无 final_answer';
    const citations = data.citations || [];
    $('citationCount').textContent = `${citations.length} 条`;
    $('ragCitations').innerHTML = citations.length ? citations.map((c,i)=>`<div class="citation"><div class="citation-title">[${i+1}] ${escapeHtml(c.path || '-')}</div><div class="citation-sub">${escapeHtml(c.heading || '')} · score=${escapeHtml(c.score ?? '-')}</div></div>`).join('') : '<div class="empty">无可靠来源</div>';
  }
  catch(e){
    $('ragBadge').outerHTML = badge('failed','失败').replace('<span','<span id="ragBadge"');
    $('ragAnswer').className='answer-box bad';
    $('ragAnswer').textContent=String(e.stack||e);
    $('ragResult').textContent=String(e.stack||e);
  }
}
async function loadFiles(path='.'){
  const data=await getJson('/api/files?path='+encodeURIComponent(path));
  let h='';
  if(data.parent!==null) h+=`<a href="#" onclick="loadFiles('${q(data.parent)}');return false;"><span class="file-kind">UP</span><span class="file-name">..</span></a>`;
  h += data.entries.map(e=>`<a href="#" onclick="${e.type==='dir'?`loadFiles('${q(e.path)}')`:`previewFile('${q(e.path)}')`};return false;"><span class="file-kind">${e.type==='dir'?'DIR':'MD'}</span><span class="file-name">${escapeHtml(e.name)}</span></a>`).join('');
  $('files').innerHTML=h||'<div class="empty">空目录</div>';
}
async function previewFile(path){
  const data=await getJson('/api/file?path='+encodeURIComponent(path));
  const parsed = parseFrontmatter(data.content || '');
  $('docTitle').textContent=(parsed.meta && parsed.meta.title) ? parsed.meta.title : data.path.split('/').pop();
  $('docPath').textContent=data.path;
  $('docPreview').textContent=parsed.body || data.content;
  $('docMeta').innerHTML=renderMeta(parsed.meta);
  const status = parsed.meta?.status || (parsed.meta ? 'metadata' : 'missing');
  $('docStatus').outerHTML = badge(status === 'active' ? 'ok' : (status === 'missing' ? 'warning' : 'warning'), status).replace('<span','<span id="docStatus"');
}
async function loadGaps(){
  const rows=await getJson('/api/gaps');
  const open = rows.filter(r => r.status === 'open').length;
  const totalFreq = rows.reduce((sum,r)=>sum + Number(r.frequency || 0), 0);
  $('gapsSummary').innerHTML=[
    card('Open 缺口', open, 'status=open', open ? 'warning' : 'ok'),
    card('记录数', rows.length, '最近 100 条'),
    card('累计出现', totalFreq, 'frequency sum')
  ].join('');
  $('gapsTable').innerHTML=rows.length ? `<div class="task-list">${rows.map(r=>`<div class="task-card"><div class="task-top"><div class="task-title">${escapeHtml(r.query || '-')}</div>${badge(r.status==='open'?'warning':'ok', r.status || '-')}</div><div class="task-meta"><span>最近：${escapeHtml(r.last_seen_at || '-')}</span><span>次数：${escapeHtml(r.frequency ?? '-')}</span><span>建议：${escapeHtml(r.suggested_title || '-')}</span></div></div>`).join('')}</div>` : '<div class="empty">暂无知识缺口</div>';
}
async function loadAudit(){
  const rows=await getJson('/api/audit');
  const answerable = rows.filter(r => String(r.answerable) === 'true').length;
  const blocked = rows.length - answerable;
  $('auditSummary').innerHTML=[
    card('审计记录', rows.length, '最近 100 条'),
    card('可回答', answerable, 'answerable=true', 'ok'),
    card('不可回答', blocked, 'source constrained', blocked ? 'warning' : 'ok')
  ].join('');
  $('auditTable').innerHTML=rows.length ? `<div class="audit-list">${rows.map(r=>`<div class="audit-card"><div class="audit-question">${escapeHtml(r.query || '-')}</div><div class="audit-meta">${badge(String(r.answerable)==='true'?'ok':'failed', String(r.answerable)==='true'?'可回答':'不可回答')}<span>confidence=${escapeHtml(r.confidence ?? '-')}</span><span>${escapeHtml(r.created_at || '-')}</span><span>citations=${citationTotal(r.citations)}</span></div></div>`).join('')}</div>` : '<div class="empty">暂无审计记录</div>';
}
async function loadHealth(){
  const data=await getJson('/api/health-detail');
  const s=data.summary||{};
  updateGlobal(s.overall || 'unknown');
  updateStateBand(s);
  renderPipeline(data);
  renderDashboardHealth(data);
  $('healthResult').textContent=pretty(data);
  $('healthCheckedAt').textContent=s.checked_at || '';
  $('healthSummary').innerHTML=[
    card('总体', s.overall || '-', 'overall', s.overall),
    card('检查项', s.checks, 'checks'),
    card('正常', s.ok, 'ok', 'ok'),
    card('异常', s.failed, 'failed', s.failed>0?'failed':''),
    card('警告', s.warnings, 'warnings', s.warnings>0?'warning':'')
  ].join('');
  const rows=(data.checks||[]).map(item=>`<div class="health-row"><div><div class="health-name">${escapeHtml(item.name)}</div></div><div>${badge(item.status,item.status)}</div><div class="health-message" title="${escapeHtml(item.message||'')}">${escapeHtml(item.message||'')}</div></div>`).join('');
  $('healthRows').innerHTML=rows||'<div class="empty">暂无检查结果</div>';
}
async function loadSchema(){ const data=await getJson('/api/schema-template'); $('schemaTemplate').textContent=data.content || pretty(data); }
async function loadObsidianWiki(){ const data=await getJson('/api/obsidian-wiki'); $('obsidianInfo').textContent=pretty(data); }
$('now').textContent=new Date().toLocaleString();
loadStatus();
loadHealth();
loadFiles('.');
</script>
</body>
</html>'''


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML_PAGE


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    counts = _fetch_one("""
        select
          (select count(*) from documents) as documents,
          (select count(*) from chunks) as chunks,
          (select count(*) from indexed_files) as indexed_files,
          (select count(*) from knowledge_gaps where status='open') as knowledge_gaps_open,
          (select count(*) from audit_logs) as audit_logs
    """)
    latest_index = _fetch_one("select path, status, indexed_at, error from indexed_files order by indexed_at desc limit 1")
    latest_quality = _fetch_one("select created_at, summary, issues from quality_reports order by created_at desc limit 1")
    git_head = _run(["git", "log", "-1", "--oneline", "--decorate"], cwd=VAULT_PATH, timeout=10)
    git_status = _run(["git", "status", "--short"], cwd=VAULT_PATH, timeout=10)
    services = {
        name: _run(["systemctl", "is-active", name], timeout=5)["stdout"].strip()
        for name in ["obsidian-rag-mcp.service", "obsidian-rag-mcp-bridge.service", "llm-wiki-sync.timer"]
    }
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            rag_health = (await client.get(f"{RAG_BASE_URL}/health")).json()
    except Exception as exc:
        rag_health = {"ok": False, "error": str(exc)}
    return _jsonable({"vault_path": str(VAULT_PATH), "project_root": str(PROJECT_ROOT), "counts": counts, "latest_index": latest_index, "latest_quality": latest_quality, "git_head": git_head, "git_status": git_status, "services": services, "rag_health": rag_health, "sync_status": _read_sync_status()})


@app.get("/api/model-config")
async def model_config() -> dict[str, Any]:
    try:
        available_models = await _list_litellm_models()
        litellm_error = None
    except Exception as exc:
        available_models = []
        litellm_error = str(exc)
    return {
        "settings_path": str(MODEL_SETTINGS_PATH),
        "defaults": _model_defaults(),
        "saved": _read_model_settings(),
        "effective": _effective_model_settings(),
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
        available_models = await _list_litellm_models()
    except Exception:
        available_models = []

    if available_models:
        invalid = [model for model in (chat_model, reranker_model) if model not in available_models]
        if invalid:
            raise HTTPException(status_code=400, detail=f"model is not available from LiteLLM: {', '.join(invalid)}")

    saved = _write_model_settings({"chat_model": chat_model, "reranker_model": reranker_model})
    return {
        "ok": True,
        "settings_path": str(MODEL_SETTINGS_PATH),
        "saved": saved,
        "effective": _effective_model_settings(),
        "available_models": available_models,
    }


@app.get("/api/domains")
def domains() -> dict[str, Any]:
    return _domain_registry_status()


@app.get("/api/sync-status")
def sync_status() -> dict[str, Any]:
    return _jsonable(_read_sync_status())


@app.post("/api/git-pull")
def git_pull() -> dict[str, Any]:
    return _run(["git", "pull", "--ff-only"], cwd=VAULT_PATH, timeout=180)


@app.post("/api/sync-index")
async def sync_index() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
        response = await client.post(f"{RAG_BASE_URL}/admin/sync/run")
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
    return {"ok": response.status_code < 400, "status_code": response.status_code, "body": body}


@app.post("/api/full-sync")
def full_sync() -> dict[str, Any]:
    if not SYNC_SCRIPT.exists():
        raise HTTPException(status_code=500, detail=f"sync script not found: {SYNC_SCRIPT}")
    return _run([str(SYNC_SCRIPT)], timeout=900)


@app.post("/api/rag-test")
async def rag_test(request: QueryRequest) -> dict[str, Any]:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        response = await client.post(f"{RAG_BASE_URL}/rag/answer", json={"query": request.query.strip()})
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


@app.get("/api/files")
def files(path: str = Query(".")) -> dict[str, Any]:
    target = _safe_rel_path(path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name.startswith(".git"):
            continue
        if child.is_dir() or child.suffix.lower() == ".md":
            entries.append({"name": child.name, "path": child.relative_to(VAULT_PATH).as_posix(), "type": "dir" if child.is_dir() else "file"})
    rel = target.relative_to(VAULT_PATH).as_posix() if target != VAULT_PATH else "."
    parent = None if target == VAULT_PATH else target.parent.relative_to(VAULT_PATH).as_posix()
    return {"path": rel, "parent": parent, "entries": entries}


@app.get("/api/file")
def file_preview(path: str) -> dict[str, Any]:
    target = _safe_rel_path(path)
    if not target.exists() or not target.is_file() or target.suffix.lower() != ".md":
        raise HTTPException(status_code=404, detail="markdown file not found")
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"path": target.relative_to(VAULT_PATH).as_posix(), "content": content[:100000]}


@app.get("/api/gaps")
def gaps() -> list[dict[str, Any]]:
    rows = _fetch_all("""
        select last_seen_at, frequency, status, query, suggested_title
        from knowledge_gaps
        order by last_seen_at desc
        limit 100
    """)
    return _jsonable(rows)


@app.get("/api/audit")
def audit() -> list[dict[str, Any]]:
    rows = _fetch_all("""
        select created_at, answerable, round(confidence::numeric, 4) as confidence, query, citations
        from audit_logs
        order by created_at desc
        limit 100
    """)
    for row in rows:
        row["citations"] = json.dumps(row.get("citations") or [], ensure_ascii=False)
    return _jsonable(rows)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data, raw[match.end():]


def _wiki_page_candidates() -> dict[str, Path]:
    pages: dict[str, Path] = {}
    for file_path in VAULT_PATH.rglob("*.md"):
        rel = file_path.relative_to(VAULT_PATH).as_posix()
        pages[rel[:-3]] = file_path
        pages[file_path.stem] = file_path
    return pages


def _wiki_knowledge_roots() -> list[Path]:
    registry = _read_domain_registry()
    roots: list[Path] = []
    for config in (registry.get("domains") or {}).values():
        if not isinstance(config, dict) or not bool(config.get("enabled")):
            continue
        subpath = str(config.get("vault_subpath") or ".")
        status = _domain_path_status(subpath)
        if not status.get("safe"):
            continue
        base = (VAULT_PATH / subpath).resolve()
        knowledge_root = base / "10_Knowledge"
        if knowledge_root.exists():
            roots.append(knowledge_root)
    if not roots and (VAULT_PATH / "10_Knowledge").exists():
        roots.append(VAULT_PATH / "10_Knowledge")
    return roots


def _expected_domain_for_path(relative_path: str) -> str | None:
    registry = _read_domain_registry()
    best_domain: str | None = None
    best_len = -1
    path = relative_path.replace("\\", "/")
    for domain_id, config in (registry.get("domains") or {}).items():
        if not isinstance(config, dict) or not bool(config.get("enabled")):
            continue
        subpath = str(config.get("vault_subpath") or ".").strip("/")
        if not subpath or subpath == ".":
            match = True
            match_len = 0
        else:
            match = path == subpath or path.startswith(subpath + "/")
            match_len = len(subpath)
        if match and match_len > best_len:
            best_domain = str(domain_id)
            best_len = match_len
    return best_domain


def _check_updated(value: Any) -> tuple[str, str | None]:
    if not value:
        return "warning", "missing updated"
    text = str(value)
    try:
        dt = datetime.fromisoformat(text[:10]).replace(tzinfo=timezone.utc)
    except Exception:
        return "warning", f"invalid updated: {text}"
    age_days = (datetime.now(timezone.utc) - dt).days
    if age_days > 180:
        return "warning", f"updated is stale: {age_days} days"
    return "ok", None


@app.get("/api/wiki-health")
def wiki_health() -> dict[str, Any]:
    knowledge_roots = _wiki_knowledge_roots()
    docs: list[Path] = []
    for root in knowledge_roots:
        docs.extend(root.rglob("*.md"))
    docs = sorted(docs)
    indexed_rows = _fetch_all("select path, status, error from indexed_files")
    indexed = {row["path"]: row for row in indexed_rows}
    pages = _wiki_page_candidates()
    issues: list[dict[str, Any]] = []
    sku_seen: dict[str, str] = {}

    def add(path: str, severity: str, code: str, message: str) -> None:
        issues.append({"path": path, "severity": severity, "code": code, "message": message})

    for file_path in docs:
        rel = file_path.relative_to(VAULT_PATH).as_posix()
        raw = file_path.read_text(encoding="utf-8", errors="replace")
        fm, body = _parse_frontmatter(raw)
        if not fm:
            add(rel, "warning", "missing_frontmatter", "缺少 YAML frontmatter，RAG 只能依赖正文和标题。")
        else:
            for key in REQUIRED_FRONTMATTER:
                if key not in fm or fm.get(key) in (None, ""):
                    add(rel, "warning", "missing_required_field", f"缺少字段: {key}")
            status = str(fm.get("status") or "").lower()
            if status and status not in VALID_STATUS:
                add(rel, "error", "invalid_status", f"status 不合法: {status}")
            expected_domain = _expected_domain_for_path(rel)
            actual_domain = str(fm.get("domain") or "").strip()
            if expected_domain and actual_domain and actual_domain != expected_domain:
                add(rel, "error", "domain_mismatch", f"domain={actual_domain} 与路径所属领域 {expected_domain} 不一致")
            state, msg = _check_updated(fm.get("updated"))
            if msg:
                add(rel, state, "updated_check", msg)
            for key in SKU_KEYS:
                for value in _as_list(fm.get(key)):
                    norm = re.sub(r"[^a-z0-9]+", "", value.lower())
                    if not norm:
                        continue
                    if norm in sku_seen and sku_seen[norm] != rel:
                        add(rel, "error", "duplicate_sku_alias", f"{key}={value} 与 {sku_seen[norm]} 重复")
                    else:
                        sku_seen[norm] = rel
        for link in WIKILINK_RE.findall(body):
            clean = link.strip()
            if clean and clean not in pages:
                add(rel, "warning", "broken_wikilink", f"断链: [[{clean}]]")
        row = indexed.get(rel)
        if not row:
            add(rel, "warning", "not_indexed", "该文件未出现在 indexed_files 中。")
        elif row.get("status") != "indexed":
            add(rel, "error", "index_status", f"索引状态: {row.get('status')} {row.get('error') or ''}")

    summary = {
        "files": len(docs),
        "knowledge_roots": [root.relative_to(VAULT_PATH).as_posix() for root in knowledge_roots],
        "issues": len(issues),
        "errors": sum(1 for item in issues if item["severity"] == "error"),
        "warnings": sum(1 for item in issues if item["severity"] == "warning"),
    }
    return {"summary": summary, "issues": issues}


def _health_item(name: str, ok: bool, *, status: str | None = None, message: str = "", details: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "status": status or ("ok" if ok else "failed"),
        "message": message,
        "details": _jsonable(details),
    }


def _parse_iso_datetime(value: Any) -> datetime | None:
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


@app.get("/api/health-detail")
async def health_detail() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    try:
        db_info = _fetch_one("""
            select
              (select count(*) from documents) as documents,
              (select count(*) from chunks) as chunks,
              (select count(*) from indexed_files) as indexed_files,
              (select count(*) from knowledge_gaps where status='open') as open_gaps,
              (select count(*) from audit_logs) as audit_logs
        """)
        checks.append(_health_item("postgres", True, message="数据库连接正常", details=db_info))
        chunks = int(db_info.get("chunks") or 0)
        documents = int(db_info.get("documents") or 0)
        checks.append(_health_item(
            "index_counts",
            chunks > 0 and documents > 0,
            status="ok" if chunks > 0 and documents > 0 else "warning",
            message=f"documents={documents}, chunks={chunks}",
            details={"documents": documents, "chunks": chunks},
        ))
    except Exception as exc:
        checks.append(_health_item("postgres", False, message=str(exc)))

    try:
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            response = await client.get(f"{RAG_BASE_URL}/health")
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
        ok = response.status_code < 400 and bool(body.get("ok", True) if isinstance(body, dict) else True)
        checks.append(_health_item("rag_api", ok, message=f"HTTP {response.status_code}", details=body))
        if isinstance(body, dict):
            vector_backend = body.get("vector_backend") or "unknown"
            milvus = body.get("milvus") or {}
            if vector_backend == "milvus":
                milvus_ok = bool(milvus.get("ok"))
                checks.append(_health_item(
                    "milvus",
                    milvus_ok,
                    message=(
                        f"collection={milvus.get('collection')}, entities={milvus.get('entities')}"
                        if milvus_ok else str(milvus.get("error") or "Milvus 检查失败")
                    ),
                    details=milvus,
                ))
            else:
                checks.append(_health_item(
                    "milvus",
                    False,
                    status="warning",
                    message=f"未启用 Milvus，当前后端: {vector_backend}",
                    details=body,
                ))
    except Exception as exc:
        checks.append(_health_item("rag_api", False, message=str(exc), details={"base_url": RAG_BASE_URL}))

    try:
        headers = {"Authorization": f"Bearer {LITELLM_API_KEY}"} if LITELLM_API_KEY else {}
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.get(f"{LITELLM_BASE_URL.rstrip('/')}/models", headers=headers)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        model_ids = [item.get("id") for item in body.get("data", []) if isinstance(item, dict)] if isinstance(body, dict) else []
        required = ["Qwen3-Embedding-4B", "Qwen3-Reranker-0.6B"]
        missing = [model for model in required if model not in model_ids]
        checks.append(_health_item(
            "litellm_models",
            response.status_code < 400 and not missing,
            status="ok" if response.status_code < 400 and not missing else "warning",
            message="模型接口正常" if not missing else f"缺少模型: {', '.join(missing)}",
            details={"status_code": response.status_code, "models": model_ids},
        ))
    except Exception as exc:
        checks.append(_health_item("litellm_models", False, message=str(exc), details={"base_url": LITELLM_BASE_URL}))

    try:
        registry = _domain_registry_status()
        summary = registry.get("summary", {})
        errors = int(summary.get("errors") or 0)
        warnings_count = int(summary.get("warnings") or 0)
        domain_count = int(summary.get("domains") or 0)
        enabled_count = int(summary.get("enabled") or 0)
        checks.append(_health_item(
            "domain_registry",
            errors == 0 and domain_count > 0 and enabled_count > 0,
            status="ok" if errors == 0 and warnings_count == 0 and domain_count > 0 and enabled_count > 0 else ("warning" if errors == 0 else "failed"),
            message=f"domains={domain_count}, enabled={enabled_count}, issues={summary.get('issues')}",
            details=registry,
        ))
    except Exception as exc:
        checks.append(_health_item("domain_registry", False, message=str(exc), details={"path": str(DOMAIN_REGISTRY_PATH)}))

    git_head = _run(["git", "log", "-1", "--oneline", "--decorate"], cwd=VAULT_PATH, timeout=10)
    git_status = _run(["git", "status", "--short"], cwd=VAULT_PATH, timeout=10)
    git_ok = git_head.get("ok", False) and git_status.get("ok", False)
    dirty = bool((git_status.get("stdout") or "").strip())
    checks.append(_health_item(
        "vault_git",
        git_ok and not dirty,
        status="ok" if git_ok and not dirty else "warning",
        message="Vault Git 工作区干净" if git_ok and not dirty else "Vault Git 有未提交改动或检查失败",
        details={"head": git_head, "status": git_status},
    ))

    sync = _read_sync_status()
    sync_status_value = sync.get("status")
    ended_at = _parse_iso_datetime(sync.get("ended_at") or sync.get("started_at"))
    age_hours = None
    if ended_at:
        age_hours = round((datetime.now(timezone.utc) - ended_at).total_seconds() / 3600, 2)
    sync_ok = sync_status_value == "success"
    sync_warn = sync_ok and age_hours is not None and age_hours > 36
    checks.append(_health_item(
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
        checks.append(_health_item(
            "wiki_quality",
            errors == 0,
            status="ok" if errors == 0 and warnings == 0 else ("warning" if errors == 0 else "failed"),
            message=f"errors={errors}, warnings={warnings}",
            details=wiki,
        ))
    except Exception as exc:
        checks.append(_health_item("wiki_quality", False, message=str(exc)))

    try:
        obsidian = obsidian_wiki()
        installed = bool(obsidian.get("installed"))
        info_ok = bool((obsidian.get("info") or {}).get("ok"))
        checks.append(_health_item(
            "obsidian_wiki",
            installed and info_ok,
            status="ok" if installed and info_ok else "warning",
            message="obsidian-wiki 可用" if installed and info_ok else "obsidian-wiki 需要检查",
            details=obsidian,
        ))
    except Exception as exc:
        checks.append(_health_item("obsidian_wiki", False, message=str(exc)))

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


@app.get("/api/schema-template")
def schema_template() -> dict[str, Any]:
    if not SCHEMA_DOC.exists():
        return {"content": "schema document not found"}
    return {"path": str(SCHEMA_DOC), "content": SCHEMA_DOC.read_text(encoding="utf-8", errors="replace")}


@app.get("/api/obsidian-wiki")
def obsidian_wiki() -> dict[str, Any]:
    command = shutil.which("obsidian-wiki")
    venv_command = Path(sys.executable).parent / "obsidian-wiki"
    if command is None and venv_command.exists():
        command = str(venv_command)
    pip_show = _run([sys.executable, "-m", "pip", "show", "obsidian-wiki"], timeout=20)
    installed = bool(command) or pip_show.get("ok", False)
    info: dict[str, Any] = {
        "installed": installed,
        "command": command,
        "pip_show": pip_show,
        "vault_path": str(VAULT_PATH),
    }
    if command:
        info["version"] = _run([command, "--version"], timeout=20)
        info["info"] = _run([command, "info"], cwd=VAULT_PATH, timeout=60)
    elif installed:
        info["note"] = "obsidian-wiki Python package is installed, but no obsidian-wiki CLI entrypoint was found in PATH."
    else:
        info["note"] = "obsidian-wiki is not installed in this environment yet. Install it in the project venv before enabling skill operations."
    return info
