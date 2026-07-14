#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml


HOOK_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
DOMAIN_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

HANDLER_TEMPLATE = '''"""Generated domain-isolated Hermes Wiki router. Do not edit by hand."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from typing import Any

from gateway.platforms.base import BasePlatformAdapter, MessageType

DOMAIN_ID = __DOMAIN_ID__
HOOK_NAME = __HOOK_NAME__
PRIMARY_TRIGGER = __PRIMARY_TRIGGER__
TRIGGER_PREFIXES = __TRIGGER_PREFIXES__
PLATFORMS = frozenset(__PLATFORMS__)
DEFAULT_RAG_ANSWER_URL = __RAG_ANSWER_URL__
RAG_ANSWER_URL = os.getenv(__URL_ENV_NAME__, DEFAULT_RAG_ANSWER_URL)
RAG_TIMEOUT_SECONDS = float(os.getenv("LLM_WIKI_RAG_TIMEOUT_SECONDS", "90"))

_ORIGINAL_ATTR = f"_{HOOK_NAME}_original_set_message_handler"
_PATCHED_ATTR = f"_{HOOK_NAME}_patched"


def _platform_name(adapter: BasePlatformAdapter) -> str:
    platform = getattr(getattr(adapter, "platform", None), "value", "")
    return str(platform).lower()


def _extract_query(text: str) -> str | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    lowered = stripped.casefold()
    for prefix in TRIGGER_PREFIXES:
        normalized = prefix.casefold()
        if lowered == normalized:
            return ""
        if lowered.startswith(normalized + " ") or lowered.startswith(normalized + "\\n"):
            return stripped[len(prefix):].strip()
    return None


def _should_route(adapter: BasePlatformAdapter, event: Any) -> bool:
    if PLATFORMS and _platform_name(adapter) not in PLATFORMS:
        return False
    if getattr(event, "message_type", None) != MessageType.TEXT:
        return False
    return _extract_query(getattr(event, "text", "") or "") is not None


def _post_answer(query: str) -> dict[str, Any]:
    payload = json.dumps({"query": query}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        RAG_ANSWER_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=RAG_TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)
    if data.get("domain") != DOMAIN_ID or not data.get("entrypoint_isolated"):
        raise RuntimeError(
            f"domain isolation check failed: expected={DOMAIN_ID}, "
            f"actual={data.get('domain')}, isolated={data.get('entrypoint_isolated')}"
        )
    return data


async def _answer_from_wiki(query: str) -> str:
    if not query.strip():
        return f"请在 {PRIMARY_TRIGGER} 后输入要查询的问题。"
    data = await asyncio.to_thread(_post_answer, query)
    final_answer = (data.get("final_answer") or "").strip()
    if final_answer:
        return final_answer
    return "正式 Wiki 中没有检索到足够可靠的来源，暂不能回答。"


def _install_patch() -> None:
    if getattr(BasePlatformAdapter, _PATCHED_ATTR, False):
        return

    original = BasePlatformAdapter.set_message_handler
    setattr(BasePlatformAdapter, _ORIGINAL_ATTR, original)

    def patched_set_message_handler(self: BasePlatformAdapter, handler):
        async def wrapped_handler(event):
            if _should_route(self, event):
                query = _extract_query(getattr(event, "text", "") or "") or ""
                try:
                    return await _answer_from_wiki(query)
                except Exception as exc:
                    print(f"[{HOOK_NAME}] domain={DOMAIN_ID} RAG answer failed: {exc}", flush=True)
                    return f"{DOMAIN_ID} 领域正式 Wiki 检索服务暂不可用，暂不能回答。"
            return await handler(event)

        return original(self, wrapped_handler)

    BasePlatformAdapter.set_message_handler = patched_set_message_handler
    setattr(BasePlatformAdapter, _PATCHED_ATTR, True)
    print(
        f"[{HOOK_NAME}] installed domain={DOMAIN_ID} triggers={TRIGGER_PREFIXES} "
        f"platforms={sorted(PLATFORMS)}",
        flush=True,
    )


_install_patch()


async def handle(event_type: str, context: dict[str, Any]) -> None:
    return None
'''


def _load_registry(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("domain registry must be an object")
    return data


def _domain_specs(registry: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    trigger_owners: dict[str, str] = {}
    hook_owners: dict[str, str] = {}

    for domain_id, config in (registry.get("domains") or {}).items():
        if not isinstance(config, dict) or not bool(config.get("enabled", True)):
            continue
        domain_id = str(domain_id)
        if not DOMAIN_ID_RE.fullmatch(domain_id):
            raise ValueError(f"invalid domain id: {domain_id}")

        hook_name = str(config.get("hermes_hook") or f"llm_wiki_{domain_id}_router")
        if not HOOK_NAME_RE.fullmatch(hook_name):
            raise ValueError(f"invalid Hermes hook name for {domain_id}: {hook_name}")
        previous_domain = hook_owners.setdefault(hook_name, domain_id)
        if previous_domain != domain_id:
            raise ValueError(f"Hermes hook collision: {hook_name} ({previous_domain}, {domain_id})")

        primary = str(config.get("entrypoint") or "").strip()
        aliases = config.get("entrypoint_aliases") or []
        if not primary.startswith("/") or any(char.isspace() for char in primary):
            raise ValueError(f"invalid entrypoint for {domain_id}: {primary}")
        if not isinstance(aliases, list):
            raise ValueError(f"entrypoint_aliases must be a list for {domain_id}")
        triggers = [primary, *(str(value).strip() for value in aliases if str(value).strip())]
        unique_triggers = list(dict.fromkeys(triggers))
        for trigger in unique_triggers:
            normalized = trigger.casefold()
            previous_domain = trigger_owners.setdefault(normalized, domain_id)
            if previous_domain != domain_id:
                raise ValueError(f"entrypoint collision: {trigger} ({previous_domain}, {domain_id})")

        platforms = config.get("entrypoint_platforms") or ["qqbot"]
        if not isinstance(platforms, list):
            raise ValueError(f"entrypoint_platforms must be a list for {domain_id}")
        platforms = sorted({str(value).strip().lower() for value in platforms if str(value).strip()})

        rag_base_url = str(config.get("hermes_rag_base_url") or "http://127.0.0.1:18080").rstrip("/")
        specs.append({
            "domain": domain_id,
            "hook_name": hook_name,
            "primary_trigger": primary,
            "triggers": unique_triggers,
            "platforms": platforms,
            "rag_answer_url": f"{rag_base_url}/rag/domains/{domain_id}/answer",
        })
    return specs


def _render_handler(spec: dict[str, Any]) -> str:
    env_domain = re.sub(r"[^A-Z0-9]+", "_", spec["domain"].upper())
    replacements = {
        "__DOMAIN_ID__": repr(spec["domain"]),
        "__HOOK_NAME__": repr(spec["hook_name"]),
        "__PRIMARY_TRIGGER__": repr(spec["primary_trigger"]),
        "__TRIGGER_PREFIXES__": repr(tuple(spec["triggers"])),
        "__PLATFORMS__": repr(tuple(spec["platforms"])),
        "__RAG_ANSWER_URL__": repr(spec["rag_answer_url"]),
        "__URL_ENV_NAME__": repr(f"LLM_WIKI_{env_domain}_RAG_ANSWER_URL"),
    }
    rendered = HANDLER_TEMPLATE
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


def _render_manifest(spec: dict[str, Any]) -> str:
    return yaml.safe_dump(
        {
            "name": spec["hook_name"],
            "description": (
                f"Route {spec['primary_trigger']} to the read-only "
                f"{spec['domain']} Wiki domain."
            ),
            "events": ["gateway:startup"],
        },
        allow_unicode=True,
        sort_keys=False,
    )


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _managed_hook_dirs(target_root: Path) -> dict[str, Path]:
    managed: dict[str, Path] = {}
    if not target_root.is_dir():
        return managed
    for child in target_root.iterdir():
        if not child.is_dir():
            continue
        handler = child / "handler.py"
        if not handler.is_file():
            continue
        text = handler.read_text(encoding="utf-8", errors="replace")
        if "Generated domain-isolated Hermes Wiki router" in text:
            managed[child.name] = child
    return managed


def main() -> int:
    parser = argparse.ArgumentParser(description="Render domain-isolated Hermes Wiki hooks.")
    parser.add_argument("--registry", type=Path, default=Path("/root/llm_wiki_hermes/config/domains.yml"))
    parser.add_argument("--target-root", type=Path, default=Path("/root/.hermes/hooks"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    specs = _domain_specs(_load_registry(args.registry))
    active_hook_names = {spec["hook_name"] for spec in specs}
    results: list[dict[str, Any]] = []
    drift = False
    for spec in specs:
        hook_dir = args.target_root / spec["hook_name"]
        expected = {
            hook_dir / "HOOK.yaml": _render_manifest(spec),
            hook_dir / "handler.py": _render_handler(spec),
        }
        changed_files: list[str] = []
        for path, expected_content in expected.items():
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current == expected_content:
                continue
            changed_files.append(path.name)
            drift = True
            if not args.check:
                _write_atomic(path, expected_content)
        results.append({
            **spec,
            "changed_files": changed_files,
            "status": "drift" if changed_files else "ok",
        })

    for hook_name, hook_dir in _managed_hook_dirs(args.target_root).items():
        if hook_name in active_hook_names:
            continue
        stale_files = [path for path in (hook_dir / "HOOK.yaml", hook_dir / "handler.py") if path.exists()]
        if not stale_files:
            continue
        drift = True
        if not args.check:
            for path in stale_files:
                path.unlink()
        results.append({
            "domain": None,
            "hook_name": hook_name,
            "changed_files": [path.name for path in stale_files],
            "status": "stale" if args.check else "disabled",
        })

    print(json.dumps({"check": args.check, "domains": results}, ensure_ascii=False, indent=2))
    return 1 if args.check and drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
