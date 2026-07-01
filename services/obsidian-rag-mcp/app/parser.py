import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.config import settings

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
TAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_\-/\u4e00-\u9fff]+)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class Chunk:
    heading_path: list[str]
    text: str


@dataclass
class ParsedDocument:
    path: str
    title: str
    frontmatter: dict[str, Any]
    tags: list[str]
    outlinks: list[str]
    status: str
    product: str | None
    applies_to: list[str]
    plans: list[str]
    customer_safe: bool
    sku: list[str]
    aliases: list[str]
    compatible_with: list[str]
    alternatives: list[str]
    limitations: list[str]
    chunks: list[Chunk]
    content_hash: str


def _jsonable_frontmatter(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable_frontmatter(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable_frontmatter(item) for item in value]
    return value


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


def should_index(relative_path: str, frontmatter: dict[str, Any]) -> bool:
    path = relative_path.replace("\\", "/")
    if not path.endswith(".md"):
        return False
    if path.startswith(("90_Archive/", "Templates/", "Assets/")):
        return False
    if frontmatter.get("rag") is False:
        return False
    if str(frontmatter.get("status", "")).lower() == "archived":
        return False
    return path.startswith("10_Knowledge/")


def parse_markdown(file_path: Path, vault_path: Path) -> ParsedDocument | None:
    relative_path = file_path.relative_to(vault_path).as_posix()
    raw = file_path.read_text(encoding="utf-8", errors="replace")
    content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    frontmatter: dict[str, Any] = {}
    body = raw
    match = FRONTMATTER_RE.match(raw)
    if match:
        frontmatter = yaml.safe_load(match.group(1)) or {}
        if not isinstance(frontmatter, dict):
            frontmatter = {}
        frontmatter = _jsonable_frontmatter(frontmatter)
        body = raw[match.end():]

    if not should_index(relative_path, frontmatter):
        return None

    title = str(frontmatter.get("title") or "").strip() or _first_heading(body) or file_path.stem
    chunks = _chunk_markdown(body)
    tags = set(_as_list(frontmatter.get("tags")))
    tags.update(TAG_RE.findall(body))
    outlinks = sorted(set(link.strip() for link in WIKILINK_RE.findall(body) if link.strip()))

    return ParsedDocument(
        path=relative_path,
        title=title,
        frontmatter=frontmatter,
        tags=sorted(tags),
        outlinks=outlinks,
        status=str(frontmatter.get("status") or "active"),
        product=str(frontmatter.get("product")) if frontmatter.get("product") else None,
        applies_to=_as_list(frontmatter.get("applies_to")),
        plans=_as_list(frontmatter.get("plans")),
        customer_safe=bool(frontmatter.get("customer_safe", False)),
        sku=_as_list(frontmatter.get("sku")),
        aliases=_as_list(frontmatter.get("aliases")),
        compatible_with=_as_list(frontmatter.get("compatible_with")),
        alternatives=_as_list(frontmatter.get("alternatives")),
        limitations=_as_list(frontmatter.get("limitations")),
        chunks=chunks,
        content_hash=content_hash,
    )


def _first_heading(body: str) -> str | None:
    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if match:
            return match.group(2).strip()
    return None


def _chunk_markdown(body: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    heading_stack: list[str] = []
    buffer: list[str] = []

    def flush():
        text = "\n".join(buffer).strip()
        buffer.clear()
        if text:
            chunks.extend(_split_long_text(text, heading_stack.copy()))

    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            heading = match.group(2).strip()
            heading_stack[:] = heading_stack[: level - 1]
            heading_stack.append(heading)
            continue
        buffer.append(line)
    flush()

    if not chunks and body.strip():
        chunks.extend(_split_long_text(body.strip(), []))
    return chunks


def _split_long_text(text: str, heading_path: list[str]) -> list[Chunk]:
    max_chars = settings.chunk_max_chars
    overlap = settings.chunk_overlap_chars
    if len(text) <= max_chars:
        return [Chunk(heading_path=heading_path, text=text)]
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(Chunk(heading_path=heading_path, text=text[start:end].strip()))
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks
