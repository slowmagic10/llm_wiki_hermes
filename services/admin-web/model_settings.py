from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from config import LITELLM_API_KEY, LITELLM_BASE_URL, MODEL_SETTINGS_PATH


def litellm_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_API_KEY}"
    return headers


def read_model_settings() -> dict[str, Any]:
    if not MODEL_SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(MODEL_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def model_defaults() -> dict[str, str]:
    return {
        "chat_model": os.getenv("CHAT_MODEL", "Qwen3.6-27B-FP8"),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "Qwen3-Embedding-4B"),
        "reranker_model": os.getenv("RERANKER_MODEL", "Qwen3-Reranker-0.6B"),
    }


def effective_model_settings() -> dict[str, str]:
    defaults = model_defaults()
    saved = read_model_settings()
    return {
        "chat_model": str(saved.get("chat_model") or defaults["chat_model"]),
        "embedding_model": str(saved.get("embedding_model") or defaults["embedding_model"]),
        "reranker_model": str(saved.get("reranker_model") or defaults["reranker_model"]),
    }


def write_model_settings(values: dict[str, str]) -> dict[str, Any]:
    MODEL_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **effective_model_settings(),
        **values,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    MODEL_SETTINGS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


async def list_litellm_models() -> list[str]:
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        response = await client.get(f"{LITELLM_BASE_URL.rstrip('/')}/models", headers=litellm_headers())
        response.raise_for_status()
        payload = response.json()
    models = []
    for item in payload.get("data", []):
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id:
            models.append(model_id)
    return sorted(set(models))
