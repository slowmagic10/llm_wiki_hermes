from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from app.config import settings


class ProfileConfigError(ValueError):
    pass


DEFAULT_SECTIONS = [
    {"key": "conclusion", "label": "结论", "source_headings": ["一句话结论", "结论", "型号对应"]},
    {"key": "scenarios", "label": "适用场景", "source_headings": ["适用场景", "常用搭配", "推荐搭配", "使用场景", "型号对应"]},
    {"key": "notes", "label": "注意事项", "source_headings": ["限制条件", "注意事项", "兼容性", "售前确认点", "风险"]},
    {"key": "alternatives", "label": "可替代方案", "source_headings": ["替代方案"]},
    {"key": "sources", "label": "来源", "kind": "sources"},
]


def _default_profile() -> dict[str, Any]:
    return {
        "display_name": "默认知识",
        "retrieval": {
            "vector_top_k": settings.search_vector_top_k,
            "fts_top_k": settings.search_fts_top_k,
            "pre_rerank_top_k": 20,
            "rerank_top_k": settings.rerank_top_k,
            "answerable_threshold": settings.answerable_threshold,
            "rerank_only_answerable_threshold": 0.85,
            "milvus_filter_multiplier": 3,
        },
        "answer": {
            "max_sources": 4,
            "max_tokens": 900,
            "no_basis_text": "未在正式 Wiki 中找到明确依据。",
            "instructions": ["只能使用来源内容回答", "回答必须客观、简洁"],
            "sections": deepcopy(DEFAULT_SECTIONS),
        },
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def read_registry() -> dict[str, Any]:
    path = Path(settings.domain_registry_path)
    if not path.exists():
        raise ProfileConfigError(f"domain registry does not exist: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ProfileConfigError(f"invalid domain registry: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileConfigError("domain registry must be an object")
    return data


def resolve_profile(domain: str | None = None, profile: str | None = None) -> dict[str, Any]:
    registry = read_registry()
    domains = registry.get("domains") or {}
    profiles = registry.get("profiles") or {}
    domain_id = (domain or str(registry.get("default_domain") or "default")).strip()
    domain_config = domains.get(domain_id)
    if not isinstance(domain_config, dict):
        raise ProfileConfigError(f"unknown domain: {domain_id}")
    if not bool(domain_config.get("enabled", True)):
        raise ProfileConfigError(f"domain is disabled: {domain_id}")

    profile_id = (profile or str(domain_config.get("profile") or "default")).strip()
    raw_profile = profiles.get(profile_id)
    if not isinstance(raw_profile, dict):
        raise ProfileConfigError(f"unknown profile: {profile_id}")

    resolved = _deep_merge(_default_profile(), raw_profile)
    resolved.update({
        "id": profile_id,
        "domain": domain_id,
        "vault_subpath": str(domain_config.get("vault_subpath") or ".").strip("/") or ".",
    })
    _validate_profile(resolved)
    return resolved


def _validate_profile(profile: dict[str, Any]) -> None:
    retrieval = profile.get("retrieval") or {}
    for key in ("vector_top_k", "fts_top_k", "pre_rerank_top_k", "rerank_top_k", "milvus_filter_multiplier"):
        value = retrieval.get(key)
        if not isinstance(value, int) or value <= 0:
            raise ProfileConfigError(f"profile {profile.get('id')} retrieval.{key} must be a positive integer")
    for key in ("answerable_threshold", "rerank_only_answerable_threshold"):
        value = retrieval.get(key)
        if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
            raise ProfileConfigError(f"profile {profile.get('id')} retrieval.{key} must be between 0 and 1")
    sections = (profile.get("answer") or {}).get("sections")
    if not isinstance(sections, list) or not sections:
        raise ProfileConfigError(f"profile {profile.get('id')} answer.sections cannot be empty")
    labels = [str(item.get("label") or "").strip() for item in sections if isinstance(item, dict)]
    if len(labels) != len(sections) or any(not label for label in labels) or len(set(labels)) != len(labels):
        raise ProfileConfigError(f"profile {profile.get('id')} answer.sections labels must be non-empty and unique")
