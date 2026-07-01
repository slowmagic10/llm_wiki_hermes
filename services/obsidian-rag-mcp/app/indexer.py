from pathlib import Path
from typing import Any

from psycopg2.extras import Json

from app.config import settings
from app.db import get_conn, vector_literal
from app.models_client import embed_text
from app.parser import ParsedDocument, parse_markdown


async def run_sync() -> dict[str, Any]:
    vault_path = Path(settings.vault_path)
    if not vault_path.exists():
        raise FileNotFoundError(f"Vault path does not exist: {vault_path}")

    files = sorted(vault_path.rglob("*.md"))
    seen_paths: set[str] = set()
    indexed = 0
    skipped = 0
    errors: list[dict[str, str]] = []

    for file_path in files:
        relative_path = file_path.relative_to(vault_path).as_posix()
        seen_paths.add(relative_path)
        try:
            parsed = parse_markdown(file_path, vault_path)
            if parsed is None:
                skipped += 1
                _mark_skipped(relative_path)
                continue
            if _is_unchanged(parsed):
                skipped += 1
                continue
            await _index_document(parsed, file_path.stat().st_mtime)
            indexed += 1
        except Exception as exc:
            errors.append({"path": relative_path, "error": str(exc)})
            _mark_error(relative_path, str(exc))

    deleted = _delete_missing_files(seen_paths)
    _write_quality_report(indexed, skipped, deleted, errors)
    return {"indexed": indexed, "skipped": skipped, "deleted": deleted, "errors": errors}


def _is_unchanged(parsed: ParsedDocument) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select content_hash, status from indexed_files where path = %s", (parsed.path,))
            row = cur.fetchone()
            return bool(row and row[0] == parsed.content_hash and row[1] == "indexed")


async def _index_document(parsed: ParsedDocument, mtime: float) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into documents (
                  path, title, frontmatter, tags, outlinks, status,
                  product, applies_to, plans, customer_safe, updated_at
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                on conflict (path) do update set
                  title = excluded.title,
                  frontmatter = excluded.frontmatter,
                  tags = excluded.tags,
                  outlinks = excluded.outlinks,
                  status = excluded.status,
                  product = excluded.product,
                  applies_to = excluded.applies_to,
                  plans = excluded.plans,
                  customer_safe = excluded.customer_safe,
                  updated_at = now()
                returning id
                """,
                (
                    parsed.path,
                    parsed.title,
                    Json(parsed.frontmatter),
                    parsed.tags,
                    parsed.outlinks,
                    parsed.status,
                    parsed.product,
                    parsed.applies_to,
                    parsed.plans,
                    parsed.customer_safe,
                ),
            )
            document_id = cur.fetchone()[0]
            cur.execute("delete from chunks where document_id = %s", (document_id,))

    for chunk in parsed.chunks:
        embedding = await embed_text(_embedding_input(parsed.title, chunk.heading_path, chunk.text))
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into chunks (
                      document_id, path, heading_path, text, token_count,
                      embedding, fts, metadata
                    ) values (
                      %s, %s, %s, %s, %s,
                      %s::vector,
                      to_tsvector('simple', %s),
                      %s
                    )
                    """,
                    (
                        document_id,
                        parsed.path,
                        chunk.heading_path,
                        chunk.text,
                        max(1, len(chunk.text) // 2),
                        vector_literal(embedding),
                        " ".join([parsed.title, *chunk.heading_path, chunk.text]),
                        Json({
                            "title": parsed.title,
                            "tags": parsed.tags,
                            "outlinks": parsed.outlinks,
                            "product": parsed.product,
                            "applies_to": parsed.applies_to,
                            "plans": parsed.plans,
                            "customer_safe": parsed.customer_safe,
                            "sku": parsed.sku,
                            "aliases": parsed.aliases,
                            "compatible_with": parsed.compatible_with,
                            "alternatives": parsed.alternatives,
                            "limitations": parsed.limitations,
                            "frontmatter": parsed.frontmatter,
                        }),
                    ),
                )

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into indexed_files (path, content_hash, mtime, indexed_at, status, error)
                values (%s, %s, to_timestamp(%s), now(), 'indexed', null)
                on conflict (path) do update set
                  content_hash = excluded.content_hash,
                  mtime = excluded.mtime,
                  indexed_at = now(),
                  status = 'indexed',
                  error = null
                """,
                (parsed.path, parsed.content_hash, mtime),
            )


def _embedding_input(title: str, heading_path: list[str], text: str) -> str:
    heading = " > ".join(heading_path)
    return f"{title}\n{heading}\n{text}" if heading else f"{title}\n{text}"


def _mark_skipped(path: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into indexed_files (path, content_hash, indexed_at, status, error)
                values (%s, '', now(), 'skipped', null)
                on conflict (path) do update set indexed_at = now(), status = 'skipped', error = null
                """,
                (path,),
            )


def _mark_error(path: str, error: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into indexed_files (path, content_hash, indexed_at, status, error)
                values (%s, '', now(), 'error', %s)
                on conflict (path) do update set indexed_at = now(), status = 'error', error = excluded.error
                """,
                (path, error),
            )


def _delete_missing_files(seen_paths: set[str]) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select path from documents")
            existing = {row[0] for row in cur.fetchall()}
            missing = sorted(existing - seen_paths)
            for path in missing:
                cur.execute("delete from documents where path = %s", (path,))
                cur.execute("delete from indexed_files where path = %s", (path,))
            return len(missing)


def _write_quality_report(indexed: int, skipped: int, deleted: int, errors: list[dict[str, str]]) -> None:
    summary = f"indexed={indexed}, skipped={skipped}, deleted={deleted}, errors={len(errors)}"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("insert into quality_reports (summary, issues) values (%s, %s)", (summary, Json(errors)))
