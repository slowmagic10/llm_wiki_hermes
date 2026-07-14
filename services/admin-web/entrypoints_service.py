from __future__ import annotations

import re
from typing import Any

from config import HERMES_HOOKS_PATH


HOOK_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


def domain_entrypoint_issues(registry: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    entrypoint_owners: dict[str, str] = {}
    hook_owners: dict[str, str] = {}

    for raw_domain_id, config in (registry.get("domains") or {}).items():
        domain_id = str(raw_domain_id)
        if not isinstance(config, dict) or not bool(config.get("enabled", True)):
            continue

        entrypoint = str(config.get("entrypoint") or "").strip()
        aliases = config.get("entrypoint_aliases") or []
        if not entrypoint.startswith("/") or any(char.isspace() for char in entrypoint):
            issues.append({
                "severity": "error",
                "domain": domain_id,
                "code": "invalid_entrypoint",
                "message": f"入口必须是无空格的 /command: {entrypoint}",
            })
        if not isinstance(aliases, list):
            issues.append({
                "severity": "error",
                "domain": domain_id,
                "code": "invalid_entrypoint_aliases",
                "message": "entrypoint_aliases 必须是列表",
            })
            aliases = []

        for trigger in [entrypoint, *(str(value).strip() for value in aliases if str(value).strip())]:
            normalized = trigger.casefold()
            owner = entrypoint_owners.setdefault(normalized, domain_id)
            if owner != domain_id:
                issues.append({
                    "severity": "error",
                    "domain": domain_id,
                    "code": "entrypoint_collision",
                    "message": f"入口 {trigger} 已属于领域 {owner}",
                })

        hook_name = str(config.get("hermes_hook") or "")
        if not HOOK_NAME_RE.fullmatch(hook_name):
            issues.append({
                "severity": "error",
                "domain": domain_id,
                "code": "invalid_hermes_hook",
                "message": f"Hermes hook 名称不合法: {hook_name}",
            })
            continue
        owner = hook_owners.setdefault(hook_name, domain_id)
        if owner != domain_id:
            issues.append({
                "severity": "error",
                "domain": domain_id,
                "code": "hermes_hook_collision",
                "message": f"Hook {hook_name} 已属于领域 {owner}",
            })
    return issues


def domain_hook_status(domain_id: str, hook_name: str) -> dict[str, Any]:
    if not HOOK_NAME_RE.fullmatch(hook_name):
        return {"ready": False, "hook": hook_name, "reason": "invalid_hook_name"}

    hook_dir = HERMES_HOOKS_PATH / hook_name
    manifest = hook_dir / "HOOK.yaml"
    handler = hook_dir / "handler.py"
    manifest_exists = manifest.is_file()
    handler_exists = handler.is_file()
    generated = False
    domain_bound = False
    if handler_exists:
        text = handler.read_text(encoding="utf-8", errors="replace")
        generated = "Generated domain-isolated Hermes Wiki router" in text
        domain_bound = (
            f"DOMAIN_ID = {domain_id!r}" in text
            and f"/rag/domains/{domain_id}/answer" in text
        )
    return {
        "ready": manifest_exists and handler_exists and generated and domain_bound,
        "hook": hook_name,
        "path": str(hook_dir),
        "manifest_exists": manifest_exists,
        "handler_exists": handler_exists,
        "generated": generated,
        "domain_bound": domain_bound,
    }
