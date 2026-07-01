import os


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float_env(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


class Settings:
    vault_path = os.getenv("VAULT_PATH", "/root/llm_wiki_hermes/vault")
    database_url = os.getenv("DATABASE_URL", "postgresql://rag:rag@127.0.0.1:25432/rag")
    litellm_base_url = os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:14000/v1")
    litellm_api_key = os.getenv("LITELLM_API_KEY", "")
    chat_model = os.getenv("CHAT_MODEL", "Qwen3.6-35B-A3B-FP8")
    embedding_model = os.getenv("EMBEDDING_MODEL", "Qwen3-Embedding-4B")
    reranker_model = os.getenv("RERANKER_MODEL", "Qwen3-Reranker-0.6B")
    chunk_max_chars = _int_env("CHUNK_MAX_CHARS", 1200)
    chunk_overlap_chars = _int_env("CHUNK_OVERLAP_CHARS", 120)
    search_vector_top_k = _int_env("SEARCH_VECTOR_TOP_K", 30)
    search_fts_top_k = _int_env("SEARCH_FTS_TOP_K", 30)
    rerank_top_k = _int_env("RERANK_TOP_K", 8)
    answerable_threshold = _float_env("ANSWERABLE_THRESHOLD", 0.5)


settings = Settings()
