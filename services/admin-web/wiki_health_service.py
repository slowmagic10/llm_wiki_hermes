from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from config import FRONTMATTER_RE, REQUIRED_FRONTMATTER, SKU_KEYS, VALID_STATUS, VAULT_PATH, WIKILINK_RE
from db import fetch_all
from domains_service import domain_path_status, expected_domain_for_path, read_domain_registry
from utils import as_list


def parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
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


def wiki_page_candidates() -> dict[str, Path]:
    pages: dict[str, Path] = {}
    for file_path in VAULT_PATH.rglob("*.md"):
        rel = file_path.relative_to(VAULT_PATH).as_posix()
        pages[rel[:-3]] = file_path
        pages[file_path.stem] = file_path
    return pages


def wiki_knowledge_roots() -> list[Path]:
    registry = read_domain_registry()
    roots: list[Path] = []
    for config in (registry.get("domains") or {}).values():
        if not isinstance(config, dict) or not bool(config.get("enabled")):
            continue
        subpath = str(config.get("vault_subpath") or ".")
        status = domain_path_status(subpath)
        if not status.get("safe"):
            continue
        base = (VAULT_PATH / subpath).resolve()
        knowledge_root = base / "10_Knowledge"
        if knowledge_root.exists():
            roots.append(knowledge_root)
    if not roots and (VAULT_PATH / "10_Knowledge").exists():
        roots.append(VAULT_PATH / "10_Knowledge")
    return roots


def check_updated(value: Any) -> tuple[str, str | None]:
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


def wiki_health() -> dict[str, Any]:
    knowledge_roots = wiki_knowledge_roots()
    docs: list[Path] = []
    for root in knowledge_roots:
        docs.extend(root.rglob("*.md"))
    docs = sorted(docs)
    indexed_rows = fetch_all("select path, status, error from indexed_files")
    indexed = {row["path"]: row for row in indexed_rows}
    pages = wiki_page_candidates()
    issues: list[dict[str, Any]] = []
    sku_seen: dict[str, str] = {}

    def add(path: str, severity: str, code: str, message: str) -> None:
        issues.append({"path": path, "severity": severity, "code": code, "message": message})

    for file_path in docs:
        rel = file_path.relative_to(VAULT_PATH).as_posix()
        raw = file_path.read_text(encoding="utf-8", errors="replace")
        fm, body = parse_frontmatter(raw)
        if not fm:
            add(rel, "warning", "missing_frontmatter", "缺少 YAML frontmatter，RAG 只能依赖正文和标题。")
        else:
            for key in REQUIRED_FRONTMATTER:
                if key not in fm or fm.get(key) in (None, ""):
                    add(rel, "warning", "missing_required_field", f"缺少字段: {key}")
            status = str(fm.get("status") or "").lower()
            if status and status not in VALID_STATUS:
                add(rel, "error", "invalid_status", f"status 不合法: {status}")
            expected_domain = expected_domain_for_path(rel)
            actual_domain = str(fm.get("domain") or "").strip()
            if expected_domain and actual_domain and actual_domain != expected_domain:
                add(rel, "error", "domain_mismatch", f"domain={actual_domain} 与路径所属领域 {expected_domain} 不一致")
            state, msg = check_updated(fm.get("updated"))
            if msg:
                add(rel, state, "updated_check", msg)
            for key in SKU_KEYS:
                for value in as_list(fm.get(key)):
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
