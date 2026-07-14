from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from config import DOMAIN_REGISTRY_PATH, RAG_BASE_URL, SYNC_STATUS_FILE, VAULT_PATH
from db import fetch_one
from entrypoints_service import domain_entrypoint_issues, domain_hook_status

DOMAIN_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def default_domain_registry() -> dict[str, Any]:
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
                "entrypoint_aliases": ["/llmwiki", "wiki:", "wiki：", "llmwiki:", "llmwiki："],
                "entrypoint_platforms": ["qqbot"],
                "hermes_hook": "llm_wiki_router",
                "hermes_rag_base_url": "http://127.0.0.1:18080",
                "enabled": True,
            }
        },
    }


def read_domain_registry() -> dict[str, Any]:
    source = "file"
    if DOMAIN_REGISTRY_PATH.exists():
        raw = yaml.safe_load(DOMAIN_REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    else:
        raw = default_domain_registry()
        source = "default"
    if not isinstance(raw, dict):
        raw = {}
    domains = raw.get("domains")
    if not isinstance(domains, dict):
        domains = {}
    return {
        "version": raw.get("version", 1),
        "default_domain": str(raw.get("default_domain") or "default"),
        "vault_layout": raw.get("vault_layout") if isinstance(raw.get("vault_layout"), dict) else {},
        "registry_path": str(DOMAIN_REGISTRY_PATH),
        "source": source,
        "domains": domains,
        "profiles": raw.get("profiles") if isinstance(raw.get("profiles"), dict) else {},
        "notes": raw.get("notes", []),
    }


def write_domain_registry(registry: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "version": registry.get("version", 1),
        "default_domain": str(registry.get("default_domain") or "default"),
        "vault_layout": registry.get("vault_layout") if isinstance(registry.get("vault_layout"), dict) else {},
        "notes": registry.get("notes") if isinstance(registry.get("notes"), list) else [],
        "domains": registry.get("domains") if isinstance(registry.get("domains"), dict) else {},
        "profiles": registry.get("profiles") if isinstance(registry.get("profiles"), dict) else {},
    }
    DOMAIN_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = DOMAIN_REGISTRY_PATH.with_suffix(DOMAIN_REGISTRY_PATH.suffix + ".tmp")
    backup = DOMAIN_REGISTRY_PATH.with_suffix(DOMAIN_REGISTRY_PATH.suffix + ".bak")
    if DOMAIN_REGISTRY_PATH.exists():
        shutil.copy2(DOMAIN_REGISTRY_PATH, backup)
    rendered = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, DOMAIN_REGISTRY_PATH)
    return payload


def validate_domain_registry(registry: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    domains = registry.get("domains") or {}
    if not domains:
        issues.append({"severity": "error", "domain": "-", "code": "empty_domains", "message": "domains 不能为空"})
        return issues
    default_domain = str(registry.get("default_domain") or "")
    if default_domain and default_domain not in domains:
        issues.append({"severity": "error", "domain": default_domain, "code": "missing_default_domain", "message": "default_domain 未在 domains 中定义"})
    default_config = domains.get(default_domain)
    if isinstance(default_config, dict) and not bool(default_config.get("enabled")):
        issues.append({"severity": "error", "domain": default_domain, "code": "disabled_default_domain", "message": "default_domain 必须保持启用"})
    profiles = registry.get("profiles") or {}
    required = ("display_name", "profile", "vault_subpath", "rag_base_url", "sync_status_file", "entrypoint", "hermes_hook", "enabled")
    enabled_paths: list[tuple[str, str]] = []
    for domain_id, config in domains.items():
        domain_id = str(domain_id)
        if not DOMAIN_ID_RE.fullmatch(domain_id):
            issues.append({"severity": "error", "domain": domain_id, "code": "invalid_domain_id", "message": "领域 ID 只能使用小写字母、数字、下划线和连字符，且必须以字母开头"})
        if not isinstance(config, dict):
            issues.append({"severity": "error", "domain": str(domain_id), "code": "invalid_domain_config", "message": "领域配置必须是对象"})
            continue
        for key in required:
            if key not in config:
                issues.append({"severity": "warning", "domain": str(domain_id), "code": "missing_field", "message": f"缺少字段: {key}"})
        profile_id = str(config.get("profile") or "")
        if profile_id and profile_id not in profiles:
            issues.append({"severity": "error", "domain": str(domain_id), "code": "unknown_profile", "message": f"未定义 profile: {profile_id}"})
        subpath = str(config.get("vault_subpath") or "")
        if subpath.startswith("/") or ".." in Path(subpath).parts:
            issues.append({"severity": "error", "domain": str(domain_id), "code": "invalid_vault_subpath", "message": f"vault_subpath 不安全: {subpath}"})
        elif bool(config.get("enabled")):
            normalized_path = subpath.strip("/") or "."
            for other_domain, other_path in enabled_paths:
                overlaps = (
                    normalized_path == "."
                    or other_path == "."
                    or normalized_path == other_path
                    or normalized_path.startswith(other_path + "/")
                    or other_path.startswith(normalized_path + "/")
                )
                if overlaps:
                    issues.append({
                        "severity": "error",
                        "domain": domain_id,
                        "code": "vault_subpath_overlap",
                        "message": f"vault_subpath 与领域 {other_domain} 重叠: {normalized_path} / {other_path}",
                    })
            enabled_paths.append((domain_id, normalized_path))
        target_subpath = str(config.get("target_vault_subpath") or "")
        if target_subpath and (target_subpath.startswith("/") or ".." in Path(target_subpath).parts):
            issues.append({"severity": "error", "domain": str(domain_id), "code": "invalid_target_vault_subpath", "message": f"target_vault_subpath 不安全: {target_subpath}"})
    issues.extend(domain_entrypoint_issues(registry))
    return issues


def domain_path_status(subpath: str) -> dict[str, Any]:
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


def domain_indexed_count(subpath: str) -> int | None:
    rel = subpath or "."
    try:
        if rel == ".":
            row = fetch_one("select count(*) as count from indexed_files")
        else:
            prefix = rel.rstrip("/") + "/"
            row = fetch_one("select count(*) as count from indexed_files where path = %s or path like %s", (rel, prefix + "%"))
        return int(row.get("count") or 0)
    except Exception:
        return None


def expected_domain_for_path(relative_path: str) -> str | None:
    registry = read_domain_registry()
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


def domain_registry_status() -> dict[str, Any]:
    registry = read_domain_registry()
    issues = validate_domain_registry(registry)
    domains = registry.get("domains") or {}
    enriched_domains: dict[str, Any] = {}
    for domain_id, config in domains.items():
        if not isinstance(config, dict):
            enriched_domains[str(domain_id)] = config
            continue
        current_status = domain_path_status(str(config.get("vault_subpath") or "."))
        target_status = domain_path_status(str(config.get("target_vault_subpath") or ""))
        hook_status = domain_hook_status(str(domain_id), str(config.get("hermes_hook") or ""))
        if bool(config.get("enabled")) and not hook_status.get("ready"):
            issues.append({
                "severity": "warning",
                "domain": str(domain_id),
                "code": "hermes_hook_not_ready",
                "message": f"Hermes 领域入口未生成或与领域不匹配: {config.get('hermes_hook') or '-'}",
            })
        enriched_domains[str(domain_id)] = {
            **config,
            "vault_status": {
                **current_status,
                "indexed_files": domain_indexed_count(str(config.get("vault_subpath") or ".")),
            },
            "target_vault_status": target_status if config.get("target_vault_subpath") else None,
            "hermes_hook_status": hook_status,
            "isolated_answer_url": f"/rag/domains/{domain_id}/answer",
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
