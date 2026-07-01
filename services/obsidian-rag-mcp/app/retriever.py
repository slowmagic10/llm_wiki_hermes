import re
from typing import Any

from psycopg2.extras import RealDictCursor, Json

from app.config import settings
from app.db import get_conn, vector_literal
from app.models_client import embed_text, rerank


RERANK_ONLY_ANSWERABLE_THRESHOLD = 0.85


async def search(query: str, product: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
    query_embedding = await embed_text(query)
    candidates = _collect_candidates(query, query_embedding, product, tags or [])

    if not candidates:
        _record_gap(query, "没有检索到候选来源")
        _record_audit(query, False, 0.0, [])
        return {"answerable": False, "confidence": 0.0, "reason": "no_candidates", "citations": [], "chunks": []}

    pre_ranked = sorted(candidates.values(), key=lambda item: item["rule_score"], reverse=True)[:20]
    scores = await rerank(query, [item["text"] for item in pre_ranked])
    for item, score in zip(pre_ranked, scores):
        item["rerank_score"] = score
        item["lexical_score"] = _lexical_score(item, query)
        item["final_score"] = max(float(score), float(item["lexical_score"]))

    ranked = sorted(
        pre_ranked,
        key=lambda item: (item["final_score"], item["rerank_score"], item["rule_score"]),
        reverse=True,
    )
    top = ranked[: settings.rerank_top_k]
    confidence = float(top[0]["final_score"]) if top else 0.0
    has_supported_evidence = bool(top and _has_supported_evidence(top[0]))
    answerable = bool(top and confidence >= settings.answerable_threshold and has_supported_evidence)

    citations = [
        {"path": item["path"], "heading": " > ".join(item["heading_path"]), "score": item["final_score"]}
        for item in top
    ]

    if not answerable:
        if top and confidence >= settings.answerable_threshold and not has_supported_evidence:
            reason = "no_supported_evidence"
            gap_reason = "没有足够的词面或强语义证据支持回答"
        else:
            reason = "low_confidence"
            gap_reason = "rerank 分数低于可回答阈值"
        _record_gap(query, gap_reason)
    else:
        reason = "found_reliable_sources"
    _record_audit(query, answerable, confidence, citations)

    return {
        "answerable": answerable,
        "confidence": confidence,
        "reason": reason,
        "citations": citations if answerable else [],
        "chunks": top if answerable else [],
    }


def _collect_candidates(query: str, query_embedding: list[float], product: str | None, tags: list[str]) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    _merge_candidates(candidates, _fts_candidates(query, product, tags), "fts_score")
    _merge_candidates(candidates, _vector_candidates(query_embedding, product, tags), "vector_score")
    for item in candidates.values():
        item["rule_score"] = _rule_score(item, query, tags)
    return candidates


def _metadata_filter(product: str | None, tags: list[str]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if product:
        clauses.append("and d.product = %s")
        params.append(product)
    if tags:
        clauses.append("and d.tags && %s")
        params.append(tags)
    return "\n".join(clauses), params


def _fts_candidates(query: str, product: str | None, tags: list[str]) -> list[dict[str, Any]]:
    where, params = _metadata_filter(product, tags)
    sql = f"""
        select c.id::text as id, c.path, c.heading_path, c.text, c.metadata,
               ts_rank_cd(c.fts, plainto_tsquery('simple', %s)) as fts_score,
               0.0 as vector_score
        from chunks c
        join documents d on d.id = c.document_id
        where c.fts @@ plainto_tsquery('simple', %s)
        {where}
        order by fts_score desc
        limit %s
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (query, query, *params, settings.search_fts_top_k))
            return list(cur.fetchall())


def _vector_candidates(query_embedding: list[float], product: str | None, tags: list[str]) -> list[dict[str, Any]]:
    where, params = _metadata_filter(product, tags)
    sql = f"""
        select c.id::text as id, c.path, c.heading_path, c.text, c.metadata,
               0.0 as fts_score,
               1.0 - (c.embedding <=> %s::vector) as vector_score
        from chunks c
        join documents d on d.id = c.document_id
        where c.embedding is not null
        {where}
        order by c.embedding <=> %s::vector
        limit %s
    """
    vector = vector_literal(query_embedding)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (vector, *params, vector, settings.search_vector_top_k))
            return list(cur.fetchall())


def _merge_candidates(candidates: dict[str, dict[str, Any]], rows: list[dict[str, Any]], score_key: str) -> None:
    for row in rows:
        item = candidates.setdefault(
            row["id"],
            {
                "id": row["id"],
                "path": row["path"],
                "heading_path": row["heading_path"] or [],
                "text": row["text"],
                "metadata": row["metadata"] or {},
                "fts_score": 0.0,
                "vector_score": 0.0,
                "rerank_score": 0.0,
            },
        )
        item[score_key] = max(float(item.get(score_key) or 0.0), float(row.get(score_key) or 0.0))



def _normal_code(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _code_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for match in re.finditer(r"[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)+", value):
        code = _normal_code(match.group(0))
        if code:
            tokens.add(code)
    for match in re.finditer(r"[A-Za-z0-9]{5,}", value):
        raw = match.group(0)
        if re.search(r"[A-Za-z]", raw) and re.search(r"[0-9]", raw):
            code = _normal_code(raw)
            if code:
                tokens.add(code)
    return tokens


def _heading_without_number(value: str) -> str:
    return re.sub(r"^\s*\d+\s*[、.)．]\s*", "", value).strip()


def _lexical_score(item: dict[str, Any], query: str) -> float:
    query_codes = _code_tokens(query)
    if not query_codes:
        return 0.0

    metadata = item.get("metadata") or {}
    heading_text = " ".join(item.get("heading_path") or [])
    body_text = str(item.get("text") or "")
    metadata_values = []
    for key in ("sku", "aliases", "compatible_with", "alternatives"):
        value = metadata.get(key)
        if isinstance(value, list):
            metadata_values.extend(str(part) for part in value)
        elif value:
            metadata_values.append(str(value))
    metadata_norm = _normal_code(" ".join(metadata_values))
    heading_norm = _normal_code(heading_text)
    body_norm = _normal_code(body_text[:800])

    for code in query_codes:
        if code and code in metadata_norm:
            return 1.0
        if code and code in heading_norm:
            return 1.0
        if code and code in body_norm:
            return 0.72

    query_norm = _normal_code(query)
    for part in item.get("heading_path") or []:
        clean = _normal_code(_heading_without_number(str(part)))
        if clean and clean in query_norm:
            return 0.95
    return 0.0


def _has_supported_evidence(item: dict[str, Any]) -> bool:
    if float(item.get("lexical_score") or 0.0) > 0.0:
        return True
    if float(item.get("rerank_score") or 0.0) >= RERANK_ONLY_ANSWERABLE_THRESHOLD:
        return True
    return False


def _rule_score(item: dict[str, Any], query: str, tags: list[str]) -> float:
    metadata = item.get("metadata") or {}
    title = str(metadata.get("title") or "")
    item_tags = set(metadata.get("tags") or [])
    heading_parts = item.get("heading_path") or []
    title_match = 1.0 if title and title in query else 0.0
    heading_match = 0.5 if any(part and part in query for part in heading_parts) else 0.0
    tag_match = 1.0 if tags and item_tags.intersection(tags) else 0.0
    return (
        float(item.get("vector_score") or 0.0) * 0.45
        + float(item.get("fts_score") or 0.0) * 0.35
        + title_match * 0.10
        + heading_match * 0.05
        + tag_match * 0.05
    )


def _record_gap(query: str, reason: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into knowledge_gaps (query, suggested_title, frequency, status, first_seen_at, last_seen_at)
                values (%s, %s, 1, 'open', now(), now())
                """,
                (query, reason),
            )


def _record_audit(query: str, answerable: bool, confidence: float, citations: list[dict[str, Any]]) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into audit_logs (query, answerable, confidence, citations) values (%s, %s, %s, %s)",
                (query, answerable, confidence, Json(citations)),
            )
