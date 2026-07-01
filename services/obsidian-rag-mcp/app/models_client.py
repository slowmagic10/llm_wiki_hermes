import httpx

from app.config import model_setting, settings


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.litellm_api_key:
        headers["Authorization"] = f"Bearer {settings.litellm_api_key}"
    return headers


async def embed_text(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        response = await client.post(
            f"{settings.litellm_base_url.rstrip('/')}/embeddings",
            headers=_headers(),
            json={"model": model_setting("embedding_model"), "input": text},
        )
        response.raise_for_status()
        payload = response.json()
        return payload["data"][0]["embedding"]


async def rerank(query: str, documents: list[str]) -> list[float]:
    if not documents:
        return []
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        response = await client.post(
            f"{settings.litellm_base_url.rstrip('/')}/rerank",
            headers=_headers(),
            json={"model": model_setting("reranker_model"), "query": query, "documents": documents},
        )
        response.raise_for_status()
        payload = response.json()
    scores = [0.0] * len(documents)
    for item in payload.get("results", []):
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < len(scores):
            scores[index] = float(item.get("relevance_score") or 0.0)
    return scores


async def chat_complete(messages: list[dict[str, str]], max_tokens: int = 900) -> str:
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        response = await client.post(
            f"{settings.litellm_base_url.rstrip('/')}/chat/completions",
            headers=_headers(),
            json={
                "model": model_setting("chat_model"),
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": max_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        response.raise_for_status()
        payload = response.json()
    message = payload["choices"][0].get("message") or {}
    return (message.get("content") or message.get("reasoning_content") or "").strip()
