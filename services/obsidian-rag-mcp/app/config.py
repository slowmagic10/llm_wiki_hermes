import os
import json
from pathlib import Path
from typing import Any


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float_env(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


class Settings:
    vault_path = os.getenv("VAULT_PATH", "/root/llm_wiki_hermes/vault")
    database_url = os.getenv("DATABASE_URL", "postgresql://rag:rag@127.0.0.1:25432/rag")
    litellm_base_url = os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:14000/v1")
    litellm_api_key = os.getenv("LITELLM_API_KEY", "")
    model_settings_path = os.getenv("MODEL_SETTINGS_PATH", "/root/llm_wiki_hermes/config/model-settings.json")
    domain_registry_path = os.getenv("DOMAIN_REGISTRY_PATH", "/root/llm_wiki_hermes/config/domains.yml")
    chat_model = os.getenv("CHAT_MODEL", "Qwen3.6-35B-A3B-FP8")
    embedding_model = os.getenv("EMBEDDING_MODEL", "Qwen3-Embedding-4B")
    reranker_model = os.getenv("RERANKER_MODEL", "Qwen3-Reranker-0.6B")
    final_answer_mode = os.getenv("FINAL_ANSWER_MODE", "deterministic").lower()
    chunk_max_chars = _int_env("CHUNK_MAX_CHARS", 1200)
    chunk_overlap_chars = _int_env("CHUNK_OVERLAP_CHARS", 120)
    search_vector_top_k = _int_env("SEARCH_VECTOR_TOP_K", 30)
    search_fts_top_k = _int_env("SEARCH_FTS_TOP_K", 30)
    rerank_top_k = _int_env("RERANK_TOP_K", 8)
    answerable_threshold = _float_env("ANSWERABLE_THRESHOLD", 0.5)
    vector_backend = os.getenv("VECTOR_BACKEND", "pgvector").lower()
    milvus_uri = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
    milvus_collection = os.getenv("MILVUS_COLLECTION", "llm_wiki_chunks")


settings = Settings()


def load_model_settings() -> dict[str, Any]:
    path = Path(settings.model_settings_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def model_setting(name: str) -> str:
    data = load_model_settings()
    value = data.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return str(getattr(settings, name))
