from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from config import DOMAIN_HOOK_SYNC_SCRIPT, DOMAIN_REGISTRY_PATH, HERMES_HOOKS_PATH
from domains_service import (
    domain_registry_status,
    read_domain_registry,
    validate_domain_registry,
    write_domain_registry,
)


class DomainAdminError(ValueError):
    def __init__(self, message: str, *, issues: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.issues = issues or []


def _normalize_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def normalize_domain_config(config: dict[str, Any]) -> dict[str, Any]:
    text_fields = (
        "display_name",
        "description",
        "profile",
        "vault_subpath",
        "target_vault_subpath",
        "isolation_mode",
        "rag_base_url",
        "sync_status_file",
        "vector_backend",
        "vector_collection",
        "entrypoint",
        "hermes_hook",
        "hermes_rag_base_url",
    )
    normalized = {key: str(value or "").strip() for key, value in config.items() if key in text_fields}
    normalized["entrypoint_aliases"] = _normalize_list(config.get("entrypoint_aliases"))
    normalized["entrypoint_platforms"] = [value.lower() for value in _normalize_list(config.get("entrypoint_platforms"))]
    normalized["enabled"] = bool(config.get("enabled"))
    return normalized


def candidate_registry(
    domain_id: str,
    config: dict[str, Any],
    *,
    make_default: bool,
) -> dict[str, Any]:
    registry = read_domain_registry()
    domains = dict(registry.get("domains") or {})
    current = domains.get(domain_id)
    merged = {**current, **normalize_domain_config(config)} if isinstance(current, dict) else normalize_domain_config(config)
    domains[domain_id] = merged
    registry["domains"] = domains
    if make_default:
        registry["default_domain"] = domain_id
    return registry


def validate_domain_update(
    domain_id: str,
    config: dict[str, Any],
    *,
    make_default: bool,
) -> dict[str, Any]:
    registry = candidate_registry(domain_id, config, make_default=make_default)
    issues = validate_domain_registry(registry)
    return {
        "ok": not any(item.get("severity") == "error" for item in issues),
        "domain": domain_id,
        "default_domain": registry.get("default_domain"),
        "issues": issues,
    }


def save_domain_update(
    domain_id: str,
    config: dict[str, Any],
    *,
    make_default: bool,
) -> dict[str, Any]:
    registry = candidate_registry(domain_id, config, make_default=make_default)
    issues = validate_domain_registry(registry)
    errors = [item for item in issues if item.get("severity") == "error"]
    if errors:
        raise DomainAdminError("领域配置校验失败", issues=issues)
    write_domain_registry(registry)
    return {
        "ok": True,
        "saved": True,
        "domain": domain_id,
        "default_domain": registry.get("default_domain"),
        "issues": issues,
        "registry": domain_registry_status(),
    }


def _run_generator(*extra_args: str) -> tuple[int, dict[str, Any], str]:
    command = [
        sys.executable,
        str(DOMAIN_HOOK_SYNC_SCRIPT),
        "--registry",
        str(DOMAIN_REGISTRY_PATH),
        "--target-root",
        str(HERMES_HOOKS_PATH),
        *extra_args,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    try:
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {"raw_stdout": result.stdout}
    return result.returncode, payload, result.stderr.strip()


def apply_domain_hooks() -> dict[str, Any]:
    registry = read_domain_registry()
    issues = validate_domain_registry(registry)
    errors = [item for item in issues if item.get("severity") == "error"]
    if errors:
        raise DomainAdminError("注册表存在错误，不能生成 Hermes hooks", issues=issues)
    if not DOMAIN_HOOK_SYNC_SCRIPT.is_file():
        raise DomainAdminError(f"hook 生成脚本不存在: {DOMAIN_HOOK_SYNC_SCRIPT}")

    check_code, before, check_error = _run_generator("--check")
    if check_code not in (0, 1):
        raise DomainAdminError(f"hook 漂移检查失败: {check_error or before}")

    changed = check_code == 1
    applied: dict[str, Any] = {"domains": []}
    if changed:
        apply_code, applied, apply_error = _run_generator()
        if apply_code != 0:
            raise DomainAdminError(f"hook 生成失败: {apply_error or applied}")

    verify_code, verified, verify_error = _run_generator("--check")
    if verify_code != 0:
        raise DomainAdminError(f"hook 生成后校验失败: {verify_error or verified}")

    return {
        "ok": True,
        "changed": changed,
        "restart_required": changed,
        "restart_command": "docker restart hermes" if changed else None,
        "before": before,
        "applied": applied,
        "verified": verified,
        "registry": domain_registry_status(),
    }
