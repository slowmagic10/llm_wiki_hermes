from __future__ import annotations

from fastapi import HTTPException

from config import SCHEMA_DOC, VAULT_PATH
from path_utils import safe_rel_path


def list_files(path: str = ".") -> dict[str, object]:
    target = safe_rel_path(path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name.startswith(".git"):
            continue
        if child.is_dir() or child.suffix.lower() == ".md":
            entries.append({"name": child.name, "path": child.relative_to(VAULT_PATH).as_posix(), "type": "dir" if child.is_dir() else "file"})
    rel = target.relative_to(VAULT_PATH).as_posix() if target != VAULT_PATH else "."
    parent = None if target == VAULT_PATH else target.parent.relative_to(VAULT_PATH).as_posix()
    return {"path": rel, "parent": parent, "entries": entries}


def file_preview(path: str) -> dict[str, str]:
    target = safe_rel_path(path)
    if not target.exists() or not target.is_file() or target.suffix.lower() != ".md":
        raise HTTPException(status_code=404, detail="markdown file not found")
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"path": target.relative_to(VAULT_PATH).as_posix(), "content": content[:100000]}


def schema_template() -> dict[str, str]:
    if not SCHEMA_DOC.exists():
        return {"content": "schema document not found"}
    return {"path": str(SCHEMA_DOC), "content": SCHEMA_DOC.read_text(encoding="utf-8", errors="replace")}
